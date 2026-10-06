"""Bounded value objects for the decision domain.

The decision module deliberately models statuses and roles separately.  It
does not introduce a synthetic score that would hide the difference between
admission risk, preference fit and the user's own choice.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, TypeAlias

from pydantic import StringConstraints


DecisionId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^decision:[0-9a-f]{32}$")]


class ShortlistRole(StrEnum):
    """Explicit role assigned by the user to an active shortlist entry."""

    PRIMARY = "primary"
    ALTERNATIVE = "alternative"


class ShortlistEntryState(StrEnum):
    """Lifecycle of a retained shortlist entry."""

    ACTIVE = "active"
    REMOVED = "removed"


class DecisionSourceKind(StrEnum):
    """How a program entered the user-owned choice state."""

    USER = "user"
    SUGGESTION_ACCEPTED = "suggestion_accepted"


class DecisionStatus(StrEnum):
    """Coarse state of explicit decision data, never a ranking score."""

    EMPTY = "empty"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    FINALIZED = "finalized"


class AdmissionGate(StrEnum):
    """Decision-level admission state used when composing candidate evidence."""

    NOT_EVALUATED = "not_evaluated"
    REALISTIC = "realistic"
    BORDERLINE = "borderline"
    UNLIKELY = "unlikely"
    INSUFFICIENT_DATA = "insufficient_data"


__all__ = [
    "AdmissionGate",
    "DecisionId",
    "DecisionSourceKind",
    "DecisionStatus",
    "ShortlistEntryState",
    "ShortlistRole",
]
