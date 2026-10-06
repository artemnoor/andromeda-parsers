"""Import and release lifecycle tables owned by this service."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from academic_data_service.infrastructure.database.base import Base


class ServiceMetadataModel(Base):
    __tablename__ = "service_metadata"

    metadata_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    metadata_value: Mapped[str] = mapped_column(String(512), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ImportBatchModel(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('validated', 'staging', 'committed', 'failed')",
            name="valid_status",
        ),
        CheckConstraint(
            "source_bundle_sha256 ~ '^[0-9a-f]{64}$'",
            name="valid_source_bundle_sha256",
        ),
        Index("ix_import_batches_status_started_at", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mapper_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    row_counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failure_code: Mapped[str | None] = mapped_column(String(80))


class DataReleaseModel(Base):
    __tablename__ = "data_releases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('staging', 'committed', 'failed')",
            name="valid_status",
        ),
        CheckConstraint(
            "source_bundle_sha256 ~ '^[0-9a-f]{64}$'",
            name="valid_source_bundle_sha256",
        ),
        CheckConstraint(
            "reconciliation_status IS NULL OR "
            "reconciliation_status IN ('passed', 'passed_with_gaps')",
            name="valid_reconciliation_status",
        ),
        UniqueConstraint(
            "source_bundle_sha256",
            "mapper_version",
            name="uq_data_releases_bundle_mapper",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    release_key: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    source_bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mapper_version: Mapped[str] = mapped_column(String(80), nullable=False)
    batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    schema_revision: Mapped[str | None] = mapped_column(String(64))
    reconciliation_status: Mapped[str | None] = mapped_column(String(32))
    reconciliation_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActiveDataReleaseModel(Base):
    __tablename__ = "active_data_release"
    __table_args__ = (CheckConstraint("slot_key = 'active'", name="only_active_slot"),)

    slot_key: Mapped[str] = mapped_column(
        String(16), primary_key=True, server_default=text("'active'")
    )
    release_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("data_releases.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MigrationAuditModel(Base):
    __tablename__ = "migration_audit"
    __table_args__ = (
        CheckConstraint("operation IN ('upgrade')", name="valid_operation"),
        Index("ix_migration_audit_revision_applied_at", "migration_revision", "applied_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    migration_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
