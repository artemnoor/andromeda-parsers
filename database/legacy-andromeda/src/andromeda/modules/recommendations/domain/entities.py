"""Internal typed entities for recommendation orchestration."""

from __future__ import annotations

from typing import NamedTuple

from andromeda.modules.proftest.contracts.public import MatchScore, ProgramFingerprint


class RankedFingerprint(NamedTuple):
    """A fingerprint and its score kept together inside the application layer."""

    fingerprint: ProgramFingerprint
    score: MatchScore


__all__ = ["RankedFingerprint"]
