from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    ReconciliationMatch,
    SalesInvoice,
    GatewaySettlement,
    MatchStatus,
)

from app.human_review.tickets import (
    create_inquiry_ticket,
)


def escalate_to_human(
    db: Session,
    match: ReconciliationMatch,
    invoice: SalesInvoice | None = None,
    gateway: GatewaySettlement | None = None,
    reason: str = "",
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:

    match.status = MatchStatus.ESCALATED

    match.variance_reason = (
        reason[:255]
        if reason
        else "AI investigation could not resolve the exception."
    )

    db.commit()

    ticket = create_inquiry_ticket(
        db=db,
        match=match,
        invoice=invoice,
        gateway=gateway,
        note=reason,
        missing_fields=missing_fields,
    )

    return {
        "success": True,
        "status": "ESCALATED",
        "match_id": match.id,
        "ticket_id": ticket.id,
        "message": (
            "Reconciliation exception escalated "
            "to human review."
        ),
    }


def mark_ai_resolved(
    db: Session,
    match: ReconciliationMatch,
    resolution_note: str,
) -> dict[str, Any]:

    match.status = MatchStatus.AGENT_RESOLVED

    match.variance_reason = (
        resolution_note[:255]
    )

    db.commit()

    return {
        "success": True,
        "status": "AGENT_RESOLVED",
        "match_id": match.id,
        "resolution_note": resolution_note,
    }