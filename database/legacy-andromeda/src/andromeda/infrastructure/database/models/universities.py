from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class EducationLevelModel(Base):
    __tablename__ = "education_levels"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)


class UniversityModel(Base):
    __tablename__ = "universities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    city: Mapped[str] = mapped_column(String(256), nullable=False)
    official_site: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(String(512), nullable=False)

    __table_args__ = (
        CheckConstraint("length(name) > 0", name="ck_university_name_non_empty"),
        CheckConstraint("length(city) > 0", name="ck_university_city_non_empty"),
        CheckConstraint("length(address) > 0", name="ck_university_address_non_empty"),
        CheckConstraint("id LIKE 'university:%'", name="ck_university_id_shape"),
    )


class DirectionModel(Base):
    __tablename__ = "directions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    education_level: Mapped[str] = mapped_column(ForeignKey("education_levels.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("university_id", "code", name="uq_direction_university_code"),
        CheckConstraint("length(code) = 8 AND substr(code, 3, 1) = '.' AND substr(code, 6, 1) = '.'", name="ck_direction_code_shape"),
        CheckConstraint("id LIKE 'direction:%:%' AND id = 'direction:' || replace(university_id, 'university:', '') || ':' || code", name="ck_direction_id_matches_university_code"),
        CheckConstraint("length(name) > 0", name="ck_direction_name_non_empty"),
    )
