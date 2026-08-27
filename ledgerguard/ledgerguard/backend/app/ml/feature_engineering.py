from __future__ import annotations

from typing import Any


def amount_difference(
    expected: float | None,
    actual: float | None,
) -> float:

    if expected is None or actual is None:
        return 999999.0

    return round(
        abs(float(expected) - float(actual)),
        2,
    )


def amount_difference_ratio(
    expected: float | None,
    actual: float | None,
) -> float:

    if expected is None or actual is None:
        return 1.0

    expected = float(expected)
    actual = float(actual)

    if expected == 0:
        return 1.0

    return round(
        abs(expected - actual) / abs(expected),
        6,
    )


def string_match(
    first: str | None,
    second: str | None,
) -> int:

    if not first or not second:
        return 0

    return int(
        str(first).strip().lower()
        == str(second).strip().lower()
    )


def contains_match(
    first: str | None,
    second: str | None,
) -> int:

    if not first or not second:
        return 0

    first = str(first).lower()
    second = str(second).lower()

    return int(
        first in second
        or second in first
    )


def build_match_features(
    invoice: Any,
    gateway: Any,
    bank: Any | None = None,
) -> dict[str, float]:

    invoice_amount = getattr(
        invoice,
        "amount",
        None,
    )

    gateway_gross = getattr(
        gateway,
        "gross_amount",
        None,
    )

    gateway_net = getattr(
        gateway,
        "net_amount",
        None,
    )

    gateway_fee = getattr(
        gateway,
        "mdr_fee",
        None,
    )

    bank_amount = (
        getattr(
            bank,
            "amount",
            None,
        )
        if bank is not None
        else None
    )

    invoice_order = getattr(
        invoice,
        "order_id",
        None,
    )

    gateway_order = getattr(
        gateway,
        "order_id",
        None,
    )

    bank_order = (
        getattr(
            bank,
            "order_id",
            None,
        )
        if bank is not None
        else None
    )

    features = {

        # Invoice ↔ Gateway
        "invoice_gateway_amount_diff":
            amount_difference(
                invoice_amount,
                gateway_gross,
            ),

        "invoice_gateway_amount_ratio":
            amount_difference_ratio(
                invoice_amount,
                gateway_gross,
            ),

        "invoice_gateway_order_exact":
            float(
                string_match(
                    invoice_order,
                    gateway_order,
                )
            ),

        "invoice_gateway_order_contains":
            float(
                contains_match(
                    invoice_order,
                    gateway_order,
                )
            ),

        # Gateway fee behaviour
        "gateway_fee":
            float(gateway_fee or 0.0),

        "gateway_net_gross_diff":
            amount_difference(
                gateway_gross,
                gateway_net,
            ),

        "gateway_fee_ratio":
            (
                float(gateway_fee or 0.0)
                / float(gateway_gross)
                if gateway_gross
                else 0.0
            ),

        # Gateway ↔ Bank
        "gateway_bank_amount_diff":
            amount_difference(
                gateway_net,
                bank_amount,
            ),

        "gateway_bank_amount_ratio":
            amount_difference_ratio(
                gateway_net,
                bank_amount,
            ),

        "gateway_bank_order_exact":
            float(
                string_match(
                    gateway_order,
                    bank_order,
                )
            ),

        "bank_available":
            float(bank is not None),
    }

    return features


def feature_vector(
    features: dict[str, float],
) -> list[float]:

    return [
        float(value)
        for value in features.values()
    ]