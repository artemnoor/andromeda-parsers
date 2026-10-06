from __future__ import annotations

from andromeda.shared.contracts.enums import AssessmentType


ASSESSMENT_MAPPING: dict[str, tuple[AssessmentType, ...]] = {
    "экз": (AssessmentType.EXAM,),
    "рэкз": (AssessmentType.EXAM,),
    "зчт": (AssessmentType.CREDIT,),
    "дзчт": (AssessmentType.GRADED_CREDIT,),
    "кур": (AssessmentType.COURSEWORK,),
    "куп": (AssessmentType.COURSE_PROJECT,),
    "гэк": (AssessmentType.STATE_EXAM,),
    "экз кур": (AssessmentType.EXAM, AssessmentType.COURSEWORK),
}


def assessment_types(value: str | None) -> tuple[AssessmentType, ...] | None:
    if not value or not value.strip():
        return None
    key = " ".join(value.casefold().split())
    try:
        return ASSESSMENT_MAPPING[key]
    except KeyError as exc:
        raise ValueError("unsupported assessment mark") from exc
