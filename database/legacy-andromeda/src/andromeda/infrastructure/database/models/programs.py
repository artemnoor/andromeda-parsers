from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class ProgramModel(Base):
    __tablename__ = "educational_programs"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    direction_id: Mapped[str] = mapped_column(ForeignKey("directions.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    education_year: Mapped[int] = mapped_column(Integer, nullable=False)
    study_plan_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    source_gaps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")

    __table_args__ = (
        UniqueConstraint("direction_id", "code", name="uq_program_direction_code"),
        CheckConstraint("id LIKE 'program:%:%'", name="ck_program_id_matches_university_code"),
        CheckConstraint("code LIKE '__.__.__-%'", name="ck_program_code_shape"),
        CheckConstraint("education_year >= 2000 AND education_year <= 2100", name="ck_program_education_year"),
        CheckConstraint("length(name) > 0", name="ck_program_name_non_empty"),
    )


EducationalProgramModel = ProgramModel
