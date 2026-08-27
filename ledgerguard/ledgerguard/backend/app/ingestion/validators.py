from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ingestion.normalizer import NormalizedTransaction


@dataclass
class ValidationIssue:
    row_number: int
    field: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
        }


def validate_transaction(
    transaction: NormalizedTransaction,
    row_number: int,
) -> list[ValidationIssue]:
    """
    Validate one normalized transaction.

    Validation does not attempt to determine whether the transaction
    reconciles. It only checks whether the data is usable.
    """

    issues: list[ValidationIssue] = []

    if not transaction.source:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="source",
                message="Source is missing.",
            )
        )

    if not transaction.transaction_id and not (
        transaction.invoice_id
        or transaction.order_id
        or transaction.settlement_id
    ):
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="transaction_id",
                message=(
                    "No transaction, invoice, order, or settlement "
                    "identifier was found."
                ),
                severity="warning",
            )
        )

    if (
        transaction.amount is None
        and transaction.gross_amount is None
        and transaction.net_amount is None
    ):
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="amount",
                message="No monetary amount was found.",
            )
        )

    if transaction.amount is not None and transaction.amount < 0:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="amount",
                message="Amount is negative.",
                severity="warning",
            )
        )

    if transaction.gross_amount is not None and transaction.gross_amount < 0:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="gross_amount",
                message="Gross amount is negative.",
                severity="warning",
            )
        )

    if transaction.net_amount is not None and transaction.net_amount < 0:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="net_amount",
                message="Net amount is negative.",
                severity="warning",
            )
        )

    if transaction.fee is not None and transaction.fee < 0:
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="fee",
                message="Fee is negative.",
                severity="warning",
            )
        )

    if transaction.currency:
        if len(transaction.currency) != 3:
            issues.append(
                ValidationIssue(
                    row_number=row_number,
                    field="currency",
                    message=(
                        f"Currency '{transaction.currency}' does not "
                        "look like a 3-letter ISO currency code."
                    ),
                    severity="warning",
                )
            )

    return issues


def validate_transactions(
    transactions: list[NormalizedTransaction],
) -> dict[str, Any]:
    """
    Validate all normalized transactions and return a structured report.
    """

    issues: list[ValidationIssue] = []

    valid_rows = 0
    invalid_rows = 0

    for index, transaction in enumerate(transactions, start=1):
        row_issues = validate_transaction(
            transaction=transaction,
            row_number=index,
        )

        issues.extend(row_issues)

        has_error = any(issue.severity == "error" for issue in row_issues)

        if has_error:
            invalid_rows += 1
        else:
            valid_rows += 1

    return {
        "total_rows": len(transactions),
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "warning_count": sum(
            issue.severity == "warning" for issue in issues
        ),
        "error_count": sum(
            issue.severity == "error" for issue in issues
        ),
        "issues": [issue.to_dict() for issue in issues],
    }