from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class AdmissionOfferingModel(Base):
    __tablename__ = "admission_offerings"

    id: Mapped[str] = mapped_column(String(320), primary_key=True)
    program_id: Mapped[str] = mapped_column(ForeignKey("educational_programs.id"), nullable=False)
    admission_year: Mapped[int] = mapped_column(Integer, nullable=False)
    # The database uses explicit sentinels for nullable contract dimensions so
    # the natural identity remains unique on SQLite and PostgreSQL alike.
    study_form: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    funding_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    places: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    university_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    field: Mapped[str | None] = mapped_column(String(256), nullable=True)
    record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "admission_year",
            "study_form",
            "funding_type",
            "scope",
            name="uq_admission_offering_identity",
        ),
        Index("ix_admission_offerings_program_year", "program_id", "admission_year"),
        CheckConstraint("admission_year >= 2000 AND admission_year <= 2100", name="ck_admission_offering_year"),
        CheckConstraint("places IS NULL OR (places >= 0 AND places <= 100000)", name="ck_admission_offering_places"),
        CheckConstraint("length(id) > 0", name="ck_admission_offering_id_non_empty"),
        CheckConstraint("length(source_kind) > 0", name="ck_admission_offering_source_kind"),
        CheckConstraint("length(source_url) > 0", name="ck_admission_offering_source_url"),
        CheckConstraint("length(content_sha256) = 64", name="ck_admission_offering_sha256"),
    )


class AdmissionExamRequirementModel(Base):
    __tablename__ = "admission_exam_requirements"

    id: Mapped[str] = mapped_column(String(384), primary_key=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("admission_offerings.id", ondelete="CASCADE"), nullable=False)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    minimum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    is_choice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_kind: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    university_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    field: Mapped[str | None] = mapped_column(String(256), nullable=True)
    record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("offering_id", "subject", "source_name", name="uq_admission_exam_identity"),
        Index("ix_admission_exams_offering", "offering_id"),
        CheckConstraint("length(subject) > 0", name="ck_admission_exam_subject"),
        CheckConstraint("minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 100)", name="ck_admission_exam_minimum"),
        CheckConstraint("length(content_sha256) = 64", name="ck_admission_exam_sha256"),
    )


class AdmissionQuotaModel(Base):
    __tablename__ = "admission_quotas"

    id: Mapped[str] = mapped_column(String(384), primary_key=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("admission_offerings.id", ondelete="CASCADE"), nullable=False)
    quota_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    places: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    university_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    field: Mapped[str | None] = mapped_column(String(256), nullable=True)
    record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("offering_id", "quota_type", "source_name", name="uq_admission_quota_identity"),
        Index("ix_admission_quotas_offering", "offering_id"),
        CheckConstraint("places >= 0 AND places <= 100000", name="ck_admission_quota_places"),
        CheckConstraint("length(quota_type) > 0", name="ck_admission_quota_type"),
        CheckConstraint("length(content_sha256) = 64", name="ck_admission_quota_sha256"),
    )


class AdmissionPassingScoreModel(Base):
    __tablename__ = "admission_passing_scores"

    id: Mapped[str] = mapped_column(String(384), primary_key=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("admission_offerings.id", ondelete="CASCADE"), nullable=False)
    score_type: Mapped[str] = mapped_column(String(32), nullable=False)
    competition_type: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="numeric")
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    university_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    field: Mapped[str | None] = mapped_column(String(256), nullable=True)
    record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint(
            "offering_id",
            "competition_type",
            "status",
            "score_type",
            name="uq_admission_passing_score_identity",
        ),
        Index("ix_admission_passing_scores_offering", "offering_id"),
        CheckConstraint("length(score_type) > 0", name="ck_admission_passing_score_type"),
        CheckConstraint(
            "competition_type IN ('general', 'special_quota', 'separate_quota', 'targeted', 'bvi', 'other')",
            name="ck_admission_passing_score_competition_type",
        ),
        CheckConstraint("status IN ('numeric', 'bvi')", name="ck_admission_passing_score_status"),
        CheckConstraint("score >= 0 AND score <= 400", name="ck_admission_passing_score_range"),
        CheckConstraint(
            "(status = 'numeric' AND score IS NOT NULL) OR "
            "(status = 'bvi' AND score IS NULL AND competition_type IN "
            "('bvi', 'special_quota', 'separate_quota', 'targeted'))",
            name="ck_admission_passing_score_status_value",
        ),
        CheckConstraint("length(content_sha256) = 64", name="ck_admission_passing_score_sha256"),
    )


class AdmissionTuitionModel(Base):
    __tablename__ = "admission_tuition"

    id: Mapped[str] = mapped_column(String(384), primary_key=True)
    offering_id: Mapped[str] = mapped_column(ForeignKey("admission_offerings.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    academic_year: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period: Mapped[str | None] = mapped_column(String(512), nullable=True)
    study_form: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_discounted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_kind: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    university_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    field: Mapped[str | None] = mapped_column(String(256), nullable=True)
    record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("offering_id", "amount", "is_discounted", "study_form", name="uq_admission_tuition_identity"),
        Index("ix_admission_tuition_offering", "offering_id"),
        CheckConstraint("amount >= 0", name="ck_admission_tuition_amount"),
        CheckConstraint("length(currency) > 0", name="ck_admission_tuition_currency"),
        CheckConstraint("length(content_sha256) = 64", name="ck_admission_tuition_sha256"),
    )


__all__ = [
    "AdmissionExamRequirementModel",
    "AdmissionOfferingModel",
    "AdmissionPassingScoreModel",
    "AdmissionQuotaModel",
    "AdmissionTuitionModel",
]
