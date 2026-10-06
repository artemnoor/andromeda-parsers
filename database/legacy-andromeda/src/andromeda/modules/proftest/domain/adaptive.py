"""Contracts for candidate-spread-driven adaptive refinement."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import ProgramId


class AdaptiveStatus(StrEnum):
    READY = "ready"
    SKIPPED = "skipped"


class AdaptiveStopReason(StrEnum):
    TOP_THREE_STABLE = "top_three_stable"
    LOW_RANKING_IMPACT = "low_ranking_impact"
    NO_MEANINGFUL_QUESTION = "no_meaningful_question"
    CONTRADICTION = "contradiction"
    MAX_QUESTIONS = "max_questions"
    SOURCE_GAP = "source_gap"
    INSUFFICIENT_CANDIDATES = "insufficient_candidates"


class AdaptiveDimension(ContractModel):
    code: str = Field(min_length=3, max_length=128)
    label: str = Field(min_length=1, max_length=256)
    kind: Literal["area", "activity"]
    spread: Decimal = Field(strict=True, ge=0, le=1)
    significance: Decimal = Field(strict=True, ge=0, le=1)


class AdaptiveSelection(ContractModel):
    status: AdaptiveStatus
    reason: str | None = Field(default=None, max_length=512)
    candidate_count: int = Field(strict=True, ge=0)
    top_candidate_count: int = Field(strict=True, ge=0)
    dimensions: tuple[AdaptiveDimension, ...] = Field(default=(), max_length=2)
    asked_question_ids: tuple[str, ...] = Field(default=(), max_length=10)
    uncertain_dimensions: tuple[str, ...] = Field(default=(), max_length=12)
    adaptive_count: int = Field(default=0, strict=True, ge=0, le=10)
    stop_reason: AdaptiveStopReason | None = None


class AdaptiveState(ContractModel):
    """Serializable state returned by the multi-step adaptive selector."""

    candidate_ids: tuple[ProgramId, ...] = Field(default=(), max_length=10)
    candidate_count: int = Field(strict=True, ge=0)
    asked_question_ids: tuple[str, ...] = Field(default=(), max_length=10)
    uncertain_dimensions: tuple[str, ...] = Field(default=(), max_length=12)
    ranking_snapshots: tuple[tuple[ProgramId, ...], ...] = Field(default=(), max_length=10)
    ranking_score_snapshots: tuple[tuple[int, ...], ...] = Field(default=(), max_length=10)
    adaptive_count: int = Field(default=0, strict=True, ge=0, le=10)
    stop_reason: AdaptiveStopReason | None = None


__all__ = ["AdaptiveDimension", "AdaptiveSelection", "AdaptiveState", "AdaptiveStatus", "AdaptiveStopReason"]
