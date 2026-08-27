from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import SalesInvoice, GatewaySettlement


def amount_difference(
    first: float | None,
    second: float | None,
) -> float:
    if first is None or second is None:
        return 999999.0

    return round(
        abs(float(first) - float(second)),
        2,
    )


def amount_ratio(
    first: float | None,
    second: float | None,
) -> float:
    if first is None or second is None:
        return 1.0

    first = float(first)

    if first == 0:
        return 1.0

    return round(
        abs(float(first) - float(second)) / abs(first),
        6,
    )


def find_invoice_candidates(
    db: Session,
    gateway: GatewaySettlement,
    limit: int = 10,
) -> list[dict[str, Any]]:

    invoices = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.currency
            == gateway.currency
        )
        .all()
    )

    candidates = []

    for invoice in invoices:

        # Strong identifier match
        order_match = (
            gateway.order_id is not None
            and invoice.order_id is not None
            and gateway.order_id.strip().lower()
            == invoice.order_id.strip().lower()
        )

        difference = amount_difference(
            invoice.amount,
            gateway.gross_amount,
        )

        ratio = amount_ratio(
            invoice.amount,
            gateway.gross_amount,
        )

        # Candidate scoring.
        #
        # This is NOT the final reconciliation decision.
        # It only determines which records should be passed
        # to the ML resolver.

        score = 0.0

        if order_match:
            score += 0.70

        # Very close amount
        if ratio <= 0.01:
            score += 0.25

        elif ratio <= 0.03:
            score += 0.15

        elif ratio <= 0.05:
            score += 0.05

        # Same currency
        if (
            invoice.currency
            and gateway.currency
            and invoice.currency
            == gateway.currency
        ):
            score += 0.05

        candidates.append(
            {
                "invoice": invoice,
                "score": round(
                    min(score, 1.0),
                    4,
                ),
                "order_match": order_match,
                "amount_difference": difference,
                "amount_ratio": ratio,
            }
        )

    candidates.sort(
        key=lambda item: (
            item["score"],
            -item["amount_difference"],
        ),
        reverse=True,
    )

    return candidates[:limit]