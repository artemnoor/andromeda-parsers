"""Registry for university ingestion adapters.

The application depends on the adapter contract, not on university-specific
conditionals scattered through runners and API composition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .ports import SourceAdapter
from .universities.bmstu import BmstuUniversityAdapter, DEFAULT_FIXTURE_DIR as BMSTU_FIXTURE_DIR
from .universities.hse import HseUniversityAdapter
from .universities.hse.capture import DEFAULT_FIXTURE_DIR as HSE_FIXTURE_DIR


@dataclass(frozen=True, slots=True)
class UniversityAdapterSpec:
    slug: str
    factory: Callable[[], SourceAdapter]
    default_fixture_dir: Path


_SPECS = {
    "bmstu": UniversityAdapterSpec("bmstu", BmstuUniversityAdapter, BMSTU_FIXTURE_DIR),
    "hse": UniversityAdapterSpec("hse", HseUniversityAdapter, HSE_FIXTURE_DIR),
}


def supported_universities() -> tuple[str, ...]:
    return tuple(_SPECS)


def adapter_spec(university: str) -> UniversityAdapterSpec:
    try:
        return _SPECS[university.casefold()]
    except KeyError as exc:
        raise ValueError(f"unsupported university {university!r}; choose one of {', '.join(_SPECS)}") from exc


def create_adapter(university: str) -> SourceAdapter:
    return adapter_spec(university).factory()


__all__ = ["UniversityAdapterSpec", "adapter_spec", "create_adapter", "supported_universities"]
