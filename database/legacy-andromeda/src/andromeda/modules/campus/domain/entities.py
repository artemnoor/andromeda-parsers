"""Map-agnostic campus read projections.

The point identity is deliberately the existing ``VenueId``.  These models
describe the data a future map consumer may read; they do not describe a map
scene, visual placement, or a route graph.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, HttpUrl, model_validator

from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.universities.contracts.public import University
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    DepartmentId,
    DirectionId,
    EducationYear,
    NonEmptyText,
    ProgramCode,
    ProgramId,
    ShortText,
    UniversityId,
    VenueId,
)
from andromeda.shared.contracts.provenance import SourceAttribution


logger = logging.getLogger("andromeda.contracts.validation")


class CampusPointType(StrEnum):
    """Stable semantic categories understood by external campus consumers."""

    BUILDING = "building"
    ROOM_ZONE = "room_zone"
    EVENT_VENUE = "event_venue"
    ENTRANCE = "entrance"
    OTHER = "other"


class CampusUniversityReference(ContractModel):
    """Card-safe projection of the existing university contract."""

    id: UniversityId
    name: NonEmptyText
    city: ShortText
    address: NonEmptyText
    official_site: HttpUrl

    @classmethod
    def from_contract(cls, university: University) -> "CampusUniversityReference":
        return cls.model_validate(university.model_dump(mode="python"))


class CampusProgramReference(ContractModel):
    """Card-safe projection of the existing program contract."""

    id: ProgramId
    direction_id: DirectionId
    code: ProgramCode
    name: NonEmptyText
    education_year: EducationYear
    study_plan_url: HttpUrl
    source_url: HttpUrl

    @classmethod
    def from_contract(cls, program: Program) -> "CampusProgramReference":
        return cls.model_validate(program.model_dump(mode="python"))


class CampusDepartmentReference(ContractModel):
    """Canonical department reference; department is not duplicated here."""

    id: DepartmentId


class CampusPoint(ContractModel):
    """A physical university point projected from the existing venue storage."""

    id: VenueId
    point_type: CampusPointType
    name: NonEmptyText
    address: NonEmptyText | None = None
    latitude: Decimal | None = Field(
        default=None,
        strict=True,
        ge=Decimal("-90"),
        le=Decimal("90"),
        max_digits=9,
        decimal_places=6,
    )
    longitude: Decimal | None = Field(
        default=None,
        strict=True,
        ge=Decimal("-180"),
        le=Decimal("180"),
        max_digits=9,
        decimal_places=6,
    )
    university_ids: tuple[UniversityId, ...] = Field(min_length=1)
    department_ids: tuple[DepartmentId, ...] = ()
    program_ids: tuple[ProgramId, ...] = ()
    event_count: int = Field(default=0, strict=True, ge=0)
    provenance: tuple[SourceAttribution, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            logger.error("contract_semantic_violation model=CampusPoint field=coordinates id=%s", self.id)
            raise ValueError("campus point latitude and longitude must be provided together")
        for field_name, values in (
            ("university_ids", self.university_ids),
            ("department_ids", self.department_ids),
            ("program_ids", self.program_ids),
        ):
            if len(values) != len(set(values)):
                logger.error("contract_semantic_violation model=CampusPoint field=%s id=%s", field_name, self.id)
                raise ValueError(f"campus point {field_name} must contain unique canonical IDs")
        if not any(
            self.id.startswith(f"venue:{university.removeprefix('university:')}:")
            for university in self.university_ids
        ):
            logger.error("contract_semantic_violation model=CampusPoint field=id id=%s", self.id)
            raise ValueError("campus point id must belong to one of its university IDs")
        return self


class CampusPointDetail(CampusPoint):
    """Point data plus existing catalog references needed for a selection card."""

    universities: tuple[CampusUniversityReference, ...] = ()
    departments: tuple[CampusDepartmentReference, ...] = ()
    programs: tuple[CampusProgramReference, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        university_ids = {item.id for item in self.universities}
        program_ids = {item.id for item in self.programs}
        department_ids = {item.id for item in self.departments}
        if university_ids != set(self.university_ids):
            logger.error("contract_semantic_violation model=CampusPointDetail field=universities id=%s", self.id)
            raise ValueError("point detail university references must match university_ids")
        if program_ids != set(self.program_ids):
            logger.error("contract_semantic_violation model=CampusPointDetail field=programs id=%s", self.id)
            raise ValueError("point detail program references must match program_ids")
        if department_ids != set(self.department_ids):
            logger.error("contract_semantic_violation model=CampusPointDetail field=departments id=%s", self.id)
            raise ValueError("point detail department references must match department_ids")
        return self


__all__ = [
    "CampusDepartmentReference",
    "CampusPoint",
    "CampusPointDetail",
    "CampusPointType",
    "CampusProgramReference",
    "CampusUniversityReference",
]
