from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import IngestRunId, ShortText, SourceHash


class IngestionRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionRunSummary(ContractModel):
    id: IngestRunId
    status: IngestionRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    source_count: int = Field(strict=True, ge=0)
    program_count: int = Field(strict=True, ge=0)
    curriculum_item_count: int = Field(strict=True, ge=0)
    event_count: int = Field(strict=True, ge=0)
    campus_point_count: int = Field(strict=True, ge=0)
    inserted_count: int = Field(strict=True, ge=0)
    updated_count: int = Field(strict=True, ge=0)
    unchanged_count: int = Field(strict=True, ge=0)
    removed_count: int = Field(strict=True, ge=0)
    error_code: str | None = Field(default=None, min_length=1, max_length=64)
    error_message: str | None = Field(default=None, min_length=1, max_length=512)
    university_id: str | None = None
    duration_ms: int | None = Field(default=None, strict=True, ge=0)
    source_gap_count: int = Field(default=0, strict=True, ge=0)
    critical_gap_count: int = Field(default=0, strict=True, ge=0)
    drift_status: str = Field(default="not_checked", pattern=r"^(not_checked|passed|rejected)$")
    quality_status: str = Field(default="not_checked", pattern=r"^(not_checked|passed|degraded|rejected)$")
    previous_good_run_id: IngestRunId | None = None
    source_profile: str = Field(default="legacy", min_length=1, max_length=128)
    source_revision: str = Field(default="legacy", min_length=1, max_length=64)
    configuration_version: str = Field(default="legacy", min_length=1, max_length=64)
    retry_of_run_id: IngestRunId | None = None
    projection_target: str = Field(default="canonical", min_length=1, max_length=64)
    heartbeat_at: datetime | None = None
    projection_status: str = Field(
        default="not_started", pattern=r"^(not_started|running|committed|reconciled|failed)$"
    )
    recovery_reason: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "IngestionRunSummary":
        if self.status is IngestionRunStatus.RUNNING and self.finished_at is not None:
            raise ValueError("running ingestion run cannot have finished_at")
        if self.status is not IngestionRunStatus.RUNNING and self.finished_at is None:
            raise ValueError("terminal ingestion run must have finished_at")
        if self.status is IngestionRunStatus.FAILED and self.error_code is None:
            raise ValueError("failed ingestion run must have error_code")
        if self.status is not IngestionRunStatus.FAILED and self.error_code is not None:
            raise ValueError("only failed ingestion run may have error_code")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("ingestion run started_at must be timezone-aware")
        return self


class IngestionRunDetail(IngestionRunSummary):
    source_hashes: tuple[SourceHash, ...] = ()
    source_kinds: tuple[ShortText, ...] = ()


__all__ = ["IngestionRunDetail", "IngestionRunStatus", "IngestionRunSummary"]
