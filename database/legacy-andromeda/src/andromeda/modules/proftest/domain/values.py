"""Shared decimal values for deterministic proftest calculations."""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
ONE = Decimal("1")


def quantize_ratio(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def clamp(value: Decimal, lower: Decimal = ZERO, upper: Decimal = ONE) -> Decimal:
    return max(lower, min(upper, value))

__all__ = ["ONE", "ZERO", "clamp", "quantize_ratio"]
