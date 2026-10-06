"""Canonical university catalog, program, department, and curriculum tables."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from academic_data_service.infrastructure.database.base import Base
from academic_data_service.infrastructure.database.mixins import (
    ReleaseScopedMixin,
    release_scoped_constraints,
)


class UniversityModel(ReleaseScopedMixin, Base):
    __tablename__ = "universities"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        UniqueConstraint("release_id", "official_code", name="uq_universities_release_code"),
    )

    official_code: Mapped[str | None] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    official_site: Mapped[str | None] = mapped_column(Text)
    identity_source_note: Mapped[str | None] = mapped_column(Text)


class DirectionModel(ReleaseScopedMixin, Base):
    __tablename__ = "directions"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "university_id"],
            ["universities.release_id", "universities.id"],
            ondelete="RESTRICT",
            name="fk_directions_university_release",
        ),
        UniqueConstraint(
            "release_id", "university_id", "code", name="uq_directions_university_code"
        ),
        CheckConstraint("duration_months IS NULL OR duration_months > 0", name="valid_duration"),
        Index("ix_directions_release_code", "release_id", "code"),
    )

    university_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    degree_label: Mapped[str | None] = mapped_column(String(200))
    duration_label: Mapped[str | None] = mapped_column(String(100))
    duration_months: Mapped[int | None] = mapped_column(Integer)
    qualification_label: Mapped[str | None] = mapped_column(String(200))
    catalog_course_names: Mapped[list[str] | None] = mapped_column(JSONB)
    catalog_page_url: Mapped[str | None] = mapped_column(Text)


class DepartmentModel(ReleaseScopedMixin, Base):
    __tablename__ = "departments"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "university_id"],
            ["universities.release_id", "universities.id"],
            ondelete="RESTRICT",
            name="fk_departments_university_release",
        ),
        UniqueConstraint(
            "release_id", "university_id", "official_code", name="uq_departments_university_code"
        ),
        Index("ix_departments_release_code", "release_id", "official_code"),
    )

    university_id: Mapped[UUID] = mapped_column(nullable=False)
    official_code: Mapped[str | None] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    faculty_name: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    campus_scope: Mapped[str | None] = mapped_column(String(100))


class DirectionDepartmentModel(ReleaseScopedMixin, Base):
    __tablename__ = "direction_departments"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "direction_id"],
            ["directions.release_id", "directions.id"],
            ondelete="CASCADE",
            name="fk_direction_departments_direction_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "department_id"],
            ["departments.release_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_direction_departments_department_release",
        ),
        UniqueConstraint(
            "release_id", "direction_id", "department_id", name="uq_direction_departments_pair"
        ),
    )

    direction_id: Mapped[UUID] = mapped_column(nullable=False)
    department_id: Mapped[UUID] = mapped_column(nullable=False)
    relation_type: Mapped[str | None] = mapped_column(String(32))
    source_relation_type: Mapped[str] = mapped_column(String(100), nullable=False)


class EducationalProgramModel(ReleaseScopedMixin, Base):
    __tablename__ = "educational_programs"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "direction_id"],
            ["directions.release_id", "directions.id"],
            ondelete="RESTRICT",
            name="fk_educational_programs_direction_release",
        ),
        CheckConstraint(
            "campus_scope IS NULL OR campus_scope IN ('head_moscow', 'other', 'unknown')",
            name="valid_campus_scope",
        ),
        Index("ix_educational_programs_release_code", "release_id", "code"),
    )

    direction_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_code: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    campus_scope: Mapped[str | None] = mapped_column(String(100))
    catalog_course_names: Mapped[list[str] | None] = mapped_column(JSONB)
    catalog_page_url: Mapped[str | None] = mapped_column(Text)
    study_plan_url: Mapped[str | None] = mapped_column(Text)
    source_card_position: Mapped[list[int] | None] = mapped_column(JSONB)


class EducationalProgramDepartmentModel(ReleaseScopedMixin, Base):
    __tablename__ = "educational_program_departments"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "program_id"],
            ["educational_programs.release_id", "educational_programs.id"],
            ondelete="CASCADE",
            name="fk_program_departments_program_release",
        ),
        ForeignKeyConstraint(
            ["release_id", "department_id"],
            ["departments.release_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_program_departments_department_release",
        ),
        UniqueConstraint(
            "release_id", "program_id", "department_id", name="uq_program_departments_pair"
        ),
        CheckConstraint(
            "relation_type IS NULL OR relation_type IN ('owner', 'coordinator', 'teaching')",
            name="valid_relation_type",
        ),
        CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'manual_review')",
            name="valid_verification_status",
        ),
    )

    program_id: Mapped[UUID] = mapped_column(nullable=False)
    department_id: Mapped[UUID] = mapped_column(nullable=False)
    relation_type: Mapped[str | None] = mapped_column(String(32))
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    source_relation_type: Mapped[str | None] = mapped_column(String(100))


class CourseModel(ReleaseScopedMixin, Base):
    __tablename__ = "catalog_courses"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "program_id"],
            ["educational_programs.release_id", "educational_programs.id"],
            ondelete="CASCADE",
            name="fk_catalog_courses_program_release",
        ),
        Index("ix_catalog_courses_release_program", "release_id", "program_id"),
    )

    program_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    description_status: Mapped[str | None] = mapped_column(String(100))


class StudyPlanModel(ReleaseScopedMixin, Base):
    __tablename__ = "study_plans"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "program_id"],
            ["educational_programs.release_id", "educational_programs.id"],
            ondelete="RESTRICT",
            name="fk_study_plans_program_release",
        ),
        CheckConstraint(
            "profile_link_status IN ('verified', 'unverified', 'unresolved', 'manual_review')",
            name="valid_profile_link_status",
        ),
        CheckConstraint(
            "semester_count IS NULL OR semester_count >= 0", name="valid_semester_count"
        ),
        CheckConstraint(
            "education_year IS NULL OR education_year >= 1900", name="valid_education_year"
        ),
        CheckConstraint(
            "status IN ('parsed', 'unavailable', 'unverified')",
            name="valid_status",
        ),
        CheckConstraint(
            "total_academic_hours IS NULL OR total_academic_hours >= 0",
            name="nonnegative_total_academic_hours",
        ),
        CheckConstraint(
            "total_astronomical_hours IS NULL OR total_astronomical_hours >= 0",
            name="nonnegative_total_astronomical_hours",
        ),
        Index("ix_study_plans_release_program", "release_id", "program_id"),
    )

    program_id: Mapped[UUID | None] = mapped_column()
    profile_link_status: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    education_year: Mapped[int | None] = mapped_column(Integer)
    start_year: Mapped[int | None] = mapped_column(Integer)
    version_label: Mapped[str | None] = mapped_column(String(160))
    source_version: Mapped[str | None] = mapped_column(String(160))
    profile_code: Mapped[str | None] = mapped_column(String(100))
    header_profile_code: Mapped[str | None] = mapped_column(String(100))
    profile_name_in_plan: Mapped[str | None] = mapped_column(Text)
    study_form: Mapped[str | None] = mapped_column(String(80))
    duration_label: Mapped[str | None] = mapped_column(String(100))
    semester_count: Mapped[int | None] = mapped_column(Integer)
    total_academic_hours: Mapped[int | None] = mapped_column(Integer)
    total_astronomical_hours: Mapped[int | None] = mapped_column(Integer)
    semester_totals: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    document_url: Mapped[str | None] = mapped_column(Text)
    download_url: Mapped[str | None] = mapped_column(Text)
    study_plan_url: Mapped[str | None] = mapped_column(Text)
    unavailable_reason: Mapped[str | None] = mapped_column(Text)


class CurriculumItemModel(ReleaseScopedMixin, Base):
    __tablename__ = "curriculum_items"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "study_plan_id"],
            ["study_plans.release_id", "study_plans.id"],
            ondelete="CASCADE",
            name="fk_curriculum_items_study_plan_release",
        ),
        CheckConstraint("ordinal >= 1", name="valid_ordinal"),
        CheckConstraint("semester IS NULL OR semester >= 1", name="valid_semester"),
        CheckConstraint("credits IS NULL OR credits >= 0", name="nonnegative_credits"),
        CheckConstraint(
            " AND ".join(
                f"({column} IS NULL OR {column} >= 0)"
                for column in (
                    "course_number",
                    "hours",
                    "lecture_hours",
                    "practice_hours",
                    "lab_hours",
                    "self_study_hours",
                    "total_hours",
                    "total_lecture_hours",
                    "total_practice_hours",
                    "total_lab_hours",
                    "total_self_study_hours",
                    "audited_hours",
                    "audited_hours_semester",
                    "semester_weeks",
                )
            ),
            name="nonnegative_hour_values",
        ),
        UniqueConstraint(
            "release_id", "study_plan_id", "ordinal", name="uq_curriculum_items_plan_ordinal"
        ),
        Index("ix_curriculum_items_release_plan_ordinal", "release_id", "study_plan_id", "ordinal"),
    )

    study_plan_id: Mapped[UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    record_type: Mapped[str | None] = mapped_column(String(80))
    is_data_row: Mapped[bool | None] = mapped_column(Boolean)
    source_record_id: Mapped[str | None] = mapped_column(String(120))
    discipline_name: Mapped[str | None] = mapped_column(Text)
    course_number: Mapped[int | None] = mapped_column(Integer)
    semester: Mapped[int | None] = mapped_column(Integer)
    credits: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    hours: Mapped[int | None] = mapped_column(Integer)
    lecture_hours: Mapped[int | None] = mapped_column(Integer)
    practice_hours: Mapped[int | None] = mapped_column(Integer)
    lab_hours: Mapped[int | None] = mapped_column(Integer)
    self_study_hours: Mapped[int | None] = mapped_column(Integer)
    total_hours: Mapped[int | None] = mapped_column(Integer)
    total_lecture_hours: Mapped[int | None] = mapped_column(Integer)
    total_practice_hours: Mapped[int | None] = mapped_column(Integer)
    total_lab_hours: Mapped[int | None] = mapped_column(Integer)
    total_self_study_hours: Mapped[int | None] = mapped_column(Integer)
    audited_hours: Mapped[int | None] = mapped_column(Integer)
    audited_hours_semester: Mapped[int | None] = mapped_column(Integer)
    semester_weeks: Mapped[int | None] = mapped_column(Integer)
    assessment_type: Mapped[str | None] = mapped_column(String(120))
    education_form: Mapped[str | None] = mapped_column(String(80))
    duration_label: Mapped[str | None] = mapped_column(String(100))
    qualification_label: Mapped[str | None] = mapped_column(String(200))
    department_name: Mapped[str | None] = mapped_column(Text)
    faculty_name: Mapped[str | None] = mapped_column(Text)
    chair_name: Mapped[str | None] = mapped_column(Text)
    source_row: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_document_url: Mapped[str | None] = mapped_column(Text)
    study_plan_url: Mapped[str | None] = mapped_column(Text)
    download_url: Mapped[str | None] = mapped_column(Text)
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
