"""Deterministic Admission Fit scoring policy."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


MINIMUM_WEIGHT = Decimal("0.50")
PASSING_WEIGHT = Decimal("0.35")
COMPLETENESS_WEIGHT = Decimal("0.15")
PASSING_BORDERLINE_RATIO = Decimal("0.85")
REALISTIC_SCORE = 80
BORDERLINE_SCORE = 55


def clamp_ratio(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(Decimal("1"), value))


def percentage(value: Decimal) -> Decimal:
    return (clamp_ratio(value) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rounded_score(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


__all__ = [
    "BORDERLINE_SCORE",
    "COMPLETENESS_WEIGHT",
    "MINIMUM_WEIGHT",
    "PASSING_BORDERLINE_RATIO",
    "PASSING_WEIGHT",
    "REALISTIC_SCORE",
    "clamp_ratio",
    "percentage",
    "rounded_score",
]
