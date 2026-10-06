from __future__ import annotations

from pydantic import HttpUrl, model_validator
from typing import Self
import logging

from ....shared.contracts.base import ContractModel
from ....shared.contracts.ids import DirectionCode, DirectionId, NonEmptyText, ShortText, UniversityId
from ....shared.contracts.enums import EducationLevel


logger = logging.getLogger("andromeda.contracts.validation")


class University(ContractModel):
    id: UniversityId
    name: NonEmptyText
    city: ShortText
    official_site: HttpUrl
    address: NonEmptyText


class Direction(ContractModel):
    id: DirectionId
    university_id: UniversityId
    code: DirectionCode
    name: NonEmptyText
    education_level: EducationLevel

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = f"direction:{self.university_id.removeprefix('university:')}:{self.code}"
        legacy = f"direction:{self.code}"
        if self.id not in {expected, legacy}:
            logger.error("contract_semantic_violation model=Direction field=id")
            raise ValueError("direction id must equal direction:<university>:<code>")
        return self


__all__ = ["Direction", "University"]
