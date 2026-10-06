"""Release-scoped source manifest, explicit links, and manual review records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from academic_data_service.infrastructure.database.base import Base
from academic_data_service.infrastructure.database.mixins import (
    ReleaseScopedMixin,
    release_scoped_constraints,
)


class SourceArtifactModel(ReleaseScopedMixin, Base):
    __tablename__ = "source_artifacts"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="valid_sha256"),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="nonnegative_byte_size"),
        Index("ix_source_artifacts_release_storage_status", "release_id", "storage_status"),
    )

    source_type: Mapped[str | None] = mapped_column(String(100))
    requested_url: Mapped[str | None] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str | None] = mapped_column(String(64))
    content_type: Mapped[str | None] = mapped_column(String(160))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    status_code: Mapped[int | None] = mapped_column(Integer)
    raw_path: Mapped[str | None] = mapped_column(Text)
    storage_status: Mapped[str] = mapped_column(String(48), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceRelationshipModel(ReleaseScopedMixin, Base):
    """Verbatim normalized relationship row; typed links live in join tables."""

    __tablename__ = "source_relationships"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        CheckConstraint("length(source_key) > 0", name="source_key_present"),
        CheckConstraint("length(target_key) > 0", name="target_key_present"),
        ForeignKeyConstraint(
            ["release_id", "source_artifact_id"],
            ["source_artifacts.release_id", "source_artifacts.id"],
            name="fk_source_relationships_artifact_release",
        ),
        Index("ix_source_relationships_release_type", "release_id", "relation_type"),
    )

    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_key: Mapped[str] = mapped_column(String(512), nullable=False)
    target_key: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_kind: Mapped[str | None] = mapped_column(String(100))
    source_artifact_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ManualReviewModel(ReleaseScopedMixin, Base):
    """Unresolved source link or data issue, intentionally without a guessed FK."""

    __tablename__ = "manual_review_items"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        CheckConstraint("status IN ('open', 'resolved', 'dismissed')", name="valid_status"),
        ForeignKeyConstraint(
            ["release_id", "source_artifact_id"],
            ["source_artifacts.release_id", "source_artifacts.id"],
            name="fk_manual_review_items_artifact_release",
        ),
        Index("ix_manual_review_items_release_status", "release_id", "status"),
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    issue_code: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(100))
    subject_key: Mapped[str | None] = mapped_column(String(512))
    source_key: Mapped[str | None] = mapped_column(String(512))
    target_key: Mapped[str | None] = mapped_column(String(512))
    candidate_keys: Mapped[list[str] | None] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_artifact_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    source_locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SourceObservationModel(ReleaseScopedMixin, Base):
    """Unmodeled source-table payload preserved for later typed projection."""

    __tablename__ = "source_observations"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "source_artifact_id"],
            ["source_artifacts.release_id", "source_artifacts.id"],
            name="fk_source_observations_artifact_release",
        ),
        Index("ix_source_observations_release_dataset", "release_id", "dataset_name"),
    )

    dataset_name: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_artifact_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
