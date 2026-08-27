"""
Unit tests for LedgerGuard's deterministic reconciliation engine.

These tests intentionally focus on the pure matching logic so they can
run without requiring PostgreSQL, Ollama, or external services.
"""

from dataclasses import dataclass

from app.matching_engine import (
    _within_pct,
    _find_summing_subset,
)


@dataclass
class MockCredit:
    amount: float


# ============================================================
# PERCENTAGE TOLERANCE TESTS
# ============================================================

def test_within_pct_exact_match():
    assert _within_pct(1000, 1000, 0.05) is True


def test_within_pct_inside_tolerance():
    assert _within_pct(1020, 1000, 0.05) is True


def test_within_pct_outside_tolerance():
    assert _within_pct(1100, 1000, 0.05) is False


def test_within_pct_zero_values():
    assert _within_pct(0, 0, 0.05) is True


def test_within_pct_zero_reference():
    assert _within_pct(10, 0, 0.05) is False


# ============================================================
# SPLIT PAYMENT TESTS
# ============================================================

def test_split_payment_two_transactions():
    credits = [
        MockCredit(400),
        MockCredit(600),
        MockCredit(100),
    ]

    result = _find_summing_subset(
        credits,
        target=1000,
        tolerance_pct=0.01,
    )

    assert result is not None
    assert sum(c.amount for c in result) == 1000


def test_split_payment_three_transactions():
    credits = [
        MockCredit(300),
        MockCredit(250),
        MockCredit(450),
        MockCredit(100),
    ]

    result = _find_summing_subset(
        credits,
        target=1000,
        tolerance_pct=0.01,
    )

    assert result is not None
    assert sum(c.amount for c in result) == 1000


def test_split_payment_with_tolerance():
    credits = [
        MockCredit(500),
        MockCredit(499),
        MockCredit(100),
    ]

    result = _find_summing_subset(
        credits,
        target=1000,
        tolerance_pct=0.01,
    )

    assert result is not None


def test_split_payment_not_found():
    credits = [
        MockCredit(100),
        MockCredit(200),
        MockCredit(300),
    ]

    result = _find_summing_subset(
        credits,
        target=1000,
        tolerance_pct=0.01,
    )

    assert result is None


def test_split_payment_does_not_use_more_than_three_records():
    credits = [
        MockCredit(250),
        MockCredit(250),
        MockCredit(250),
        MockCredit(250),
    ]

    result = _find_summing_subset(
        credits,
        target=1000,
        tolerance_pct=0.01,
    )

    # Engine intentionally searches combinations of max 3.
    assert result is None