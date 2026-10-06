"""Pure profile aggregation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TypeVar

from .values import ZERO, quantize_ratio


KeyT = TypeVar("KeyT", bound=str)


def normalize_weights(values: Mapping[KeyT, Decimal]) -> dict[KeyT, Decimal]:
    total = sum(values.values(), ZERO)
    if total <= ZERO:
        return {}
    ordered = sorted(((key, value) for key, value in values.items() if value > ZERO), key=lambda entry: str(entry[0]))
    normalized = {key: quantize_ratio(value / total) for key, value in ordered}
    if normalized:
        last_key = ordered[-1][0]
        normalized[last_key] += Decimal("1") - sum(normalized.values(), ZERO)
    return normalized


__all__ = ["normalize_weights"]
