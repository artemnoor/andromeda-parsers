from __future__ import annotations

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, Integer, Numeric
from decimal import Decimal

from ..base import Base


class DisciplineAreaModel(Base):
    __tablename__ = "discipline_areas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)

    __table_args__ = (
        CheckConstraint("length(id) > 0", name="ck_discipline_area_id_non_empty"),
        CheckConstraint("length(name) > 0", name="ck_discipline_area_name_non_empty"),
        CheckConstraint("position >= 1 AND position <= 22", name="ck_discipline_area_position"),
    )


class DisciplineModel(Base):
    __tablename__ = "disciplines"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)

    __table_args__ = (
        CheckConstraint("length(name) > 0", name="ck_discipline_name_non_empty"),
        CheckConstraint("length(normalized_name) > 0", name="ck_discipline_normalized_non_empty"),
    )


class DisciplineAreaWeightModel(Base):
    __tablename__ = "discipline_area_weights"

    discipline_id: Mapped[str] = mapped_column(ForeignKey("disciplines.id", ondelete="CASCADE"), primary_key=True)
    area_id: Mapped[str] = mapped_column(ForeignKey("discipline_areas.id"), primary_key=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)

    __table_args__ = (
        CheckConstraint("weight > 0 AND weight <= 1", name="ck_discipline_area_weight_range"),
    )
