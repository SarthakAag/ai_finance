from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MatchResult:
    matched: bool
    stage: str
    confidence: float
    variance_amount: float
    variance_reason: str | None = None
    explanation: str = ""


def compare_amounts(
    expected: float | None,
    actual: float | None,
    tolerance: float = 1.0,
) -> tuple[bool, float]:
    if expected is None or actual is None:
        return False, 0.0

    variance = round(actual - expected, 2)

    return abs(variance) <= tolerance, variance


def exact_match(
    expected_amount: float | None,
    actual_amount: float | None,
) -> MatchResult:

    matched, variance = compare_amounts(
        expected_amount,
        actual_amount,
        tolerance=0.01,
    )

    if matched:
        return MatchResult(
            matched=True,
            stage="exact",
            confidence=1.0,
            variance_amount=variance,
            explanation="Expected and actual amounts match exactly.",
        )

    return MatchResult(
        matched=False,
        stage="exact",
        confidence=0.0,
        variance_amount=variance,
        explanation="Amounts do not match exactly.",
    )


def mdr_match(
    gross_amount: float | None,
    fee: float | None,
    net_amount: float | None,
    tolerance: float = 1.0,
) -> MatchResult:

    if gross_amount is None or net_amount is None:
        return MatchResult(
            matched=False,
            stage="fuzzy_mdr",
            confidence=0.0,
            variance_amount=0.0,
            explanation="Gross or net amount is missing.",
        )

    fee = fee or 0.0

    expected_net = round(gross_amount - fee, 2)

    matched, variance = compare_amounts(
        expected_net,
        net_amount,
        tolerance=tolerance,
    )

    if matched:
        return MatchResult(
            matched=True,
            stage="fuzzy_mdr",
            confidence=0.98,
            variance_amount=variance,
            variance_reason="mdr_fee",
            explanation=(
                f"Net amount matches gross amount minus fee. "
                f"Expected={expected_net}, actual={net_amount}."
            ),
        )

    return MatchResult(
        matched=False,
        stage="fuzzy_mdr",
        confidence=0.0,
        variance_amount=variance,
        variance_reason="amount_difference",
        explanation=(
            f"Expected net={expected_net}, actual net={net_amount}."
        ),
    )