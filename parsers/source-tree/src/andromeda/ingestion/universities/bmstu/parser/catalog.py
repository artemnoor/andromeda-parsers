from __future__ import annotations

from collections.abc import Sequence

from ..selectors import select_program_codes


def select_catalog_programs(values: Sequence[str] | None = None) -> tuple[str, ...]:
    # ``None`` is the explicit adapter signal for live catalog discovery.
    # A caller that supplies codes still gets the strict selector contract.
    return () if values is None else select_program_codes(tuple(values))
