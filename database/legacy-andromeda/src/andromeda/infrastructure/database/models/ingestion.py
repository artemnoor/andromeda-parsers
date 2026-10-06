from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class IngestRunModel(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    program_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    curriculum_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    campus_point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    removed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source_hashes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    source_kinds_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    university_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="university:legacy", server_default="university:legacy"
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    critical_gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    drift_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_checked", server_default="not_checked")
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_checked", server_default="not_checked")
    quality_metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    previous_good_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    program_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    source_profile: Mapped[str] = mapped_column(String(128), nullable=False, default="legacy", server_default="legacy")
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False, default="legacy", server_default="legacy")
    configuration_version: Mapped[str] = mapped_column(String(64), nullable=False, default="legacy", server_default="legacy")
    retry_of_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    projection_target: Mapped[str] = mapped_column(String(64), nullable=False, default="canonical", server_default="canonical")
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=text("CURRENT_TIMESTAMP")
    )
    projection_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_started", server_default="not_started"
    )
    recovery_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_ingest_run_status"),
        CheckConstraint("source_count >= 0", name="ck_ingest_run_source_count"),
        CheckConstraint("program_count >= 0", name="ck_ingest_run_program_count"),
        CheckConstraint("curriculum_item_count >= 0", name="ck_ingest_run_curriculum_item_count"),
        CheckConstraint("event_count >= 0", name="ck_ingest_run_event_count"),
        CheckConstraint("campus_point_count >= 0", name="ck_ingest_run_campus_point_count"),
        CheckConstraint("inserted_count >= 0", name="ck_ingest_run_inserted_count"),
        CheckConstraint("updated_count >= 0", name="ck_ingest_run_updated_count"),
        CheckConstraint("unchanged_count >= 0", name="ck_ingest_run_unchanged_count"),
        CheckConstraint("removed_count >= 0", name="ck_ingest_run_removed_count"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_ingest_run_duration_ms"),
        CheckConstraint("source_gap_count >= 0", name="ck_ingest_run_source_gap_count"),
        CheckConstraint("critical_gap_count >= 0", name="ck_ingest_run_critical_gap_count"),
        CheckConstraint("drift_status IN ('not_checked', 'passed', 'rejected')", name="ck_ingest_run_drift_status"),
        CheckConstraint("quality_status IN ('not_checked', 'passed', 'degraded', 'rejected')", name="ck_ingest_run_quality_status"),
        CheckConstraint("length(university_id) > 0", name="ck_ingest_run_university_id"),
        CheckConstraint("length(projection_target) > 0", name="ck_ingest_run_projection_target"),
        CheckConstraint(
            "projection_status IN ('not_started', 'running', 'committed', 'reconciled', 'failed')",
            name="ck_ingest_run_projection_status",
        ),
        CheckConstraint("length(quality_metrics_json) > 0", name="ck_ingest_run_quality_metrics_json"),
        CheckConstraint("length(source_profile) > 0", name="ck_ingest_run_source_profile"),
        CheckConstraint("length(source_revision) > 0", name="ck_ingest_run_source_revision"),
        CheckConstraint("length(configuration_version) > 0", name="ck_ingest_run_configuration_version"),
        Index("ix_ingest_runs_source_profile_started_at", "source_profile", "started_at"),
        Index("ix_ingest_runs_status_started_at", "status", "started_at"),
        Index(
            "uq_ingest_runs_active_identity",
            "university_id",
            "source_profile",
            "projection_target",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
        Index("uq_ingest_runs_idempotency_key", "idempotency_key", unique=True, sqlite_where=text("idempotency_key IS NOT NULL"), postgresql_where=text("idempotency_key IS NOT NULL")),
    )


class SourceSnapshotModel(Base):
    __tablename__ = "source_snapshots"

    content_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    ingest_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_runs.id"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (
        CheckConstraint("length(content_sha256) = 64", name="ck_source_snapshot_sha256_length"),
        CheckConstraint("status_code >= 200 AND status_code <= 599", name="ck_source_snapshot_status"),
        Index("ix_source_snapshots_ingest_run_id", "ingest_run_id"),
    )


class RawSourceRecordModel(Base):
    __tablename__ = "raw_source_records"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    snapshot_sha256: Mapped[str] = mapped_column(ForeignKey("source_snapshots.content_sha256"), nullable=False)
    record_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_raw_source_records_snapshot_hash", "snapshot_sha256"),)
