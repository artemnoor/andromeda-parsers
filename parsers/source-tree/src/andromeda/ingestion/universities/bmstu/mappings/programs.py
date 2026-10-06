from __future__ import annotations

from ..selectors import select_program_codes


def normalize_program_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    return select_program_codes(values)
