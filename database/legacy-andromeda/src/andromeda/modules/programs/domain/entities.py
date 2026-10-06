from __future__ import annotations

from typing import Self
import logging

from pydantic import HttpUrl, model_validator

from ....shared.contracts.base import ContractModel
from ....shared.contracts.ids import DirectionId, EducationYear, NonEmptyText, ProgramCode, ProgramId
from ....shared.contracts.provenance import SourceAttribution, SourceGapReference


logger = logging.getLogger("andromeda.contracts.validation")


class Program(ContractModel):
    id: ProgramId
    direction_id: DirectionId
    code: ProgramCode
    name: NonEmptyText
    education_year: EducationYear
    study_plan_url: HttpUrl
    source_url: HttpUrl
    provenance: tuple[SourceAttribution, ...] = ()
    source_gaps: tuple[SourceGapReference, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        university_slug = self.direction_id.removeprefix("direction:").split(":", 1)[0] if self.direction_id.count(":") == 2 else None
        expected = f"program:{university_slug}:{self.code}" if university_slug else f"program:{self.code}"
        legacy = f"program:{self.code}"
        if self.id not in {expected, legacy}:
            logger.error("contract_semantic_violation model=Program field=id")
            raise ValueError("program id must equal program:<university>:<code>")
        direction_code = self.direction_id.rsplit(":", 1)[-1]
        if not self.code.startswith(direction_code + "-"):
            logger.error("contract_semantic_violation model=Program field=direction_id")
            raise ValueError("program code must belong to its direction")
        return self


__all__ = ["Program"]
