from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, HttpUrl, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import DepartmentId, EventId, NonEmptyText, ProgramId, UniversityId, VenueId
from andromeda.shared.contracts.provenance import SourceAttribution


logger = logging.getLogger("andromeda.contracts.validation")


class EventKind(StrEnum):
    ADDITIONAL_EDUCATION = "additional_education"
    OPEN_DAY = "open_day"
    LECTURE = "lecture"
    COMPETITION = "competition"
    CAREER = "career"
    OTHER = "other"


class EventFormat(StrEnum):
    OFFLINE = "offline"
    ONLINE = "online"
    HYBRID = "hybrid"


class Venue(ContractModel):
    id: VenueId
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

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            logger.error("contract_semantic_violation model=Venue field=coordinates id=%s", self.id)
            raise ValueError("venue latitude and longitude must be provided together")
        return self


class Event(ContractModel):
    id: EventId
    title: NonEmptyText
    kind: EventKind
    format: EventFormat
    starts_at: datetime
    ends_at: datetime | None = None
    description: str | None = Field(default=None, min_length=1, max_length=10_000)
    registration_url: HttpUrl | None = None
    university_ids: tuple[UniversityId, ...] = Field(min_length=1)
    department_ids: tuple[DepartmentId, ...] = ()
    program_ids: tuple[ProgramId, ...] = ()
    venue: Venue | None = None
    provenance: tuple[SourceAttribution, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            logger.error("contract_semantic_violation model=Event field=starts_at id=%s", self.id)
            raise ValueError("event starts_at must be timezone-aware")
        if self.ends_at is not None:
            if self.ends_at.tzinfo is None or self.ends_at.utcoffset() is None:
                logger.error("contract_semantic_violation model=Event field=ends_at id=%s", self.id)
                raise ValueError("event ends_at must be timezone-aware")
            if self.ends_at <= self.starts_at:
                logger.error("contract_semantic_violation model=Event field=ends_at id=%s", self.id)
                raise ValueError("event ends_at must be after starts_at")
        for field_name, values in (
            ("university_ids", self.university_ids),
            ("department_ids", self.department_ids),
            ("program_ids", self.program_ids),
        ):
            if len(values) != len(set(values)):
                logger.error("contract_semantic_violation model=Event field=%s id=%s", field_name, self.id)
                raise ValueError(f"event {field_name} must contain unique canonical IDs")
        if self.venue is not None and not any(
            self.venue.id.startswith(f"venue:{university.removeprefix('university:')}:")
            for university in self.university_ids
        ):
            logger.error("contract_semantic_violation model=Event field=venue id=%s", self.id)
            raise ValueError("venue must belong to one of the event universities")
        return self


__all__ = ["Event", "EventFormat", "EventKind", "Venue"]
