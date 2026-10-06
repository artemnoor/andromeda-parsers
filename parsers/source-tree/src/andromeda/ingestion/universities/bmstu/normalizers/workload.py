from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_credits(value: str | int | float | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("credits must be numeric") from exc
