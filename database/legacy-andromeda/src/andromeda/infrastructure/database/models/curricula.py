from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class AssessmentTypeModel(Base):
    __tablename__ = "assessment_types"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)


class CurriculumModel(Base):
    __tablename__ = "curricula"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    program_id: Mapped[str] = mapped_column(ForeignKey("educational_programs.id"), nullable=False)
    education_year: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    source_gaps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")

    __table_args__ = (
        UniqueConstraint("program_id", "education_year", name="uq_curriculum_program_year"),
        CheckConstraint("education_year >= 2000 AND education_year <= 2100", name="ck_curriculum_education_year"),
        CheckConstraint("id LIKE 'curriculum:%'", name="ck_curriculum_id_shape"),
    )


class CurriculumItemModel(Base):
    __tablename__ = "curriculum_items"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    curriculum_id: Mapped[str] = mapped_column(ForeignKey("curricula.id"), nullable=False)
    discipline_id: Mapped[str] = mapped_column(ForeignKey("disciplines.id"), nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester_identity: Mapped[str] = mapped_column(String(16), nullable=False)
    hours: Mapped[int] = mapped_column(Integer, nullable=False)
    credits: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    source_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("curriculum_id", "discipline_id", "semester_identity", name="uq_curriculum_item_identity"),
        CheckConstraint("semester IS NULL OR (semester >= 1 AND semester <= 12)", name="ck_item_semester"),
        CheckConstraint("semester_identity = 'unassigned' OR semester_identity LIKE 'legacy:%' OR semester_identity = 'semester:' || semester", name="ck_item_semester_identity"),
        CheckConstraint("hours >= 0 AND hours <= 2000", name="ck_item_hours"),
        CheckConstraint("credits IS NULL OR (credits >= 0 AND credits <= 60)", name="ck_item_credits"),
        CheckConstraint("length(source_name) > 0", name="ck_item_source_name_non_empty"),
        CheckConstraint("source_position IS NULL OR source_position >= 1", name="ck_item_source_position"),
    )


class CurriculumItemAssessmentModel(Base):
    __tablename__ = "curriculum_item_assessments"

    curriculum_item_id: Mapped[str] = mapped_column(ForeignKey("curriculum_items.id", ondelete="CASCADE"), primary_key=True)
    assessment_type_id: Mapped[str] = mapped_column(ForeignKey("assessment_types.id"), primary_key=True)
