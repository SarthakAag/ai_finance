from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Any

import pandas as pd


class NormalizationError(Exception):
    """Raised when source data cannot be normalized."""


@dataclass
class NormalizedTransaction:
    """
    Common transaction representation used by LedgerGuard.
    """

    source: str

    transaction_id: str | None = None
    invoice_id: str | None = None
    order_id: str | None = None
    settlement_id: str | None = None
    merchant_id: str | None = None

    amount: float | None = None
    gross_amount: float | None = None
    net_amount: float | None = None
    fee: float | None = None

    currency: str = "INR"

    transaction_date: datetime | None = None

    narration: str | None = None

    raw_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# COLUMN ALIASES
# ============================================================

COLUMN_ALIASES: dict[str, set[str]] = {

    "transaction_id": {
        "transaction_id",
        "transactionid",
        "txn_id",
        "txnid",
        "transaction",
        "txn",
        "reference",
        "reference_id",
        "referenceid",
        "payment_id",
        "paymentid",
    },

    "invoice_id": {
        "invoice_id",
        "invoiceid",
        "invoice",
        "invoice_no",
        "invoiceno",
        "invoice_number",
        "invoicenumber",
        "bill_no",
        "bill_number",
    },

    "order_id": {
        "order_id",
        "orderid",
        "order",
        "order_number",
        "ordernumber",
        "merchant_order_id",
        "merchantorderid",
    },

    "settlement_id": {
        "settlement_id",
        "settlementid",
        "settlement",
        "settlement_number",
        "settlementnumber",
    },

    "merchant_id": {
        "merchant_id",
        "merchantid",
        "merchant",
        "merchant_code",
        "merchantcode",
    },

    "amount": {
        "amount",
        "value",
        "transaction_amount",
        "transactionamount",
        "payment_amount",
        "paymentamount",
        "total_amount",
        "totalamount",
    },

    "gross_amount": {
        "gross_amount",
        "grossamount",
        "gross",
        "gross_value",
        "grossvalue",
    },

    "net_amount": {
        "net_amount",
        "netamount",
        "net",
        "settlement_amount",
        "settlementamount",
        "settled_amount",
        "settledamount",
        "credited_amount",
        "creditedamount",
    },

    "fee": {
        "fee",
        "fees",
        "mdr",
        "mdr_fee",
        "mdrfee",
        "processing_fee",
        "processingfee",
        "gateway_fee",
        "gatewayfee",
        "charges",
        "charge",
    },

    "currency": {
        "currency",
        "currency_code",
        "currencycode",
        "curr",
    },

    "transaction_date": {
        "date",
        "transaction_date",
        "transactiondate",
        "txn_date",
        "txndate",
        "payment_date",
        "paymentdate",
        "settlement_date",
        "settlementdate",
        "settled_at",
        "settledat",
        "credited_at",
        "creditedat",
        "created_at",
        "createdat",
    },

    "narration": {
        "narration",
        "description",
        "details",
        "remarks",
        "remark",
        "notes",
        "note",
        "particulars",
        "transaction_description",
        "transactiondescription",
    },

    "utr": {
        "utr",
        "utr_number",
        "utrnumber",
        "bank_reference",
        "bankreference",
        "bank_ref",
        "bankref",
    },

    "debit": {
        "debit",
        "debit_amount",
        "debitamount",
        "withdrawal",
        "withdrawal_amount",
        "withdrawalamount",
    },

    "credit": {
        "credit",
        "credit_amount",
        "creditamount",
        "deposit",
        "deposit_amount",
        "depositamount",
    },
}


# ============================================================
# COLUMN HELPERS
# ============================================================

def clean_column_name(value: Any) -> str:

    if value is None:
        return ""

    text = str(value).strip().lower()

    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)

    return text.strip("_")


def build_column_map(
    columns: list[Any],
) -> dict[str, str]:

    cleaned_to_original: dict[str, str] = {}

    for column in columns:

        cleaned = clean_column_name(column)

        if cleaned:
            cleaned_to_original[cleaned] = str(column)

    result: dict[str, str] = {}

    for internal_name, aliases in COLUMN_ALIASES.items():

        for alias in aliases:

            if alias in cleaned_to_original:

                result[internal_name] = cleaned_to_original[alias]

                break

    return result


# ============================================================
# SOURCE DETECTION
# ============================================================

SOURCE_KEYWORDS: dict[str, set[str]] = {

    "razorpay": {
        "razorpay",
        "payment_id",
        "settlement_id",
        "settlement_amount",
        "payment_method",
        "fee",
        "mdr",
    },

    "bank": {
        "utr",
        "credit",
        "debit",
        "narration",
        "bank_reference",
        "withdrawal",
        "deposit",
    },

    "ledger": {
        "invoice_id",
        "invoice_no",
        "invoice_number",
        "debit",
        "credit",
        "ledger",
        "customer",
        "account",
    },

    "invoice": {
        "invoice_id",
        "invoice_no",
        "invoice_number",
        "customer",
        "tax",
        "subtotal",
    },
}


def detect_source(
    dataframe: pd.DataFrame,
    filename: str = "",
) -> str:

    filename_lower = str(filename).lower()

    for source in (
        "razorpay",
        "bank",
        "ledger",
        "invoice",
    ):

        if source in filename_lower:
            return source

    columns: set[str] = set()

    for column in list(dataframe.columns):
        columns.add(clean_column_name(column))

    scores = {
        "razorpay": 0,
        "bank": 0,
        "ledger": 0,
        "invoice": 0,
    }

    for source, keywords in SOURCE_KEYWORDS.items():

        for keyword in keywords:

            cleaned_keyword = clean_column_name(keyword)

            if cleaned_keyword in columns:
                scores[source] += 1

    best_source = max(
        scores,
        key=scores.get,
    )

    if scores[best_source] == 0:

        raise NormalizationError(
            "Unable to determine payment source automatically. "
            "Please provide source explicitly."
        )

    return best_source


# ============================================================
# SAFE VALUE HELPERS
# ============================================================

def is_missing(value: Any) -> bool:

    if value is None:
        return True

    if isinstance(value, str):

        return value.strip() == ""

    # Handle normal Python numeric values without Pandas.
    if isinstance(value, (int, float)):

        return False

    # Handle Pandas NaT/NA carefully.
    try:

        value_type = type(value).__name__

        if value_type in {
            "NaTType",
            "NAType",
        }:

            return True

    except Exception:
        pass

    return False


def safe_string(
    value: Any,
) -> str | None:

    if is_missing(value):
        return None

    text = str(value).strip()

    if not text:
        return None

    return text


def safe_float(
    value: Any,
) -> float | None:

    if is_missing(value):
        return None

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, (int, float)):

        try:
            return float(value)

        except Exception:
            return None

    text = str(value).strip()

    if not text:
        return None

    text = (
        text
        .replace(",", "")
        .replace("₹", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
    )

    if text.startswith("(") and text.endswith(")"):

        text = "-" + text[1:-1]

    try:

        return float(text)

    except (
        TypeError,
        ValueError,
    ):

        return None


def safe_datetime(
    value: Any,
) -> datetime | None:
    """
    Convert common financial date formats to datetime.

    IMPORTANT:
    Do NOT use pandas.to_datetime() here.
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    # Pandas Timestamp can be converted directly.
    if type(value).__name__ == "Timestamp":

        try:
            return value.to_pydatetime()

        except Exception:
            return None

    text = str(value).strip()

    if not text:
        return None

    formats = (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%d-%b-%Y",
        "%d %b %Y",
        "%d %B %Y",
    )

    for date_format in formats:

        try:

            return datetime.strptime(
                text,
                date_format,
            )

        except ValueError:

            continue

    # Excel serial date support.
    if isinstance(value, (int, float)):

        try:

            excel_epoch = datetime(
                1899,
                12,
                30,
            )

            return (
                excel_epoch
                + timedelta(
                    days=float(value)
                )
            )

        except Exception:

            return None

    return None


# ============================================================
# ROW HELPERS
# ============================================================

def get_value(
    row: dict[str, Any],
    column_map: dict[str, str],
    field: str,
) -> Any:

    actual_column = column_map.get(field)

    if actual_column is None:
        return None

    return row.get(actual_column)


# ============================================================
# RAZORPAY
# ============================================================

def normalize_razorpay_row(
    row: dict[str, Any],
    column_map: dict[str, str],
) -> NormalizedTransaction:

    payment_id = safe_string(
        get_value(
            row,
            column_map,
            "transaction_id",
        )
    )

    order_id = safe_string(
        get_value(
            row,
            column_map,
            "order_id",
        )
    )

    settlement_id = safe_string(
        get_value(
            row,
            column_map,
            "settlement_id",
        )
    )

    amount = safe_float(
        get_value(
            row,
            column_map,
            "amount",
        )
    )

    fee = safe_float(
        get_value(
            row,
            column_map,
            "fee",
        )
    )

    settlement_amount = safe_float(
        get_value(
            row,
            column_map,
            "net_amount",
        )
    )

    currency = (
        safe_string(
            get_value(
                row,
                column_map,
                "currency",
            )
        )
        or "INR"
    )

    transaction_date = safe_datetime(
        get_value(
            row,
            column_map,
            "transaction_date",
        )
    )

    return NormalizedTransaction(
        source="razorpay",
        transaction_id=payment_id,
        order_id=order_id,
        settlement_id=settlement_id,
        amount=amount,
        gross_amount=amount,
        net_amount=settlement_amount,
        fee=fee,
        currency=currency.upper(),
        transaction_date=transaction_date,
    )


# ============================================================
# BANK
# ============================================================

def normalize_bank_row(
    row: dict[str, Any],
    column_map: dict[str, str],
) -> NormalizedTransaction:

    transaction_id = safe_string(
        get_value(
            row,
            column_map,
            "transaction_id",
        )
    )

    credit = safe_float(
        get_value(
            row,
            column_map,
            "credit",
        )
    )

    debit = safe_float(
        get_value(
            row,
            column_map,
            "debit",
        )
    )

    amount = (
        credit
        if credit is not None
        else debit
    )

    narration = safe_string(
        get_value(
            row,
            column_map,
            "narration",
        )
    )

    transaction_date = safe_datetime(
        get_value(
            row,
            column_map,
            "transaction_date",
        )
    )

    currency = (
        safe_string(
            get_value(
                row,
                column_map,
                "currency",
            )
        )
        or "INR"
    )

    return NormalizedTransaction(
        source="bank",
        transaction_id=transaction_id,
        amount=amount,
        gross_amount=amount,
        currency=currency.upper(),
        transaction_date=transaction_date,
        narration=narration,
    )


# ============================================================
# LEDGER
# ============================================================

def normalize_ledger_row(
    row: dict[str, Any],
    column_map: dict[str, str],
) -> NormalizedTransaction:

    invoice_id = safe_string(
        get_value(
            row,
            column_map,
            "invoice_id",
        )
    )

    order_id = safe_string(
        get_value(
            row,
            column_map,
            "order_id",
        )
    )

    amount = safe_float(
        get_value(
            row,
            column_map,
            "amount",
        )
    )

    debit = safe_float(
        get_value(
            row,
            column_map,
            "debit",
        )
    )

    credit = safe_float(
        get_value(
            row,
            column_map,
            "credit",
        )
    )

    if amount is None:

        amount = (
            credit
            if credit is not None
            else debit
        )

    narration = safe_string(
        get_value(
            row,
            column_map,
            "narration",
        )
    )

    transaction_date = safe_datetime(
        get_value(
            row,
            column_map,
            "transaction_date",
        )
    )

    currency = (
        safe_string(
            get_value(
                row,
                column_map,
                "currency",
            )
        )
        or "INR"
    )

    return NormalizedTransaction(
        source="ledger",
        transaction_id=invoice_id or order_id,
        invoice_id=invoice_id,
        order_id=order_id,
        amount=amount,
        gross_amount=amount,
        currency=currency.upper(),
        transaction_date=transaction_date,
        narration=narration,
    )


# ============================================================
# INVOICE
# ============================================================

def normalize_invoice_row(
    row: dict[str, Any],
    column_map: dict[str, str],
) -> NormalizedTransaction:

    invoice_id = safe_string(
        get_value(
            row,
            column_map,
            "invoice_id",
        )
    )

    order_id = safe_string(
        get_value(
            row,
            column_map,
            "order_id",
        )
    )

    amount = safe_float(
        get_value(
            row,
            column_map,
            "amount",
        )
    )

    gross_amount = safe_float(
        get_value(
            row,
            column_map,
            "gross_amount",
        )
    )

    if gross_amount is None:
        gross_amount = amount

    currency = (
        safe_string(
            get_value(
                row,
                column_map,
                "currency",
            )
        )
        or "INR"
    )

    transaction_date = safe_datetime(
        get_value(
            row,
            column_map,
            "transaction_date",
        )
    )

    narration = safe_string(
        get_value(
            row,
            column_map,
            "narration",
        )
    )

    return NormalizedTransaction(
        source="invoice",
        transaction_id=invoice_id or order_id,
        invoice_id=invoice_id,
        order_id=order_id,
        amount=amount,
        gross_amount=gross_amount,
        currency=currency.upper(),
        transaction_date=transaction_date,
        narration=narration,
    )


# ============================================================
# MAIN NORMALIZER
# ============================================================

def normalize_dataframe(
    dataframe: pd.DataFrame,
    source: str,
    filename: str = "",
) -> list[NormalizedTransaction]:

    if dataframe is None:

        raise NormalizationError(
            "No dataframe was provided."
        )

    if not isinstance(
        dataframe,
        pd.DataFrame,
    ):

        raise NormalizationError(
            "Expected a pandas DataFrame."
        )

    if dataframe.empty:
        return []

    source = str(
        source or ""
    ).strip().lower()

    supported_sources = {
        "razorpay",
        "bank",
        "ledger",
        "invoice",
    }

    if source not in supported_sources:

        raise NormalizationError(
            f"Unsupported source: {source}"
        )

    columns = list(
        dataframe.columns
    )

    column_map = build_column_map(
        columns
    )

    if not column_map:

        raise NormalizationError(
            "No supported columns were found."
        )

    # Convert the dataframe to ordinary Python dictionaries.
    # After this point, normalization does not manipulate Pandas.
    rows = dataframe.to_dict(
        orient="records"
    )

    transactions: list[
        NormalizedTransaction
    ] = []

    for row_number, row in enumerate(
        rows,
        start=1,
    ):

        try:

            if source == "razorpay":

                transaction = (
                    normalize_razorpay_row(
                        row,
                        column_map,
                    )
                )

            elif source == "bank":

                transaction = (
                    normalize_bank_row(
                        row,
                        column_map,
                    )
                )

            elif source == "ledger":

                transaction = (
                    normalize_ledger_row(
                        row,
                        column_map,
                    )
                )

            else:

                transaction = (
                    normalize_invoice_row(
                        row,
                        column_map,
                    )
                )

            # Keep the original row for audit/debugging.
            transaction.raw_data = dict(row)

            transactions.append(
                transaction
            )

        except Exception as exc:

            raise NormalizationError(
                f"Failed to normalize row "
                f"{row_number}: {exc}"
            ) from exc

    return transactions