"""Conservative identity resolution for admission exam subjects."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import unicodedata
from enum import StrEnum


logger = logging.getLogger("andromeda.admission_fit.subject_identity")


class SubjectResolutionStatus(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class SubjectResolution:
    input_subject: str
    normalized_subject: str
    status: SubjectResolutionStatus
    matched_subject: str | None = None
    candidates: tuple[str, ...] = ()


# These are explicit aliases only. There is deliberately no fuzzy matching.
_ALIASES: dict[str, str] = {
    "русский": "русский язык",
    "математика профиль": "математика",
    "математика профильный уровень": "математика",
    "иностранный": "иностранный язык",
    "английский": "иностранный язык",
    "информатика": "информатика и информационно коммуникационные технологии",
    "информатика и икт": "информатика и информационно коммуникационные технологии",
}


def normalize_subject_name(value: str) -> str:
    """Normalize typography while preserving the semantic words."""

    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def canonical_subject_key(value: str) -> str:
    normalized = normalize_subject_name(value)
    return _ALIASES.get(normalized, normalized)


def resolve_subject(input_subject: str, available_subjects: tuple[str, ...]) -> SubjectResolution:
    """Resolve only an exact normalized/explicit-alias match."""

    key = canonical_subject_key(input_subject)
    candidates = tuple(subject for subject in available_subjects if canonical_subject_key(subject) == key)
    if len(candidates) == 1:
        result = SubjectResolution(
            input_subject=input_subject,
            normalized_subject=key,
            status=SubjectResolutionStatus.MATCHED,
            matched_subject=candidates[0],
        )
        logger.debug("subject_identity_resolved normalized_key=%s candidate_count=1", key)
        return result
    if not candidates:
        logger.warning("subject_identity_missing normalized_key=%s", key)
        return SubjectResolution(input_subject=input_subject, normalized_subject=key, status=SubjectResolutionStatus.MISSING)
    logger.warning("subject_identity_ambiguous normalized_key=%s candidate_count=%d", key, len(candidates))
    return SubjectResolution(
        input_subject=input_subject,
        normalized_subject=key,
        status=SubjectResolutionStatus.AMBIGUOUS,
        candidates=candidates,
    )


__all__ = [
    "SubjectResolution",
    "SubjectResolutionStatus",
    "canonical_subject_key",
    "normalize_subject_name",
    "resolve_subject",
]
