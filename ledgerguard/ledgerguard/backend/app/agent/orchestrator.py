"""
Exception-resolution agent orchestrator.

Flow:

ML uncertain
    ->
AI investigation
    ->
tool calls
    ->
AgentTrace
    ->
write_correction
    ->
AGENT_RESOLVED or ESCALATED
    ->
InquiryTicket for human review

The agent is intentionally explicit and auditable.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.llm_provider import resilient_chat

from app.models import (
    ReconciliationMatch,
    SalesInvoice,
    GatewaySettlement,
    AgentTrace,
)

from app.agent.tools import (
    contract_rag_search,
    comms_search,
    fx_lookup,
    write_correction,
    TOOL_SCHEMAS,
)

from app.human_review.tickets import create_inquiry_ticket


MAX_STEPS = 6


SYSTEM_PROMPT = """
You are a finance reconciliation investigator.

Your job is to investigate an uncertain reconciliation produced by
an ML-based reconciliation system.

You are given:

- internal invoice information
- payment gateway settlement information
- ML candidate information
- relevant contract information when available
- relevant internal communication when available

Your job is to determine whether there is concrete evidence explaining
the discrepancy.

IMPORTANT SAFETY RULES:

1. Never invent a transaction, invoice, payment, contract clause,
   communication, or financial explanation.

2. Only conclude resolved=true when concrete evidence supports the
   explanation.

3. If evidence is insufficient, conclude resolved=false.

4. A close amount alone is NOT enough evidence for resolution.

5. If multiple invoices have similar amounts, do not arbitrarily
   select one.

6. Contract terms, internal messages, and FX results can be used as
   supporting evidence.

7. Before every tool call, write ONE short sentence explaining what
   you are checking.

8. Always finish with write_correction.

9. If you cannot establish a defensible explanation, escalate to
   human review.
"""


def resolve_exception(
    db: Session,
    match_id: str,
) -> dict:

    # =========================================================
    # 1. Load reconciliation match
    # =========================================================

    match = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.id == match_id
        )
        .first()
    )

    if not match:

        return {
            "success": False,
            "error": "match not found",
        }

    # =========================================================
    # 2. Load invoice
    # =========================================================

    invoice = None

    if match.sales_invoice_id:

        invoice = (
            db.query(SalesInvoice)
            .filter(
                SalesInvoice.id
                == match.sales_invoice_id
            )
            .first()
        )

    # =========================================================
    # 3. Load gateway
    # =========================================================

    gateway = None

    if match.gateway_settlement_id:

        gateway = (
            db.query(GatewaySettlement)
            .filter(
                GatewaySettlement.id
                == match.gateway_settlement_id
            )
            .first()
        )

    # =========================================================
    # 4. Prefetch context
    # =========================================================

    merchant_id = (
        invoice.merchant_id
        if invoice
        else None
    )

    order_id = (
        match.order_id
        or (
            invoice.order_id
            if invoice
            else None
        )
        or (
            gateway.order_id
            if gateway
            else None
        )
    )

    contract_context = (
        _prefetch_contract_context(
            db,
            merchant_id,
        )
    )

    comms_context = (
        _prefetch_comms_context(
            db,
            order_id,
        )
    )

    # =========================================================
    # 5. Build case summary
    # =========================================================

    case_summary = _build_case_summary(
        match=match,
        invoice=invoice,
        gateway=gateway,
        order_id=order_id,
    )

    if contract_context:

        case_summary += (
            "\nRelevant contract terms:\n"
            f"{contract_context}\n"
        )

    else:

        case_summary += (
            "\nNo contract context was found automatically.\n"
        )

    if comms_context:

        case_summary += (
            "\nRelevant internal messages:\n"
            f"{comms_context}\n"
        )

    else:

        case_summary += (
            "\nNo internal messages were found for this order.\n"
        )

    # =========================================================
    # 6. Start agent conversation
    # =========================================================

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": (
                "Investigate this reconciliation exception:\n\n"
                f"{case_summary}"
            ),
        },
    ]

    # =========================================================
    # 7. Agent loop
    # =========================================================

    for step in range(
        1,
        MAX_STEPS + 1,
    ):

        response = resilient_chat(
            messages,
            tools=TOOL_SCHEMAS,
        )

        # -----------------------------------------------------
        # Model didn't call a tool
        # -----------------------------------------------------

        if not response.tool_calls:

            messages.append(
                {
                    "role": "assistant",
                    "content": response.text or "",
                }
            )

            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You must now call write_correction "
                        "with either resolved=true or resolved=false."
                    ),
                }
            )

            continue

        # -----------------------------------------------------
        # Execute tool calls
        # -----------------------------------------------------

        for call in response.tool_calls:

            name = call["name"]

            args = (
                call["arguments"]
                or {}
            )

            output = _execute_tool(
                db=db,
                name=name,
                args=args,
                match_id=match_id,
            )

            tokens = _extract_token_usage(
                response
            )

            _log_trace(
                db=db,
                match_id=match.id,
                step=step,
                tool_name=name,
                tool_input=args,
                tool_output=output,
                reasoning=response.text,
                tokens_used=tokens,
            )

            messages.append(
                {
                    "role": "assistant",
                    "content": (
                        response.text
                        or f"Calling {name}"
                    ),
                }
            )

            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Tool result: "
                        f"{json.dumps(output)}"
                    ),
                }
            )

            # -------------------------------------------------
            # Final agent decision
            # -------------------------------------------------

            if name == "write_correction":

                if not output.get("success"):

                    continue

                new_status = output.get(
                    "new_status"
                )

                # ---------------------------------------------
                # Escalate to human
                # ---------------------------------------------

                if new_status == "ESCALATED":

                    ticket = create_inquiry_ticket(
                        db=db,
                        match=match,
                        invoice=invoice,
                        gateway=gateway,
                        note=args.get(
                            "resolution_note",
                            "",
                        ),
                    )

                    return {
                        "success": True,
                        "match_id": match_id,
                        "final_status": "ESCALATED",
                        "ticket_id": ticket.id,
                        "steps": step,
                    }

                # ---------------------------------------------
                # Agent successfully resolved
                # ---------------------------------------------

                return {
                    "success": True,
                    "match_id": match_id,
                    "final_status": new_status,
                    "steps": step,
                }

    # =========================================================
    # 8. Maximum steps reached
    # =========================================================

    output = write_correction(
        db,
        match_id,
        (
            "Agent exceeded the maximum investigation steps "
            "without obtaining sufficient evidence."
        ),
        resolved=False,
    )

    ticket = create_inquiry_ticket(
        db=db,
        match=match,
        invoice=invoice,
        gateway=gateway,
        note=(
            "Agent exceeded maximum investigation steps."
        ),
    )

    return {
        "success": True,
        "match_id": match_id,
        "final_status": "ESCALATED",
        "ticket_id": ticket.id,
        "steps": MAX_STEPS,
    }


# =============================================================
# CASE SUMMARY
# =============================================================

def _build_case_summary(
    match: ReconciliationMatch,
    invoice: SalesInvoice | None,
    gateway: GatewaySettlement | None,
    order_id: str | None,
) -> str:

    lines = [
        f"Match ID: {match.id}",
        f"Order ID: {order_id or 'unknown'}",
        f"Match stage: {match.match_stage}",
        (
            "Variance reason: "
            f"{match.variance_reason or 'unknown'}"
        ),
        (
            "Existing confidence: "
            f"{match.confidence or 'unknown'}"
        ),
    ]

    # ---------------------------------------------------------
    # Invoice
    # ---------------------------------------------------------

    if invoice:

        lines.extend(
            [
                "",
                "INTERNAL INVOICE",
                f"Invoice ID: {invoice.invoice_id}",
                f"Order ID: {invoice.order_id}",
                f"Amount: {invoice.amount}",
                f"Currency: {invoice.currency}",
                f"Merchant ID: {invoice.merchant_id or 'unknown'}",
            ]
        )

    else:

        lines.extend(
            [
                "",
                "INTERNAL INVOICE",
                "No invoice record is attached to this match.",
            ]
        )

    # ---------------------------------------------------------
    # Gateway
    # ---------------------------------------------------------

    if gateway:

        lines.extend(
            [
                "",
                "PAYMENT GATEWAY",
                (
                    "Settlement ID: "
                    f"{gateway.settlement_id}"
                ),
                (
                    "Order ID: "
                    f"{gateway.order_id or 'unknown'}"
                ),
                (
                    "Gross amount: "
                    f"{gateway.gross_amount}"
                ),
                (
                    "MDR fee: "
                    f"{gateway.mdr_fee}"
                ),
                (
                    "Net amount: "
                    f"{gateway.net_amount}"
                ),
                (
                    "Currency: "
                    f"{gateway.currency}"
                ),
                (
                    "Settled at: "
                    f"{gateway.settled_at}"
                ),
            ]
        )

    else:

        lines.extend(
            [
                "",
                "PAYMENT GATEWAY",
                "No gateway record is attached to this match.",
            ]
        )

    return "\n".join(lines)


# =============================================================
# CONTEXT PREFETCH
# =============================================================

def _prefetch_contract_context(
    db: Session,
    merchant_id: str | None,
) -> str | None:

    if not merchant_id:
        return None

    try:

        result = contract_rag_search(
            db,
            merchant_id,
            "MDR fee rate refund discount terms",
        )

        results = result.get(
            "results",
            [],
        )

        if not results:
            return None

        return "\n".join(
            result["text"]
            for result in results
        )

    except Exception:

        return None


def _prefetch_comms_context(
    db: Session,
    order_id: str | None,
) -> str | None:

    if not order_id:
        return None

    try:

        result = comms_search(
            db,
            order_id,
        )

        results = result.get(
            "results",
            [],
        )

        if not results:
            return None

        return "\n".join(
            (
                f"[{message['channel']}] "
                f"{message['sender']}: "
                f"{message['text']}"
            )
            for message in results
        )

    except Exception:

        return None


# =============================================================
# TOOL EXECUTION
# =============================================================

def _execute_tool(
    db: Session,
    name: str,
    args: dict,
    match_id: str,
) -> dict:

    if name == "contract_rag_search":

        return contract_rag_search(
            db,
            args.get(
                "merchant_id",
                "",
            ),
            args.get(
                "query",
                "",
            ),
        )

    if name == "comms_search":

        return comms_search(
            db,
            args.get(
                "order_id",
                "",
            ),
            args.get(
                "keyword"
            ),
        )

    if name == "fx_lookup":

        return fx_lookup(
            args.get(
                "from_currency",
                "",
            ),
            args.get(
                "to_currency",
                "",
            ),
        )

    if name == "write_correction":

        return write_correction(
            db,
            match_id,
            args.get(
                "resolution_note",
                "",
            ),
            args.get(
                "resolved",
                False,
            ),
        )

    return {
        "error": (
            f"Unknown tool: {name}"
        )
    }


# =============================================================
# TRACE
# =============================================================

def _extract_token_usage(
    response,
) -> int | None:

    raw = getattr(
        response,
        "raw",
        {},
    ) or {}

    usage = (
        raw.get("usageMetadata")
        or raw.get("usage")
    )

    if not usage:
        return None

    return (
        usage.get(
            "totalTokenCount"
        )
        or usage.get(
            "total_tokens"
        )
    )


def _log_trace(
    db: Session,
    match_id: str,
    step: int,
    tool_name: str,
    tool_input: dict,
    tool_output: dict,
    reasoning: str | None,
    tokens_used: int | None = None,
):

    trace = AgentTrace(
        reconciliation_match_id=match_id,
        step_number=step,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        reasoning=reasoning or "",
        tokens_used=tokens_used,
    )

    db.add(trace)
    db.commit()