from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AgentTrace,
    GatewaySettlement,
    InquiryTicket,
    ReconciliationMatch,
    SalesInvoice,
    MatchStatus,
)


router = APIRouter(
    prefix="/review",
    tags=["Human Review"],
)


# ============================================================
# REQUEST SCHEMAS
# ============================================================


class ResolveTicketRequest(BaseModel):
    resolution_note: str = Field(
        ...,
        min_length=3,
        description="Human reviewer's final reconciliation decision.",
    )


class RejectTicketRequest(BaseModel):
    resolution_note: str = Field(
        ...,
        min_length=3,
        description="Reason the ticket remains unresolved.",
    )


# ============================================================
# HELPERS
# ============================================================


def _serialize_invoice(invoice: SalesInvoice | None) -> dict[str, Any] | None:
    if not invoice:
        return None

    return {
        "id": invoice.id,
        "invoice_id": invoice.invoice_id,
        "order_id": invoice.order_id,
        "merchant_id": invoice.merchant_id,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "status": (
            invoice.status.value
            if hasattr(invoice.status, "value")
            else invoice.status
        ),
        "created_at": (
            invoice.created_at.isoformat()
            if invoice.created_at
            else None
        ),
    }


def _serialize_gateway(
    gateway: GatewaySettlement | None,
) -> dict[str, Any] | None:
    if not gateway:
        return None

    return {
        "id": gateway.id,
        "settlement_id": gateway.settlement_id,
        "order_id": gateway.order_id,
        "merchant_id": gateway.merchant_id,
        "gross_amount": gateway.gross_amount,
        "mdr_fee": gateway.mdr_fee,
        "net_amount": gateway.net_amount,
        "currency": gateway.currency,
        "settled_at": (
            gateway.settled_at.isoformat()
            if gateway.settled_at
            else None
        ),
        "status": (
            gateway.status.value
            if hasattr(gateway.status, "value")
            else gateway.status
        ),
    }


def _serialize_trace(trace: AgentTrace) -> dict[str, Any]:
    return {
        "id": trace.id,
        "step_number": trace.step_number,
        "tool_name": trace.tool_name,
        "tool_input": trace.tool_input,
        "tool_output": trace.tool_output,
        "reasoning": trace.reasoning,
        "tokens_used": trace.tokens_used,
        "created_at": (
            trace.created_at.isoformat()
            if trace.created_at
            else None
        ),
    }


def _serialize_ticket(
    db: Session,
    ticket: InquiryTicket,
) -> dict[str, Any]:
    match = (
        db.query(ReconciliationMatch)
        .filter(ReconciliationMatch.id == ticket.reconciliation_match_id)
        .first()
    )

    invoice = None
    gateway = None

    if match:
        if match.sales_invoice_id:
            invoice = (
                db.query(SalesInvoice)
                .filter(SalesInvoice.id == match.sales_invoice_id)
                .first()
            )

        if match.gateway_settlement_id:
            gateway = (
                db.query(GatewaySettlement)
                .filter(
                    GatewaySettlement.id
                    == match.gateway_settlement_id
                )
                .first()
            )

    traces = (
        db.query(AgentTrace)
        .filter(
            AgentTrace.reconciliation_match_id
            == ticket.reconciliation_match_id
        )
        .order_by(AgentTrace.step_number.asc())
        .all()
    )

    return {
        "ticket": {
            "id": ticket.id,
            "reconciliation_match_id": ticket.reconciliation_match_id,
            "subject": ticket.subject,
            "body": ticket.body,
            "expected_amount": ticket.expected_amount,
            "actual_amount": ticket.actual_amount,
            "missing_fields": ticket.missing_fields or [],
            "resolved": ticket.resolved,
            "resolution_note": ticket.resolution_note,
            "created_at": (
                ticket.created_at.isoformat()
                if ticket.created_at
                else None
            ),
        },
        "match": (
            {
                "id": match.id,
                "order_id": match.order_id,
                "status": (
                    match.status.value
                    if hasattr(match.status, "value")
                    else match.status
                ),
                "match_stage": match.match_stage,
                "variance_amount": match.variance_amount,
                "variance_reason": match.variance_reason,
                "confidence": match.confidence,
                "created_at": (
                    match.created_at.isoformat()
                    if match.created_at
                    else None
                ),
            }
            if match
            else None
        ),
        "invoice": _serialize_invoice(invoice),
        "gateway": _serialize_gateway(gateway),
        "agent_traces": [
            _serialize_trace(trace)
            for trace in traces
        ],
    }


# ============================================================
# LIST OPEN REVIEW TICKETS
# ============================================================


@router.get("/tickets")
def list_review_tickets(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Return all unresolved human-review tickets.

    This is the main endpoint used by the review dashboard.
    """

    tickets = (
        db.query(InquiryTicket)
        .filter(InquiryTicket.resolved.is_(False))
        .order_by(InquiryTicket.created_at.desc())
        .all()
    )

    items = []

    for ticket in tickets:
        match = (
            db.query(ReconciliationMatch)
            .filter(
                ReconciliationMatch.id
                == ticket.reconciliation_match_id
            )
            .first()
        )

        items.append(
            {
                "id": ticket.id,
                "subject": ticket.subject,
                "reconciliation_match_id": ticket.reconciliation_match_id,
                "order_id": (
                    match.order_id
                    if match
                    else None
                ),
                "status": (
                    match.status.value
                    if match and hasattr(match.status, "value")
                    else (
                        match.status
                        if match
                        else None
                    )
                ),
                "expected_amount": ticket.expected_amount,
                "actual_amount": ticket.actual_amount,
                "missing_fields": ticket.missing_fields or [],
                "created_at": (
                    ticket.created_at.isoformat()
                    if ticket.created_at
                    else None
                ),
            }
        )

    return {
        "success": True,
        "count": len(items),
        "tickets": items,
    }


# ============================================================
# GET SINGLE REVIEW TICKET
# ============================================================


@router.get("/tickets/{ticket_id}")
def get_review_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Return the complete evidence package for a human reviewer.
    """

    ticket = (
        db.query(InquiryTicket)
        .filter(InquiryTicket.id == ticket_id)
        .first()
    )

    if not ticket:
        raise HTTPException(
            status_code=404,
            detail="Review ticket not found.",
        )

    return {
        "success": True,
        **_serialize_ticket(db, ticket),
    }


# ============================================================
# RESOLVE TICKET
# ============================================================


@router.post("/tickets/{ticket_id}/resolve")
def resolve_review_ticket(
    ticket_id: str,
    request: ResolveTicketRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Human reviewer confirms the reconciliation.

    This closes the inquiry ticket and marks the associated
    reconciliation match as AGENT_RESOLVED.
    """

    ticket = (
        db.query(InquiryTicket)
        .filter(InquiryTicket.id == ticket_id)
        .first()
    )

    if not ticket:
        raise HTTPException(
            status_code=404,
            detail="Review ticket not found.",
        )

    if ticket.resolved:
        return {
            "success": True,
            "message": "Ticket is already resolved.",
            "ticket_id": ticket.id,
        }

    match = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.id
            == ticket.reconciliation_match_id
        )
        .first()
    )

    if not match:
        raise HTTPException(
            status_code=404,
            detail="Associated reconciliation match not found.",
        )

    note = request.resolution_note.strip()

    ticket.resolved = True
    ticket.resolution_note = note

    match.status = MatchStatus.AGENT_RESOLVED
    match.variance_reason = note[:255]

    db.commit()

    return {
        "success": True,
        "message": "Review ticket resolved successfully.",
        "ticket_id": ticket.id,
        "match_id": match.id,
        "status": match.status.value,
        "resolution_note": note,
    }


# ============================================================
# KEEP TICKET OPEN / REJECT RESOLUTION
# ============================================================


@router.post("/tickets/{ticket_id}/reject")
def reject_review_ticket(
    ticket_id: str,
    request: RejectTicketRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Reviewer explicitly decides that the exception cannot yet
    be resolved.

    The ticket remains open and the note is stored.
    """

    ticket = (
        db.query(InquiryTicket)
        .filter(InquiryTicket.id == ticket_id)
        .first()
    )

    if not ticket:
        raise HTTPException(
            status_code=404,
            detail="Review ticket not found.",
        )

    if ticket.resolved:
        raise HTTPException(
            status_code=400,
            detail="Cannot reject an already resolved ticket.",
        )

    match = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.id
            == ticket.reconciliation_match_id
        )
        .first()
    )

    note = request.resolution_note.strip()

    ticket.resolution_note = note

    if match:
        match.status = MatchStatus.ESCALATED
        match.variance_reason = note[:255]

    db.commit()

    return {
        "success": True,
        "message": "Ticket remains open for further investigation.",
        "ticket_id": ticket.id,
        "match_id": (
            match.id
            if match
            else None
        ),
        "status": (
            match.status.value
            if match
            else "ESCALATED"
        ),
        "resolution_note": note,
    }


# ============================================================
# DASHBOARD SUMMARY
# ============================================================


@router.get("/summary")
def review_summary(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Small dashboard summary for the human-review UI.
    """

    open_tickets = (
        db.query(InquiryTicket)
        .filter(InquiryTicket.resolved.is_(False))
        .count()
    )

    resolved_tickets = (
        db.query(InquiryTicket)
        .filter(InquiryTicket.resolved.is_(True))
        .count()
    )

    escalated_matches = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.status
            == MatchStatus.ESCALATED
        )
        .count()
    )

    agent_resolved_matches = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.status
            == MatchStatus.AGENT_RESOLVED
        )
        .count()
    )

    reconciled_matches = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.status
            == MatchStatus.RECONCILED
        )
        .count()
    )

    return {
        "success": True,
        "open_tickets": open_tickets,
        "resolved_tickets": resolved_tickets,
        "escalated_matches": escalated_matches,
        "agent_resolved_matches": agent_resolved_matches,
        "reconciled_matches": reconciled_matches,
    }