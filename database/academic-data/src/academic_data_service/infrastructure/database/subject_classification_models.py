"""Versioned subject taxonomy and immutable Jev classification provenance."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from academic_data_service.infrastructure.database.base import Base


class SubjectTaxonomyModel(Base):
    __tablename__ = "subject_taxonomies"

    taxonomy_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    taxonomy_version: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class SubjectTaxonomyCategoryModel(Base):
    __tablename__ = "subject_taxonomy_categories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy_key", "taxonomy_version"],
            ["subject_taxonomies.taxonomy_key", "subject_taxonomies.taxonomy_version"],
            ondelete="RESTRICT",
            name="fk_subject_taxonomy_categories_taxonomy",
        ),
        CheckConstraint("ordinal BETWEEN 1 AND 16", name="valid_ordinal"),
        UniqueConstraint(
            "taxonomy_key", "taxonomy_version", "ordinal", name="uq_subject_taxonomy_ordinal"
        ),
    )

    taxonomy_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    taxonomy_version: Mapped[str] = mapped_column(String(40), primary_key=True)
    category_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)


class SubjectClassificationRunModel(Base):
    __tablename__ = "subject_classification_runs"
    __table_args__ = (
        UniqueConstraint("release_id", "external_key", name="uq_subject_classification_run_key"),
        UniqueConstraint("release_id", "id", name="uq_subject_classification_run_release_id"),
        ForeignKeyConstraint(
            ["release_id"],
            ["data_releases.id"],
            ondelete="RESTRICT",
            name="fk_subject_classification_run_release",
        ),
        ForeignKeyConstraint(
            ["taxonomy_key", "taxonomy_version"],
            ["subject_taxonomies.taxonomy_key", "subject_taxonomies.taxonomy_version"],
            name="fk_subject_classification_run_taxonomy",
        ),
        CheckConstraint("status = 'complete'", name="complete_only"),
        CheckConstraint(
            "expected_count > 0 AND classified_count = expected_count", name="complete_counts"
        ),
        CheckConstraint("failed_count = 0", name="no_failed_classifications"),
        CheckConstraint("source_bundle_sha256 ~ '^[0-9a-f]{64}$'", name="valid_source_digest"),
        CheckConstraint("source_input_sha256 ~ '^[0-9a-f]{64}$'", name="valid_input_digest"),
        CheckConstraint("result_sha256 ~ '^[0-9a-f]{64}$'", name="valid_result_digest"),
        CheckConstraint("prompt_sha256 ~ '^[0-9a-f]{64}$'", name="valid_prompt_digest"),
        CheckConstraint("cost_rub IS NULL OR cost_rub >= 0", name="nonnegative_cost"),
        Index("ix_subject_classification_runs_release_created", "release_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    external_key: Mapped[str] = mapped_column(String(200), nullable=False)
    taxonomy_key: Mapped[str] = mapped_column(String(100), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_model: Mapped[str] = mapped_column(String(120), nullable=False)
    resolved_model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    expected_count: Mapped[int] = mapped_column(nullable=False)
    classified_count: Mapped[int] = mapped_column(nullable=False)
    failed_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    cost_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SubjectClassificationModel(Base):
    __tablename__ = "subject_classifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["release_id", "run_id"],
            ["subject_classification_runs.release_id", "subject_classification_runs.id"],
            ondelete="RESTRICT",
            name="fk_subject_classifications_run_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "catalog_course_id"],
            ["catalog_courses.release_id", "catalog_courses.id"],
            ondelete="RESTRICT",
            name="fk_subject_classifications_catalog_course",
        ),
        ForeignKeyConstraint(
            ["release_id", "curriculum_item_id"],
            ["curriculum_items.release_id", "curriculum_items.id"],
            ondelete="RESTRICT",
            name="fk_subject_classifications_curriculum_item",
        ),
        ForeignKeyConstraint(
            ["taxonomy_key", "taxonomy_version", "category_code"],
            [
                "subject_taxonomy_categories.taxonomy_key",
                "subject_taxonomy_categories.taxonomy_version",
                "subject_taxonomy_categories.category_code",
            ],
            ondelete="RESTRICT",
            name="fk_subject_classifications_category",
        ),
        CheckConstraint(
            "num_nonnulls(catalog_course_id, curriculum_item_id) = 1",
            name="exactly_one_typed_subject",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_confidence"),
        CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name="valid_input_digest"),
        CheckConstraint(
            "review_status IN ('classified', 'needs_review')", name="valid_review_status"
        ),
        Index("ix_subject_classifications_release_course", "release_id", "catalog_course_id"),
        Index("ix_subject_classifications_release_item", "release_id", "curriculum_item_id"),
        Index("ix_subject_classifications_run", "run_id", "category_code"),
        UniqueConstraint(
            "run_id", "catalog_course_id", name="uq_subject_classifications_run_course"
        ),
        UniqueConstraint(
            "run_id", "curriculum_item_id", name="uq_subject_classifications_run_item"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    catalog_course_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    curriculum_item_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    taxonomy_key: Mapped[str] = mapped_column(String(100), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    category_code: Mapped[str] = mapped_column(String(8), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    probabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    jev_answer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    review_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
