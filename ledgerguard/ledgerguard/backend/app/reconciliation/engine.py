from __future__ import annotations

from typing import Any

from app.models import (
    BankCredit,
    GatewaySettlement,
    SalesInvoice,
)
from app.reconciliation.rules import (
    MatchResult,
    exact_match,
    mdr_match,
)


class ReconciliationEngine:

    def reconcile_invoice_gateway(
        self,
        invoice: SalesInvoice,
        gateway: GatewaySettlement,
    ) -> MatchResult:

        # Strongest signal: order ID
        if (
            invoice.order_id
            and gateway.order_id
            and invoice.order_id == gateway.order_id
        ):
            # First check exact amount.
            result = exact_match(
                invoice.amount,
                gateway.gross_amount,
            )

            if result.matched:
                result.explanation = (
                    f"Order ID {invoice.order_id} matched and "
                    "gross amount is exact."
                )
                return result

            # Then check whether difference is explainable by fee.
            mdr_result = mdr_match(
                gateway.gross_amount,
                gateway.mdr_fee,
                gateway.net_amount,
            )

            if mdr_result.matched:
                mdr_result.explanation = (
                    f"Order ID {invoice.order_id} matched. "
                    + mdr_result.explanation
                )
                return mdr_result

        return MatchResult(
            matched=False,
            stage="unmatched",
            confidence=0.0,
            variance_amount=round(
                (gateway.gross_amount or 0)
                - (invoice.amount or 0),
                2,
            ),
            variance_reason="no_matching_rule",
            explanation="No deterministic reconciliation rule matched.",
        )

    def reconcile_gateway_bank(
        self,
        gateway: GatewaySettlement,
        bank: BankCredit,
    ) -> MatchResult:

        # Order ID is the strongest available identifier.
        if (
            gateway.order_id
            and bank.order_id
            and gateway.order_id == bank.order_id
        ):
            result = exact_match(
                gateway.net_amount,
                bank.amount,
            )

            if result.matched:
                result.explanation = (
                    f"Order ID {gateway.order_id} matched and "
                    "settlement amount equals bank credit."
                )
                return result

        # Bank feeds frequently don't contain order IDs.
        # In that case amount can still provide a candidate.
        result = exact_match(
            gateway.net_amount,
            bank.amount,
        )

        if result.matched:
            result.confidence = 0.85
            result.explanation = (
                "Bank credit amount matches gateway settlement "
                "amount, but order ID was unavailable."
            )
            return result

        return MatchResult(
            matched=False,
            stage="unmatched",
            confidence=0.0,
            variance_amount=round(
                (bank.amount or 0)
                - (gateway.net_amount or 0),
                2,
            ),
            variance_reason="bank_amount_difference",
            explanation="Gateway settlement could not be matched to bank credit.",
        )