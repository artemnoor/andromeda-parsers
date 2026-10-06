from __future__ import annotations

from ....shared.contracts.base import ContractModel
from ....shared.contracts.enums import AssessmentType
from ....shared.contracts.ids import Credits, HourCount, Semester


class Workload(ContractModel):
    semester: Semester | None = None
    hours: HourCount
    credits: Credits | None = None
    assessment_types: tuple[AssessmentType, ...] | None = None


__all__ = ["Workload"]
