"""Typed contracts for resumable adaptive proftest sessions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import json
from typing import Annotated, TypeAlias

from pydantic import Field, StringConstraints, model_validator

from andromeda.shared.contracts.base import ContractModel

from .adaptive import AdaptiveSelection, AdaptiveState
from .entities import Answer, AnswerSet, AnswerStatus, Question
from .results import ProftestResults

SessionId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^proftest-session:[0-9a-f]{32}$")]
AnalyticsEventId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^proftest-event:[0-9a-f]{32}$")]


class SessionStatus(StrEnum):
    DRAFT = "draft"
    COMPLETED = "completed"
    EXPIRED = "expired"
    ABANDONED = "abandoned"


class AnalyticsEventType(StrEnum):
    TEST_STARTED = "test_started"
    STAGE_VIEWED = "stage_viewed"
    QUESTION_VIEWED = "question_viewed"
    ANSWER_SELECTED = "answer_selected"
    ANSWER_CHANGED = "answer_changed"
    QUESTION_SKIPPED = "question_skipped"
    ADAPTIVE_STOPPED = "adaptive_stopped"
    TEST_COMPLETED = "test_completed"
    RESULT_PROGRAM_OPENED = "result_program_opened"
    COMPARE_STARTED = "compare_started"


class SessionProgress(ContractModel):
    stage: str = Field(min_length=1, max_length=64)
    stage_index: int = Field(strict=True, ge=0, le=20)
    stage_count: int = Field(strict=True, ge=1, le=20)
    answer_count: int = Field(strict=True, ge=0, le=38)
    min_remaining: int = Field(strict=True, ge=0, le=38)
    max_remaining: int = Field(strict=True, ge=0, le=38)

    @model_validator(mode="after")
    def validate_range(self) -> "SessionProgress":
        if self.min_remaining > self.max_remaining:
            raise ValueError("progress minimum cannot exceed maximum")
        return self


class SessionAnswer(ContractModel):
    question_id: str = Field(min_length=1, max_length=256)
    option_ids: tuple[str, ...] = Field(default=(), max_length=6)
    intensity: Decimal | None = Field(default=None, strict=True, ge=0, le=1, max_digits=5, decimal_places=4)
    status: AnswerStatus = AnswerStatus.ANSWERED
    dimension: str | None = Field(default=None, min_length=3, max_length=128)

    def to_answer(self) -> Answer:
        return Answer(
            question_id=self.question_id,
            option_ids=self.option_ids,
            intensity=self.intensity,
            status=self.status,
        )


class PreliminaryTopic(ContractModel):
    code: str = Field(min_length=3, max_length=128)
    label: str = Field(min_length=1, max_length=256)


class PreliminaryProfile(ContractModel):
    topics: tuple[PreliminaryTopic, ...] = Field(default=(), max_length=3)


class ProftestAnswerSession(ContractModel):
    session_id: SessionId
    question_set_version: str = Field(min_length=1, max_length=128)
    status: SessionStatus = SessionStatus.DRAFT
    answer_set: AnswerSet = AnswerSet()
    adaptive_questions: tuple[Question, ...] = Field(default=(), max_length=10)
    adaptive_state: AdaptiveState | None = None
    cursor: int = Field(strict=True, ge=0, le=38)
    interaction_count: int = Field(strict=True, ge=0, le=38)
    current_question_id: str | None = Field(default=None, min_length=1, max_length=256)
    stale_question_ids: tuple[str, ...] = Field(default=(), max_length=10)
    revision: int = Field(strict=True, ge=1)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> "ProftestAnswerSession":
        if self.interaction_count < self.cursor:
            raise ValueError("interaction_count cannot be lower than cursor")
        if self.updated_at > self.expires_at:
            raise ValueError("session must expire after it was updated")
        if len(self.stale_question_ids) != len(set(self.stale_question_ids)):
            raise ValueError("stale question IDs must be unique")
        question_ids = tuple(question.id for question in self.adaptive_questions)
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("adaptive question snapshots must be unique")
        if any(not question.adaptive for question in self.adaptive_questions):
            raise ValueError("session snapshots must contain adaptive questions only")
        return self


class ProftestSessionView(ContractModel):
    session: ProftestAnswerSession
    current_question: Question | None = None
    progress: SessionProgress
    adaptive: AdaptiveSelection | None = None
    preliminary: PreliminaryProfile | None = None
    results: ProftestResults | None = None
    # The profile belongs to the existing profile persistence boundary.  This
    # optional envelope field only tells clients which persisted projection
    # was produced by completion; it is not a copy of profile preferences.
    profile_revision: int | None = Field(default=None, strict=True, ge=1)


class ProftestAnalyticsEvent(ContractModel):
    event_id: AnalyticsEventId
    session_id: SessionId | None = None
    question_set_version: str = Field(min_length=1, max_length=128)
    event_type: AnalyticsEventType
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=16)
    occurred_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_payload(self) -> "ProftestAnalyticsEvent":
        allowed_keys = {"stage", "questionId", "component", "device", "durationMs", "uncertainty", "adaptiveCount", "changed", "top3Changed", "reason"}
        if set(self.payload) - allowed_keys:
            raise ValueError("analytics payload contains unsupported fields")
        if len(json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))) > 2048:
            raise ValueError("analytics payload is too large")
        device = self.payload.get("device")
        if device is not None and device not in {"mobile", "desktop", "unknown"}:
            raise ValueError("analytics device must be coarse")
        if any(isinstance(value, str) and len(value) > 128 for value in self.payload.values()):
            raise ValueError("analytics payload text is too long")
        return self


__all__ = [
    "AnalyticsEventId",
    "AnalyticsEventType",
    "ProftestAnalyticsEvent",
    "ProftestAnswerSession",
    "PreliminaryProfile",
    "PreliminaryTopic",
    "SessionId",
    "SessionProgress",
    "SessionAnswer",
    "SessionStatus",
]
