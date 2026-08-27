from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    SalesInvoice,
    GatewaySettlement,
    BankCredit,
    MatchStatus,
)

from app.ingestion.normalizer import NormalizedTransaction


class DatabaseIngestionError(Exception):
    """Raised when normalized data cannot be stored."""


def ingest_transaction(
    db: Session,
    transaction: NormalizedTransaction,
) -> dict[str, Any]:

    source = transaction.source.lower().strip()

    if source == "razorpay":
        return ingest_razorpay(
            db,
            transaction,
        )

    if source == "bank":
        return ingest_bank(
            db,
            transaction,
        )

    if source == "ledger":
        return ingest_ledger(
            db,
            transaction,
        )

    if source == "invoice":
        return ingest_invoice(
            db,
            transaction,
        )

    raise DatabaseIngestionError(
        f"Unsupported source: {source}"
    )


# ============================================================
# RAZORPAY
# ============================================================

def ingest_razorpay(
    db: Session,
    transaction: NormalizedTransaction,
) -> dict[str, Any]:

    settlement_id = transaction.settlement_id

    if not settlement_id:

        raise DatabaseIngestionError(
            "Razorpay transaction is missing settlement_id."
        )

    existing = (
        db.query(GatewaySettlement)
        .filter(
            GatewaySettlement.settlement_id
            == settlement_id
        )
        .first()
    )

    if existing:

        return {
            "action": "existing",
            "source": "razorpay",
            "id": existing.id,
            "settlement_id": existing.settlement_id,
        }

    gross_amount = (
        transaction.gross_amount
        if transaction.gross_amount is not None
        else transaction.amount
    )

    net_amount = (
        transaction.net_amount
        if transaction.net_amount is not None
        else transaction.amount
    )

    if gross_amount is None:
        gross_amount = 0.0

    if net_amount is None:
        net_amount = 0.0

    fee = (
        transaction.fee
        if transaction.fee is not None
        else 0.0
    )

    settlement = GatewaySettlement(
        settlement_id=settlement_id,
        order_id=transaction.order_id,
        merchant_id=transaction.merchant_id,
        gross_amount=float(gross_amount),
        mdr_fee=float(fee),
        net_amount=float(net_amount),
        currency=transaction.currency or "INR",
        settled_at=(
            transaction.transaction_date
            if transaction.transaction_date
            else None
        ),
        status=MatchStatus.PENDING,
    )

    db.add(settlement)
    db.flush()

    return {
        "action": "created",
        "source": "razorpay",
        "id": settlement.id,
        "settlement_id": settlement.settlement_id,
    }


# ============================================================
# BANK
# ============================================================

def ingest_bank(
    db: Session,
    transaction: NormalizedTransaction,
) -> dict[str, Any]:

    txn_ref = (
        transaction.transaction_id
        or transaction.settlement_id
    )

    if not txn_ref:

        raise DatabaseIngestionError(
            "Bank transaction is missing transaction reference."
        )

    existing = (
        db.query(BankCredit)
        .filter(
            BankCredit.txn_ref == txn_ref
        )
        .first()
    )

    if existing:

        return {
            "action": "existing",
            "source": "bank",
            "id": existing.id,
            "txn_ref": existing.txn_ref,
        }

    amount = (
        transaction.amount
        if transaction.amount is not None
        else transaction.net_amount
    )

    if amount is None:

        raise DatabaseIngestionError(
            f"Bank transaction {txn_ref} has no amount."
        )

    credit = BankCredit(
        txn_ref=txn_ref,
        order_id=transaction.order_id,
        amount=float(amount),
        currency=transaction.currency or "INR",
        credited_at=(
            transaction.transaction_date
            if transaction.transaction_date
            else None
        ),
        narration=transaction.narration or "",
        status=MatchStatus.PENDING,
    )

    db.add(credit)
    db.flush()

    return {
        "action": "created",
        "source": "bank",
        "id": credit.id,
        "txn_ref": credit.txn_ref,
    }


# ============================================================
# LEDGER
# ============================================================

def ingest_ledger(
    db: Session,
    transaction: NormalizedTransaction,
) -> dict[str, Any]:

    invoice_id = (
        transaction.invoice_id
        or transaction.transaction_id
    )

    if not invoice_id:

        raise DatabaseIngestionError(
            "Ledger transaction is missing invoice ID."
        )

    existing = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.invoice_id
            == invoice_id
        )
        .first()
    )

    if existing:

        return {
            "action": "existing",
            "source": "ledger",
            "id": existing.id,
            "invoice_id": existing.invoice_id,
        }

    amount = (
        transaction.amount
        if transaction.amount is not None
        else transaction.gross_amount
    )

    if amount is None:

        raise DatabaseIngestionError(
            f"Ledger invoice {invoice_id} has no amount."
        )

    invoice = SalesInvoice(
        invoice_id=invoice_id,
        order_id=transaction.order_id,
        merchant_id=transaction.merchant_id,
        amount=float(amount),
        currency=transaction.currency or "INR",
        created_at=(
            transaction.transaction_date
            if transaction.transaction_date
            else None
        ),
        status=MatchStatus.PENDING,
    )

    db.add(invoice)
    db.flush()

    return {
        "action": "created",
        "source": "ledger",
        "id": invoice.id,
        "invoice_id": invoice.invoice_id,
    }


# ============================================================
# INVOICE
# ============================================================

def ingest_invoice(
    db: Session,
    transaction: NormalizedTransaction,
) -> dict[str, Any]:

    invoice_id = (
        transaction.invoice_id
        or transaction.transaction_id
    )

    if not invoice_id:

        raise DatabaseIngestionError(
            "Invoice transaction is missing invoice ID."
        )

    existing = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.invoice_id
            == invoice_id
        )
        .first()
    )

    if existing:

        return {
            "action": "existing",
            "source": "invoice",
            "id": existing.id,
            "invoice_id": existing.invoice_id,
        }

    amount = (
        transaction.amount
        if transaction.amount is not None
        else transaction.gross_amount
    )

    if amount is None:

        raise DatabaseIngestionError(
            f"Invoice {invoice_id} has no amount."
        )

    invoice = SalesInvoice(
        invoice_id=invoice_id,
        order_id=transaction.order_id,
        merchant_id=transaction.merchant_id,
        amount=float(amount),
        currency=transaction.currency or "INR",
        created_at=(
            transaction.transaction_date
            if transaction.transaction_date
            else None
        ),
        status=MatchStatus.PENDING,
    )

    db.add(invoice)
    db.flush()

    return {
        "action": "created",
        "source": "invoice",
        "id": invoice.id,
        "invoice_id": invoice.invoice_id,
    }


# ============================================================
# BULK INGESTION
# ============================================================

def ingest_transactions(
    db: Session,
    transactions: list[NormalizedTransaction],
) -> dict[str, Any]:

    created = 0
    existing = 0
    failed = 0

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, transaction in enumerate(
        transactions,
        start=1,
    ):

        try:

            result = ingest_transaction(
                db,
                transaction,
            )

            records.append(result)

            if result["action"] == "created":
                created += 1

            elif result["action"] == "existing":
                existing += 1

        except Exception as exc:

            failed += 1

            errors.append(
                {
                    "row_number": index,
                    "source": transaction.source,
                    "transaction_id": (
                        transaction.transaction_id
                    ),
                    "error": str(exc),
                }
            )

    if failed:

        db.rollback()

        return {
            "success": False,
            "created": 0,
            "existing": existing,
            "failed": failed,
            "records": records,
            "errors": errors,
        }

    db.commit()

    return {
        "success": True,
        "created": created,
        "existing": existing,
        "failed": 0,
        "records": records,
        "errors": [],
    }