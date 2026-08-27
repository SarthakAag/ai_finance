from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    InquiryTicket,
    ReconciliationMatch,
    SalesInvoice,
    GatewaySettlement,
)


def create_inquiry_ticket(
    db: Session,
    match: ReconciliationMatch,
    invoice: SalesInvoice | None = None,
    gateway: GatewaySettlement | None = None,
    note: str = "",
    missing_fields: list[str] | None = None,
) -> InquiryTicket:

    if missing_fields is None:
        missing_fields = [
            "settlement_confirmation",
            "variance_explanation",
        ]

    expected_amount = (
        invoice.amount
        if invoice is not None
        else None
    )

    actual_amount = (
        gateway.net_amount
        if gateway is not None
        else None
    )

    subject = (
        f"Reconciliation exception: "
        f"Order {match.order_id or 'Unknown'}"
    )

    body = (
        "An unresolved reconciliation exception "
        "requires human review.\n\n"
        f"Order ID: {match.order_id or 'Unknown'}\n"
        f"Match ID: {match.id}\n"
        f"Invoice amount: "
        f"{expected_amount if expected_amount is not None else 'unknown'}\n"
        f"Gateway amount: "
        f"{gateway.gross_amount if gateway else 'unknown'}\n"
        f"Gateway net amount: "
        f"{gateway.net_amount if gateway else 'unknown'}\n"
        f"Variance reason: "
        f"{match.variance_reason or 'unknown'}\n\n"
        f"Investigation notes:\n"
        f"{note or 'No additional notes available.'}\n\n"
        "Missing information:\n"
        + "\n".join(
            f"- {field}"
            for field in missing_fields
        )
        + "\n\n"
        "Please review the transaction and provide "
        "the final reconciliation decision."
    )

    ticket = InquiryTicket(
        reconciliation_match_id=match.id,
        subject=subject,
        body=body,
        expected_amount=expected_amount,
        actual_amount=actual_amount,
        missing_fields=missing_fields,
        resolved=False,
    )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return ticket


def get_ticket(
    db: Session,
    ticket_id: str,
) -> InquiryTicket | None:

    return (
        db.query(InquiryTicket)
        .filter(
            InquiryTicket.id == ticket_id
        )
        .first()
    )


def resolve_ticket(
    db: Session,
    ticket_id: str,
    resolution_note: str,
) -> dict[str, Any]:

    ticket = get_ticket(
        db,
        ticket_id,
    )

    if ticket is None:
        return {
            "success": False,
            "error": "Ticket not found.",
        }

    ticket.resolved = True
    ticket.resolution_note = resolution_note

    match = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.id
            == ticket.reconciliation_match_id
        )
        .first()
    )

    if match is not None:
        match.status = "AGENT_RESOLVED"
        match.variance_reason = (
            resolution_note[:255]
        )

    db.commit()

    return {
        "success": True,
        "ticket_id": ticket.id,
        "match_id": (
            match.id
            if match
            else None
        ),
        "resolved": True,
    }