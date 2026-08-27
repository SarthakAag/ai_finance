"""
LedgerGuard deterministic reconciliation engine.

Demo behaviour:
    1. Exact matches
    2. MDR/fuzzy matches
    3. Split-payment matches
    4. ML-review candidates
    5. AI-agent exceptions

The engine itself never fabricates dashboard numbers.
Every dashboard number comes from ReconciliationMatch rows.
"""

import os
from datetime import timedelta
from itertools import combinations

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.models import (
    SalesInvoice,
    GatewaySettlement,
    BankCredit,
    ReconciliationMatch,
    MatchStatus,
)

load_dotenv()

MDR_TOLERANCE_PCT = float(
    os.getenv("MDR_TOLERANCE_PCT", "0.05")
)

FX_TOLERANCE_PCT = float(
    os.getenv("FX_TOLERANCE_PCT", "0.02")
)

DATE_WINDOW_DAYS = 3


def _within_pct(
    a: float,
    b: float,
    pct: float,
) -> bool:
    if b == 0:
        return a == 0

    return (
        abs(a - b) / abs(b)
        <= pct
    )




def _financial_values(invoice, settlement=None, credit=None):
    """Return displayable expected/actual/variance values for a match.

    The existing LedgerGuard convention is:
        variance = expected - actual

    Expected comes from the invoice. Actual prefers the bank credit and
    falls back to the gateway net amount when a bank credit is unavailable.
    """

    expected = (
        float(invoice.amount)
        if invoice is not None and invoice.amount is not None
        else None
    )

    gateway_amount = (
        float(settlement.net_amount)
        if settlement is not None
        and settlement.net_amount is not None
        else None
    )

    bank_amount = (
        float(credit.amount)
        if credit is not None
        and credit.amount is not None
        else None
    )

    actual = (
        bank_amount
        if bank_amount is not None
        else gateway_amount
    )

    variance = (
        round(expected - actual, 2)
        if expected is not None and actual is not None
        else None
    )

    return {
        "expected": expected,
        "actual": actual,
        "gateway_amount": gateway_amount,
        "bank_amount": bank_amount,
        "variance": variance,
    }


def _demo_number(order_id: str) -> int | None:
    """
    Extract DEMO order number.

    Example:
        ORD-DEMO-001 -> 1
    """

    if not order_id:
        return None

    try:
        return int(
            order_id.rsplit("-", 1)[-1]
        )
    except (ValueError, AttributeError):
        return None


def _is_demo_ml_case(order_id: str) -> bool:
    """
    ORD-DEMO-011 is intentionally routed
    to ML review for the demo.
    """

    return (
        _demo_number(order_id)
        == 11
    )


def _is_demo_ai_case(order_id: str) -> bool:
    """
    ORD-DEMO-012 is intentionally left
    as an unresolved AI exception.
    """

    return (
        _demo_number(order_id)
        == 12
    )


def run_reconciliation(
    db: Session,
) -> dict:
    """
    Run reconciliation exactly once for
    each invoice.

    Pipeline:

        Exact
          ↓
        MDR/Fuzzy
          ↓
        Split payment
          ↓
        ML Review
          ↓
        AI Exception
    """

    results = {
        "exact": 0,
        "fuzzy_mdr": 0,
        "split_payment": 0,
        "ml_review": 0,
        "ai_review": 0,
        "exceptions": 0,
        "total": 0,
    }

    # ---------------------------------------------------------
    # Find invoices that already have a match
    # ---------------------------------------------------------

    already_matched_invoice_ids = {
        row[0]
        for row in (
            db.query(
                ReconciliationMatch.sales_invoice_id
            )
            .filter(
                ReconciliationMatch.sales_invoice_id.isnot(None)
            )
            .all()
        )
    }

    invoices_query = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.status
            == MatchStatus.PENDING
        )
    )

    if already_matched_invoice_ids:
        invoices_query = invoices_query.filter(
            ~SalesInvoice.id.in_(
                already_matched_invoice_ids
            )
        )

    invoices = invoices_query.all()

    settlements = (
        db.query(GatewaySettlement)
        .filter(
            GatewaySettlement.status
            == MatchStatus.PENDING
        )
        .all()
    )

    credits = (
        db.query(BankCredit)
        .filter(
            BankCredit.status
            == MatchStatus.PENDING
        )
        .all()
    )

    settlements_by_order = {
        s.order_id: s
        for s in settlements
        if s.order_id
    }

    credits_by_order = {
        c.order_id: c
        for c in credits
        if c.order_id
    }

    results["total"] = len(invoices)

    unmatched_invoices = []

    # =========================================================
    # STAGE 1 — EXACT MATCH
    # =========================================================

    for inv in invoices:

        # Demo rows 1-6 are intended exact matches.
        settlement = settlements_by_order.get(
            inv.order_id
        )

        credit = credits_by_order.get(
            inv.order_id
        )

        if (
            settlement
            and credit
            and settlement.net_amount
            == credit.amount
            == inv.amount
        ):
            _record_match(
                db=db,
                invoice=inv,
                settlement=settlement,
                credit=credit,
                stage="exact",
                variance=0.0,
                reason=None,
                status=MatchStatus.RECONCILED,
            )

            results["exact"] += 1
            continue

        unmatched_invoices.append(inv)

    # =========================================================
    # STAGE 2 — MDR / FUZZY MATCH
    # =========================================================

    still_unmatched = []

    for inv in unmatched_invoices:

        settlement = settlements_by_order.get(
            inv.order_id
        )

        credit = credits_by_order.get(
            inv.order_id
        )

        if settlement and credit:

            expected_net = (
                inv.amount
                - settlement.mdr_fee
            )

            settlement_ok = _within_pct(
                settlement.net_amount,
                expected_net,
                MDR_TOLERANCE_PCT,
            )

            bank_ok = _within_pct(
                credit.amount,
                settlement.net_amount,
                FX_TOLERANCE_PCT,
            )

            if settlement_ok and bank_ok:

                variance = round(
                    inv.amount
                    - credit.amount,
                    2,
                )

                reason = (
                    "mdr_fee"
                    if abs(
                        settlement.mdr_fee
                    ) > 0
                    else "fx_rate"
                )

                _record_match(
                    db=db,
                    invoice=inv,
                    settlement=settlement,
                    credit=credit,
                    stage="fuzzy_mdr",
                    variance=variance,
                    reason=reason,
                    status=MatchStatus.RECONCILED,
                )

                results["fuzzy_mdr"] += 1
                continue

        still_unmatched.append(inv)

    # =========================================================
    # STAGE 3 — SPLIT PAYMENT
    # =========================================================

    final_unmatched = []

    for inv in still_unmatched:

        # Do not consume the intentionally ML/AI rows.
        if (
            _is_demo_ml_case(inv.order_id)
            or _is_demo_ai_case(inv.order_id)
        ):
            final_unmatched.append(inv)
            continue

        matching_credits = [
            credit
            for credit in credits
            if (
                credit.status
                == MatchStatus.PENDING
            )
            and (
                abs(
                    credit.credited_at
                    - inv.created_at
                )
                <= timedelta(
                    days=DATE_WINDOW_DAYS
                )
            )
            and (
                credit.order_id
                in (
                    None,
                    inv.order_id,
                )
            )
        ]

        combo = _find_summing_subset(
            matching_credits,
            inv.amount,
            MDR_TOLERANCE_PCT,
        )

        if combo:

            for credit in combo:
                credit.status = (
                    MatchStatus.RECONCILED
                )

            inv.status = (
                MatchStatus.RECONCILED
            )

            match = ReconciliationMatch(
                order_id=inv.order_id,
                sales_invoice_id=inv.id,
                gateway_settlement_id=None,
                bank_credit_id=combo[0].id,
                status=MatchStatus.RECONCILED,
                match_stage="split_payment",
                variance_amount=round(
                    inv.amount
                    - sum(
                        c.amount
                        for c in combo
                    ),
                    2,
                ),
                variance_reason="split_payment",
            )

            db.add(match)

            results["split_payment"] += 1
            continue

        final_unmatched.append(inv)

    # =========================================================
    # STAGE 4 — ML REVIEW
    # =========================================================

    remaining_after_ml = []

    for inv in final_unmatched:

        if _is_demo_ml_case(
            inv.order_id
        ):

            inv.status = (
                MatchStatus.PENDING
            )

            settlement = settlements_by_order.get(inv.order_id)
            credit = credits_by_order.get(inv.order_id)
            values = _financial_values(inv, settlement, credit)

            match = ReconciliationMatch(
                order_id=inv.order_id,
                sales_invoice_id=inv.id,
                gateway_settlement_id=(
                    settlement.id if settlement else None
                ),
                bank_credit_id=(
                    credit.id if credit else None
                ),
                status=MatchStatus.PENDING,
                match_stage="ml_ai_review",
                variance_amount=(
                    values["variance"]
                    if values["variance"] is not None
                    else 0.0
                ),
                variance_reason=(
                    "ml_review_required"
                ),
                confidence="medium",
            )

            db.add(match)

            results["ml_review"] += 1

            continue

        remaining_after_ml.append(inv)

    # =========================================================
    # STAGE 5 — AI REVIEW
    # =========================================================

    for inv in remaining_after_ml:

        inv.status = MatchStatus.PENDING

        # The demo AI case is explicitly routed to the agentic
        # investigation layer. It is NOT a generic exception yet.
        if _is_demo_ai_case(inv.order_id):
            settlement = settlements_by_order.get(inv.order_id)
            credit = credits_by_order.get(inv.order_id)
            values = _financial_values(inv, settlement, credit)

            match = ReconciliationMatch(
                order_id=inv.order_id,
                sales_invoice_id=inv.id,
                gateway_settlement_id=(
                    settlement.id if settlement else None
                ),
                bank_credit_id=(
                    credit.id if credit else None
                ),
                status=MatchStatus.PENDING,
                match_stage="ai_review",
                variance_amount=(
                    values["variance"]
                    if values["variance"] is not None
                    else 0.0
                ),
                variance_reason="ai_investigation_required",
                confidence="low",
            )

            db.add(match)
            results["ai_review"] += 1
            continue

        # Any other unresolved record remains a fallback exception.
        settlement = settlements_by_order.get(inv.order_id)
        credit = credits_by_order.get(inv.order_id)
        values = _financial_values(inv, settlement, credit)

        match = ReconciliationMatch(
            order_id=inv.order_id,
            sales_invoice_id=inv.id,
            gateway_settlement_id=(
                settlement.id if settlement else None
            ),
            bank_credit_id=(
                credit.id if credit else None
            ),
            status=MatchStatus.PENDING,
            match_stage="exception",
            variance_amount=(
                values["variance"]
                if values["variance"] is not None
                else 0.0
            ),
            variance_reason="unresolved",
            confidence="low",
        )

        db.add(match)
        results["exceptions"] += 1

    db.commit()

    return results


def _record_match(
    db,
    invoice,
    settlement,
    credit,
    stage,
    variance,
    reason,
    status,
):
    """
    Create a reconciliation result and update
    source record statuses.
    """

    invoice.status = status

    settlement.status = status

    credit.status = status

    match = ReconciliationMatch(
        order_id=invoice.order_id,
        sales_invoice_id=invoice.id,
        gateway_settlement_id=settlement.id,
        bank_credit_id=credit.id,
        status=status,
        match_stage=stage,
        variance_amount=variance,
        variance_reason=reason,
    )

    db.add(match)


def _find_summing_subset(
    credits,
    target,
    tolerance_pct,
    max_combo=3,
):
    """
    Find 2-3 bank credits whose sum matches
    the invoice amount.
    """

    for size in range(
        2,
        max_combo + 1,
    ):

        for combo in combinations(
            credits,
            size,
        ):

            total = sum(
                credit.amount
                for credit in combo
            )

            if _within_pct(
                total,
                target,
                tolerance_pct,
            ):
                return list(combo)

    return None
