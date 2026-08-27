"""
Bridges the ingestion pipeline (parse -> normalize -> validate) to the
actual reconciliation tables. Without this, uploaded files get parsed and
echoed back as JSON but never become SalesInvoice / GatewaySettlement /
BankCredit rows -- so /reconcile/run has nothing new to work with and
matches/exceptions/tickets stay empty no matter what gets uploaded.

One NormalizedTransaction -> one row in the table matching its source:
    "invoice"  -> SalesInvoice
    "razorpay" -> GatewaySettlement
    "bank"     -> BankCredit
    "ledger"   -> not reconciled directly (no ledger table yet); skipped
                  with a note in the result so the gap is visible, not silent.

Existing rows are matched on their natural unique key (invoice_id /
settlement_id / txn_ref) so re-uploading the same file is idempotent
rather than creating duplicates.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.ingestion.normalizer import NormalizedTransaction
from app.models import SalesInvoice, GatewaySettlement, BankCredit, MatchStatus


def _fallback_id(prefix: str, index: int) -> str:
    """Uploaded rows aren't guaranteed to have every ID field filled in --
    fall back to a stable synthetic id rather than dropping the row."""
    return f"{prefix}-UPLOAD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{index}"


def persist_transactions(
    db: Session,
    source: str,
    transactions: list[NormalizedTransaction],
) -> dict[str, Any]:
    """Writes normalized transactions into the matching reconciliation
    table. Returns a summary so the API response can show what actually
    landed in the database, not just what was parsed."""

    created = 0
    updated = 0
    skipped = 0
    skipped_reasons: list[str] = []

    for i, txn in enumerate(transactions):
        if source == "invoice":
            invoice_id = txn.invoice_id or txn.transaction_id or _fallback_id("INV", i)
            existing = db.query(SalesInvoice).filter(SalesInvoice.invoice_id == invoice_id).first()

            if txn.amount is None or not txn.order_id:
                skipped += 1
                skipped_reasons.append(f"row {i+1}: missing amount or order_id")
                continue

            if existing:
                existing.amount = txn.amount
                existing.currency = txn.currency or "INR"
                if txn.transaction_date:
                    existing.created_at = txn.transaction_date
                updated += 1
            else:
                db.add(SalesInvoice(
                    invoice_id=invoice_id,
                    order_id=txn.order_id,
                    merchant_id=txn.merchant_id or "unknown_merchant",
                    amount=txn.amount,
                    currency=txn.currency or "INR",
                    created_at=txn.transaction_date or datetime.utcnow(),
                    status=MatchStatus.PENDING,
                ))
                created += 1

        elif source == "razorpay":
            settlement_id = txn.settlement_id or txn.transaction_id or _fallback_id("STL", i)
            existing = db.query(GatewaySettlement).filter(GatewaySettlement.settlement_id == settlement_id).first()

            gross = txn.gross_amount if txn.gross_amount is not None else txn.amount
            if gross is None or not txn.order_id:
                skipped += 1
                skipped_reasons.append(f"row {i+1}: missing amount or order_id")
                continue

            net = txn.net_amount if txn.net_amount is not None else gross
            fee = txn.fee if txn.fee is not None else round(gross - net, 2)

            if existing:
                existing.gross_amount = gross
                existing.net_amount = net
                existing.mdr_fee = fee
                existing.currency = txn.currency or "INR"
                if txn.transaction_date:
                    existing.settled_at = txn.transaction_date
                updated += 1
            else:
                db.add(GatewaySettlement(
                    settlement_id=settlement_id,
                    order_id=txn.order_id,
                    merchant_id=txn.merchant_id or "unknown_merchant",
                    gross_amount=gross,
                    mdr_fee=fee,
                    net_amount=net,
                    currency=txn.currency or "INR",
                    settled_at=txn.transaction_date or datetime.utcnow(),
                    status=MatchStatus.PENDING,
                ))
                created += 1

        elif source == "bank":
            txn_ref = txn.transaction_id or _fallback_id("BNK", i)
            existing = db.query(BankCredit).filter(BankCredit.txn_ref == txn_ref).first()

            if txn.amount is None:
                skipped += 1
                skipped_reasons.append(f"row {i+1}: missing amount")
                continue

            if existing:
                existing.amount = txn.amount
                existing.currency = txn.currency or "INR"
                existing.narration = txn.narration or existing.narration
                if txn.transaction_date:
                    existing.credited_at = txn.transaction_date
                updated += 1
            else:
                db.add(BankCredit(
                    txn_ref=txn_ref,
                    order_id=txn.order_id,  # bank feeds often lack this -- fine, nullable
                    amount=txn.amount,
                    currency=txn.currency or "INR",
                    credited_at=txn.transaction_date or datetime.utcnow(),
                    narration=txn.narration or "",
                    status=MatchStatus.PENDING,
                ))
                created += 1

        else:
            # "ledger" (or anything else) has no dedicated reconciliation
            # table yet -- skip explicitly rather than silently dropping.
            skipped += 1
            skipped_reasons.append(f"row {i+1}: source '{source}' has no reconciliation table yet")

    db.commit()

    return {
        "rows_created": created,
        "rows_updated": updated,
        "rows_skipped": skipped,
        "skipped_reasons": skipped_reasons[:10],  # cap so the response doesn't explode on bad files
    }