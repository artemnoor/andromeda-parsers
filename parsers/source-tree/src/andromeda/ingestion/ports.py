from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from .contracts.normalized import CanonicalSnapshot
from .contracts.raw import RawTracerBundle
from .contracts.source import CapturedSources


class SourceAdapter(Protocol):
    """Adapter contract implemented by each university ingestion module."""

    def capture(self, mode: str = "fixture", fixture_dir: Path | None = None) -> CapturedSources: ...

    def parse(
        self,
        captured: CapturedSources,
        program_codes: Sequence[str] | None = None,
    ) -> tuple[RawTracerBundle, CanonicalSnapshot]: ...
