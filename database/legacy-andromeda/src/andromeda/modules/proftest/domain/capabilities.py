"""Source-backed capability declarations for proftest signals."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel


class ProgramSignal(StrEnum):
    AREA_SHARE = "area_share"
    ACTIVITY_SIGNALS = "activity_signals"
    SEMESTER_LOAD = "semester_distribution"
    ASSESSMENT_TYPES = "assessment_types"
    LECTURE_HOURS = "lecture_hours"
    LAB_HOURS = "lab_hours"
    PRACTICE_HOURS = "practice_hours"


class SourceCapability(ContractModel):
    signal: ProgramSignal
    supported: bool
    evidence_fields: tuple[str, ...] = Field(default=(), max_length=8)
    gap_code: str | None = Field(default=None, min_length=1, max_length=96)

    @classmethod
    def supported_signal(cls, signal: ProgramSignal, *evidence_fields: str) -> "SourceCapability":
        return cls(signal=signal, supported=True, evidence_fields=tuple(evidence_fields))

    @classmethod
    def unsupported_signal(cls, signal: ProgramSignal, gap_code: str) -> "SourceCapability":
        return cls(signal=signal, supported=False, gap_code=gap_code)


def source_capabilities() -> tuple[SourceCapability, ...]:
    """Return the deterministic signal inventory for the current canonical data."""

    return (
        SourceCapability.supported_signal(ProgramSignal.AREA_SHARE, "CurriculumItem.area_weights"),
        SourceCapability.supported_signal(ProgramSignal.ACTIVITY_SIGNALS, "ProgramFingerprint.activity_signals"),
        SourceCapability.supported_signal(ProgramSignal.SEMESTER_LOAD, "CurriculumItem.semester", "CurriculumItem.hours"),
        SourceCapability.supported_signal(ProgramSignal.ASSESSMENT_TYPES, "CurriculumItem.assessment_types"),
        SourceCapability.unsupported_signal(ProgramSignal.LECTURE_HOURS, "missing_lecture_hour_breakdown"),
        SourceCapability.unsupported_signal(ProgramSignal.LAB_HOURS, "missing_lab_hour_breakdown"),
        SourceCapability.unsupported_signal(ProgramSignal.PRACTICE_HOURS, "missing_practice_hour_breakdown"),
    )


__all__ = ["ProgramSignal", "SourceCapability", "source_capabilities"]
