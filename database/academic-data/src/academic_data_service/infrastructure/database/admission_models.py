"""Typed admission campaigns, requirements, capacity, prices, and results."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from academic_data_service.infrastructure.database.base import Base
from academic_data_service.infrastructure.database.mixins import (
    ReleaseScopedMixin,
    TemporalAssertionMixin,
    release_scoped_constraints,
)


class AdmissionCampaignModel(ReleaseScopedMixin, Base):
    __tablename__ = "admission_campaigns"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "university_id"],
            ["universities.release_id", "universities.id"],
            ondelete="RESTRICT",
            name="fk_admission_campaigns_university_release",
        ),
        UniqueConstraint(
            "release_id", "university_id", "year", "campaign_kind", name="uq_campaign_identity"
        ),
        CheckConstraint("year BETWEEN 1900 AND 2200", name="valid_year"),
        Index("ix_admission_campaigns_release_year", "release_id", "year"),
    )

    university_id: Mapped[UUID] = mapped_column(nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    education_level: Mapped[str | None] = mapped_column(String(80))
    campaign_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    date_note: Mapped[str | None] = mapped_column(Text)


class CampaignCalendarEventModel(ReleaseScopedMixin, Base):
    __tablename__ = "campaign_calendar_events"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "campaign_id"],
            ["admission_campaigns.release_id", "admission_campaigns.id"],
            ondelete="CASCADE",
            name="fk_campaign_calendar_events_campaign_release",
        ),
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR starts_at <= ends_at",
            name="valid_time_range",
        ),
        Index("ix_campaign_calendar_events_release_campaign", "release_id", "campaign_id"),
    )

    campaign_id: Mapped[UUID] = mapped_column(nullable=False)
    event_code: Mapped[str | None] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    date_value: Mapped[date | None] = mapped_column(Date)
    time_value: Mapped[time | None] = mapped_column(Time)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_text: Mapped[str | None] = mapped_column(Text)


class FundingTypeModel(ReleaseScopedMixin, Base):
    __tablename__ = "funding_types"
    __table_args__ = release_scoped_constraints(
        __tablename__, UniqueConstraint("release_id", "code", name="uq_funding_types_release_code")
    )

    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class QuotaTypeModel(ReleaseScopedMixin, Base):
    __tablename__ = "quota_types"
    __table_args__ = release_scoped_constraints(
        __tablename__, UniqueConstraint("release_id", "code", name="uq_quota_types_release_code")
    )

    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class ProgramOfferingModel(ReleaseScopedMixin, Base):
    __tablename__ = "program_offerings"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "campaign_id"],
            ["admission_campaigns.release_id", "admission_campaigns.id"],
            ondelete="CASCADE",
            name="fk_program_offerings_campaign_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "direction_id"],
            ["directions.release_id", "directions.id"],
            ondelete="RESTRICT",
            name="fk_program_offerings_direction_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "program_id"],
            ["educational_programs.release_id", "educational_programs.id"],
            ondelete="RESTRICT",
            name="fk_program_offerings_program_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "department_id"],
            ["departments.release_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_program_offerings_department_release",
        ),
        CheckConstraint("year BETWEEN 1900 AND 2200", name="valid_year"),
        Index("ix_program_offerings_release_campaign", "release_id", "campaign_id"),
        Index("ix_program_offerings_release_direction", "release_id", "direction_id"),
    )

    campaign_id: Mapped[UUID] = mapped_column(nullable=False)
    direction_id: Mapped[UUID | None] = mapped_column()
    direction_code: Mapped[str | None] = mapped_column(String(32))
    program_id: Mapped[UUID | None] = mapped_column()
    department_id: Mapped[UUID | None] = mapped_column()
    department_code: Mapped[str | None] = mapped_column(String(80))
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    study_form: Mapped[str | None] = mapped_column(String(80))
    language: Mapped[str | None] = mapped_column(String(80))
    study_duration_label: Mapped[str | None] = mapped_column(String(100))
    program_name_in_document: Mapped[str | None] = mapped_column(Text)
    campus_scope: Mapped[str | None] = mapped_column(String(100))
    catalog_join_status: Mapped[str | None] = mapped_column(String(100))
    source_locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_row: Mapped[list[Any] | None] = mapped_column(JSONB)


class CompetitionPoolModel(ReleaseScopedMixin, TemporalAssertionMixin, Base):
    __tablename__ = "competition_pools"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "campaign_id"],
            ["admission_campaigns.release_id", "admission_campaigns.id"],
            ondelete="CASCADE",
            name="fk_competition_pools_campaign_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "direction_id"],
            ["directions.release_id", "directions.id"],
            ondelete="RESTRICT",
            name="fk_competition_pools_direction_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "department_id"],
            ["departments.release_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_competition_pools_department_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "funding_type_id"],
            ["funding_types.release_id", "funding_types.id"],
            ondelete="RESTRICT",
            name="fk_competition_pools_funding_type_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "quota_type_id"],
            ["quota_types.release_id", "quota_types.id"],
            ondelete="RESTRICT",
            name="fk_competition_pools_quota_type_release",
        ),
        CheckConstraint("year BETWEEN 1900 AND 2200", name="valid_year"),
        CheckConstraint("places IS NULL OR places >= 0", name="nonnegative_places"),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="valid_validity_period",
        ),
        Index("ix_competition_pools_release_campaign", "release_id", "campaign_id"),
        Index("ix_competition_pools_release_direction", "release_id", "direction_id"),
    )

    campaign_id: Mapped[UUID] = mapped_column(nullable=False)
    direction_id: Mapped[UUID | None] = mapped_column()
    department_id: Mapped[UUID | None] = mapped_column()
    direction_code: Mapped[str | None] = mapped_column(String(32))
    department_code: Mapped[str | None] = mapped_column(String(80))
    funding_type_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    quota_type_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    funding_type_code: Mapped[str | None] = mapped_column(String(100))
    quota_type_code: Mapped[str | None] = mapped_column(String(100))
    scope_level: Mapped[str | None] = mapped_column(String(80))
    places: Mapped[int | None] = mapped_column(Integer)
    places_by_source_row: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    source_locators: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)


class CompetitionPoolOfferingModel(ReleaseScopedMixin, Base):
    __tablename__ = "competition_pool_offerings"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "pool_id"],
            ["competition_pools.release_id", "competition_pools.id"],
            ondelete="CASCADE",
            name="fk_pool_offerings_pool_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "offering_id"],
            ["program_offerings.release_id", "program_offerings.id"],
            ondelete="CASCADE",
            name="fk_pool_offerings_offering_release",
        ),
        UniqueConstraint("release_id", "pool_id", "offering_id", name="uq_pool_offerings_pair"),
    )

    pool_id: Mapped[UUID] = mapped_column(nullable=False)
    offering_id: Mapped[UUID] = mapped_column(nullable=False)


class PlaceQuotaAssertionModel(ReleaseScopedMixin, TemporalAssertionMixin, Base):
    __tablename__ = "place_quota_assertions"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "campaign_id"],
            ["admission_campaigns.release_id", "admission_campaigns.id"],
            ondelete="CASCADE",
            name="fk_place_quota_assertions_campaign_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "pool_id"],
            ["competition_pools.release_id", "competition_pools.id"],
            ondelete="CASCADE",
            name="fk_place_quota_assertions_pool_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "funding_type_id"],
            ["funding_types.release_id", "funding_types.id"],
            ondelete="RESTRICT",
            name="fk_place_quota_assertions_funding_type_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "quota_type_id"],
            ["quota_types.release_id", "quota_types.id"],
            ondelete="RESTRICT",
            name="fk_place_quota_assertions_quota_type_release",
        ),
        CheckConstraint("places >= 0", name="nonnegative_places"),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="valid_validity_period",
        ),
        Index("ix_place_quota_assertions_release_campaign", "release_id", "campaign_id"),
        Index("ix_place_quota_assertions_release_pool", "release_id", "pool_id"),
    )

    campaign_id: Mapped[UUID] = mapped_column(nullable=False)
    pool_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    funding_type_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    quota_type_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    places: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_level: Mapped[str | None] = mapped_column(String(80))
    source_locators: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)


class ExamModel(ReleaseScopedMixin, Base):
    __tablename__ = "admission_exams"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        UniqueConstraint("release_id", "code", name="uq_admission_exams_release_code"),
    )

    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class AdmissionRequirementSetModel(ReleaseScopedMixin, TemporalAssertionMixin, Base):
    __tablename__ = "admission_requirement_sets"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "campaign_id"],
            ["admission_campaigns.release_id", "admission_campaigns.id"],
            ondelete="CASCADE",
            name="fk_requirement_sets_campaign_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "direction_id"],
            ["directions.release_id", "directions.id"],
            ondelete="RESTRICT",
            name="fk_requirement_sets_direction_release",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="valid_validity_period",
        ),
        Index("ix_requirement_sets_release_campaign", "release_id", "campaign_id"),
    )

    campaign_id: Mapped[UUID] = mapped_column(nullable=False)
    direction_id: Mapped[UUID | None] = mapped_column()
    direction_code: Mapped[str | None] = mapped_column(String(32))
    applicant_category_text: Mapped[str | None] = mapped_column(Text)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_requirement_tree: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AdmissionRequirementNodeModel(ReleaseScopedMixin, Base):
    __tablename__ = "admission_requirement_nodes"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "requirement_set_id"],
            ["admission_requirement_sets.release_id", "admission_requirement_sets.id"],
            ondelete="CASCADE",
            name="fk_requirement_nodes_set_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "exam_id"],
            ["admission_exams.release_id", "admission_exams.id"],
            ondelete="RESTRICT",
            name="fk_requirement_nodes_exam_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "requirement_set_id", "parent_id"],
            [
                "admission_requirement_nodes.release_id",
                "admission_requirement_nodes.requirement_set_id",
                "admission_requirement_nodes.id",
            ],
            ondelete="CASCADE",
            name="fk_requirement_nodes_parent_same_tree",
        ),
        UniqueConstraint(
            "release_id", "requirement_set_id", "id", name="uq_requirement_nodes_set_id"
        ),
        UniqueConstraint(
            "release_id",
            "requirement_set_id",
            "path_key",
            name="uq_requirement_nodes_set_path",
        ),
        UniqueConstraint(
            "release_id",
            "requirement_set_id",
            "parent_id",
            "ordinal",
            name="uq_requirement_nodes_sibling_order",
        ),
        CheckConstraint("ordinal >= 0", name="valid_ordinal"),
        CheckConstraint("node_kind IN ('operator', 'exam')", name="valid_node_kind"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
        CheckConstraint(
            "operator IS NULL OR operator IN ('AND', 'OR', 'AT_LEAST')",
            name="valid_operator",
        ),
        CheckConstraint("min_count IS NULL OR min_count >= 1", name="valid_min_count"),
        CheckConstraint(
            "minimum_score IS NULL OR minimum_score >= 0", name="nonnegative_minimum_score"
        ),
        CheckConstraint(
            "(node_kind = 'operator' AND operator IS NOT NULL AND exam_id IS NULL "
            "AND minimum_score IS NULL) OR "
            "(node_kind = 'exam' AND operator IS NULL AND exam_id IS NOT NULL "
            "AND min_count IS NULL)",
            name="node_shape_matches_kind",
        ),
        Index(
            "ix_requirement_nodes_release_set_parent",
            "release_id",
            "requirement_set_id",
            "parent_id",
        ),
        Index(
            "uq_requirement_nodes_single_root",
            "release_id",
            "requirement_set_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )

    requirement_set_id: Mapped[UUID] = mapped_column(nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    path_key: Mapped[str] = mapped_column(String(512), nullable=False)
    node_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    operator: Mapped[str | None] = mapped_column(String(16))
    min_count: Mapped[int | None] = mapped_column(Integer)
    exam_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    subject_code: Mapped[str | None] = mapped_column(String(120))
    minimum_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    is_choice: Mapped[bool | None] = mapped_column(nullable=True)
    tiebreak_rank: Mapped[str | None] = mapped_column(String(24))


class OfferingRequirementLinkModel(ReleaseScopedMixin, Base):
    __tablename__ = "offering_requirement_links"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "offering_id"],
            ["program_offerings.release_id", "program_offerings.id"],
            ondelete="CASCADE",
            name="fk_offering_requirement_links_offering_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "requirement_set_id"],
            ["admission_requirement_sets.release_id", "admission_requirement_sets.id"],
            ondelete="CASCADE",
            name="fk_offering_requirement_links_set_release",
        ),
        UniqueConstraint(
            "release_id", "offering_id", "requirement_set_id", name="uq_offering_requirement_pair"
        ),
        CheckConstraint(
            "relation_type IN ('offering_has_exam_requirement_for_direction', "
            "'offering_has_direction_exam_requirement')",
            name="valid_relation_type",
        ),
    )

    offering_id: Mapped[UUID] = mapped_column(nullable=False)
    requirement_set_id: Mapped[UUID] = mapped_column(nullable=False)
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)


class TuitionAssertionModel(ReleaseScopedMixin, TemporalAssertionMixin, Base):
    __tablename__ = "tuition_assertions"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "direction_id"],
            ["directions.release_id", "directions.id"],
            ondelete="RESTRICT",
            name="fk_tuition_assertions_direction_release",
        ),
        CheckConstraint("amount IS NULL OR amount >= 0", name="nonnegative_amount"),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="valid_validity_period",
        ),
        Index("ix_tuition_assertions_release_direction", "release_id", "direction_id"),
    )

    direction_id: Mapped[UUID | None] = mapped_column()
    direction_code: Mapped[str | None] = mapped_column(String(32))
    direction_name: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    academic_year_label: Mapped[str | None] = mapped_column(String(80))
    table_category: Mapped[str | None] = mapped_column(String(120))
    campus_scope: Mapped[str | None] = mapped_column(String(120))
    raw_cells: Mapped[list[Any] | None] = mapped_column(JSONB)
    source_locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class HistoricalAdmissionStatisticModel(ReleaseScopedMixin, TemporalAssertionMixin, Base):
    __tablename__ = "historical_admission_statistics"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "direction_id"],
            ["directions.release_id", "directions.id"],
            ondelete="RESTRICT",
            name="fk_historical_statistics_direction_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "department_id"],
            ["departments.release_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_historical_statistics_department_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "funding_type_id"],
            ["funding_types.release_id", "funding_types.id"],
            ondelete="RESTRICT",
            name="fk_historical_statistics_funding_type_release",
        ),
        CheckConstraint("admission_year BETWEEN 1900 AND 2200", name="valid_admission_year"),
        CheckConstraint(
            "admitted_count IS NULL OR admitted_count >= 0", name="nonnegative_admitted_count"
        ),
        CheckConstraint(
            "minimum_score IS NULL OR minimum_score >= 0", name="nonnegative_minimum_score"
        ),
        CheckConstraint(
            "maximum_score IS NULL OR maximum_score >= 0", name="nonnegative_maximum_score"
        ),
        CheckConstraint(
            "average_score IS NULL OR average_score >= 0", name="nonnegative_average_score"
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="valid_validity_period",
        ),
        Index("ix_historical_statistics_release_year", "release_id", "admission_year"),
    )

    direction_id: Mapped[UUID | None] = mapped_column()
    department_id: Mapped[UUID | None] = mapped_column()
    direction_code: Mapped[str | None] = mapped_column(String(32))
    department_code: Mapped[str | None] = mapped_column(String(80))
    funding_type_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    admission_year: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_type: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_type: Mapped[str | None] = mapped_column(String(80))
    scope_label: Mapped[str | None] = mapped_column(String(160))
    funding_type_code: Mapped[str | None] = mapped_column(String(100))
    study_form: Mapped[str | None] = mapped_column(String(80))
    admitted_count: Mapped[int | None] = mapped_column(Integer)
    minimum_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    maximum_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    average_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    campus_scope: Mapped[str | None] = mapped_column(String(120))
    snapshot_date: Mapped[date | None] = mapped_column(Date)
    finality_note: Mapped[str | None] = mapped_column(Text)
    source_locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AdmissionStatisticModel(ReleaseScopedMixin, TemporalAssertionMixin, Base):
    __tablename__ = "admission_statistics"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "direction_id"],
            ["directions.release_id", "directions.id"],
            ondelete="RESTRICT",
            name="fk_admission_statistics_direction_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "funding_type_id"],
            ["funding_types.release_id", "funding_types.id"],
            ondelete="RESTRICT",
            name="fk_admission_statistics_funding_type_release",
        ),
        CheckConstraint("admission_year BETWEEN 1900 AND 2200", name="valid_admission_year"),
        CheckConstraint("score IS NULL OR score >= 0", name="nonnegative_score"),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="valid_validity_period",
        ),
        Index("ix_admission_statistics_release_year", "release_id", "admission_year"),
    )

    direction_id: Mapped[UUID | None] = mapped_column()
    direction_code: Mapped[str | None] = mapped_column(String(32))
    funding_type_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    admission_year: Mapped[int] = mapped_column(Integer, nullable=False)
    admission_stage: Mapped[str | None] = mapped_column(String(80))
    competition_type: Mapped[str | None] = mapped_column(String(100))
    funding_type_code: Mapped[str | None] = mapped_column(String(100))
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    status: Mapped[str | None] = mapped_column(String(40))
    study_form: Mapped[str | None] = mapped_column(String(80))
    snapshot_date: Mapped[date | None] = mapped_column(Date)
    source_locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class IndividualAchievementPolicyModel(ReleaseScopedMixin, TemporalAssertionMixin, Base):
    __tablename__ = "individual_achievement_policies"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "campaign_id"],
            ["admission_campaigns.release_id", "admission_campaigns.id"],
            ondelete="CASCADE",
            name="fk_achievement_policies_campaign_release",
        ),
        CheckConstraint(
            "additional_points IS NULL OR additional_points >= 0",
            name="nonnegative_additional_points",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="valid_validity_period",
        ),
        Index("ix_achievement_policies_release_campaign", "release_id", "campaign_id"),
    )

    campaign_id: Mapped[UUID | None] = mapped_column()
    campaign_year: Mapped[int | None] = mapped_column(Integer)
    achievement_name: Mapped[str] = mapped_column(Text, nullable=False)
    additional_points: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    required_document: Mapped[str | None] = mapped_column(Text)
    row_number: Mapped[int | None] = mapped_column(Integer)
    source_locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AdmissionDocumentModel(ReleaseScopedMixin, Base):
    __tablename__ = "admission_documents"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        Index("ix_admission_documents_release_scope", "release_id", "scope_tag"),
    )

    document_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    document_group: Mapped[str | None] = mapped_column(Text)
    scope_tag: Mapped[str | None] = mapped_column(String(120))
    captured: Mapped[bool] = mapped_column(nullable=False)


class AdmissionDocumentPageModel(ReleaseScopedMixin, Base):
    __tablename__ = "admission_document_pages"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "document_id_fk"],
            ["admission_documents.release_id", "admission_documents.id"],
            ondelete="CASCADE",
            name="fk_admission_document_pages_document_release",
        ),
        CheckConstraint("page_number >= 1", name="valid_page_number"),
        Index("ix_admission_document_pages_release_document", "release_id", "document_id_fk"),
    )

    document_id_fk: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    page_text: Mapped[str | None] = mapped_column(Text)


class AdmissionResultSourceModel(ReleaseScopedMixin, Base):
    __tablename__ = "admission_result_sources"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="valid_sha256"),
        Index("ix_admission_result_sources_release_stored", "release_id", "stored"),
    )

    title: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str | None] = mapped_column(String(64))
    stored: Mapped[bool] = mapped_column(nullable=False)
    omission_reason: Mapped[str | None] = mapped_column(Text)


class RuleScopeModel(Base):
    """Typed policy scope; NULL on an axis means a wildcard on that axis."""

    __tablename__ = "rule_scopes"
    __table_args__ = (
        UniqueConstraint(
            "university_key",
            "campaign_year",
            "education_level_code",
            "audience_code",
            "surface_code",
            name="uq_rule_scopes_exact_axes",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "campaign_year IS NULL OR campaign_year BETWEEN 1900 AND 2200",
            name="valid_campaign_year",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    scope_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    university_key: Mapped[str | None] = mapped_column(String(256))
    campaign_year: Mapped[int | None] = mapped_column(Integer)
    education_level_code: Mapped[str | None] = mapped_column(String(80))
    audience_code: Mapped[str | None] = mapped_column(String(80))
    surface_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RulePackModel(Base):
    """Logical decision policy; source admission requirements remain elsewhere."""

    __tablename__ = "rule_packs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    external_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RulePackVersionModel(Base):
    """Immutable versioned policy body with database-enforced exact-scope dates."""

    __tablename__ = "rule_pack_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["rule_pack_id"], ["rule_packs.id"], ondelete="RESTRICT", name="fk_rule_versions_pack"
        ),
        ForeignKeyConstraint(
            ["scope_id"], ["rule_scopes.id"], ondelete="RESTRICT", name="fk_rule_versions_scope"
        ),
        UniqueConstraint(
            "rule_pack_id", "scope_id", "version", name="uq_rule_pack_versions_pack_scope_version"
        ),
        CheckConstraint("version >= 1", name="valid_version"),
        CheckConstraint("status IN ('draft', 'published', 'retired')", name="valid_status"),
        CheckConstraint("checksum ~ '^[0-9a-f]{64}$'", name="valid_checksum"),
        CheckConstraint(
            "NOT isempty(valid_during) AND NOT lower_inf(valid_during)",
            name="nonempty_validity_range",
        ),
        ExcludeConstraint(
            ("scope_id", "="),
            ("valid_during", "&&"),
            using="gist",
            where=text("status = 'published'"),
            name="ex_rule_pack_versions_published_scope_period",
        ),
        Index("ix_rule_pack_versions_scope_status", "scope_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    rule_pack_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_during: Mapped[Any] = mapped_column(DATERANGE, nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
