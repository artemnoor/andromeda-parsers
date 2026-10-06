from __future__ import annotations

from datetime import datetime
import logging
from typing import Self

from pydantic import Field, HttpUrl, model_validator

from ....shared.contracts.base import ContractModel
from ....shared.contracts.enums import AssessmentType
from ....shared.contracts.ids import Credits, CurriculumId, CurriculumItemId, DisciplineId, EducationYear, HourCount, ProgramId, Semester, SourcePosition
from ....shared.contracts.provenance import SourceAttribution, SourceGapReference


logger = logging.getLogger("andromeda.contracts.validation")


class CurriculumItem(ContractModel):
    id: CurriculumItemId
    discipline_id: DisciplineId
    source_name: str = Field(min_length=1, max_length=256)
    semester: Semester | None = None
    hours: HourCount
    credits: Credits | None = None
    assessment_types: tuple[AssessmentType, ...] | None = None
    source_position: SourcePosition | None = None

    @model_validator(mode="after")
    def validate_item(self) -> Self:
        expected_suffix = f":{self.discipline_id}:{self.semester if self.semester is not None else 'unassigned'}"
        if not self.id.startswith("curriculum-item:program:") or not self.id.endswith(expected_suffix):
            logger.error("contract_semantic_violation model=CurriculumItem field=id")
            raise ValueError("curriculum item id must derive from its discipline and semester")
        if self.assessment_types is not None and not self.assessment_types:
            logger.error("contract_semantic_violation model=CurriculumItem field=assessment_types")
            raise ValueError("assessment_types must be non-empty when present")
        if self.assessment_types is not None and len(set(self.assessment_types)) != len(self.assessment_types):
            logger.error("contract_semantic_violation model=CurriculumItem field=assessment_types")
            raise ValueError("assessment_types must not contain duplicates")
        return self


class Curriculum(ContractModel):
    id: CurriculumId
    program_id: ProgramId
    education_year: EducationYear
    source_url: HttpUrl
    captured_at: datetime
    items: tuple[CurriculumItem, ...] = Field(min_length=1)
    provenance: tuple[SourceAttribution, ...] = ()
    source_gaps: tuple[SourceGapReference, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        program_identity = self.program_id.removeprefix("program:")
        expected = f"curriculum:{program_identity}-{self.education_year}"
        legacy = f"curriculum:{program_identity.split(':', 1)[-1]}-{self.education_year}"
        if self.id not in {expected, legacy}:
            logger.error("contract_semantic_violation model=Curriculum field=id")
            raise ValueError("curriculum id must derive from program and education year")
        identities = [(item.discipline_id, item.semester) for item in self.items]
        if len(identities) != len(set(identities)):
            logger.error("contract_semantic_violation model=Curriculum field=items")
            raise ValueError("curriculum cannot contain duplicate discipline/semester items")
        return self


__all__ = ["Curriculum", "CurriculumItem"]
