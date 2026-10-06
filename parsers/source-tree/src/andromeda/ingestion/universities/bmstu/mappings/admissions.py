from __future__ import annotations

import logging
import re

from decimal import Decimal

from andromeda.modules.admissions.contracts.public import (
    AdmissionCompetitionType,
    FundingType,
    PassingScoreStatus,
    PassingScoreType,
    QuotaType,
    StudyForm,
)


logger = logging.getLogger("andromeda.ingestion.bmstu.mappings.admissions")


def normalize_study_form(value: str | None) -> StudyForm | None:
    if not value:
        return None
    text = " ".join(value.casefold().replace("ё", "е").split())
    canonical = {
        "full_time": StudyForm.FULL_TIME,
        "full-time": StudyForm.FULL_TIME,
        "part_time": StudyForm.PART_TIME,
        "part-time": StudyForm.PART_TIME,
        "evening": StudyForm.EVENING,
        "online": StudyForm.ONLINE,
    }.get(text)
    if canonical is not None:
        logger.debug("[FIX:admission-form] normalized source=%r result=%s", value, canonical.value)
        return canonical
    if "очно-заоч" in text or "очно заоч" in text or "вечер" in text:
        logger.debug("[FIX:admission-form] normalized source=%r result=%s", value, StudyForm.EVENING.value)
        return StudyForm.EVENING
    if "заоч" in text:
        logger.debug("[FIX:admission-form] normalized source=%r result=%s", value, StudyForm.PART_TIME.value)
        return StudyForm.PART_TIME
    if "очн" in text:
        logger.debug("[FIX:admission-form] normalized source=%r result=%s", value, StudyForm.FULL_TIME.value)
        return StudyForm.FULL_TIME
    if "дистан" in text or "онлайн" in text:
        logger.debug("[FIX:admission-form] normalized source=%r result=%s", value, StudyForm.ONLINE.value)
        return StudyForm.ONLINE
    logger.debug("[FIX:admission-form] normalized source=%r result=unknown", value)
    return None


def normalize_funding(value: str | None) -> FundingType | None:
    if not value:
        return None
    text = value.casefold()
    if "бюдж" in text or "кцп" in text or text == FundingType.BUDGET.value:
        return FundingType.BUDGET
    if "плат" in text or "контракт" in text or text == FundingType.PAID.value:
        return FundingType.PAID
    if "целев" in text or text == FundingType.TARGETED.value:
        return FundingType.TARGETED
    return None


def normalize_quota(value: str) -> QuotaType:
    text = value.casefold().replace("ё", "е")
    if "отдель" in text:
        return QuotaType.SEPARATE
    if "особ" in text or "спец" in text:
        return QuotaType.SPECIAL
    if "целев" in text:
        return QuotaType.TARGETED
    return QuotaType.OTHER


def normalize_passing_score(value: str) -> PassingScoreType:
    text = value.casefold().replace("ё", "е")
    if "бюдж" in text or text == PassingScoreType.BUDGET.value:
        return PassingScoreType.BUDGET
    if "плат" in text or "контракт" in text or text == PassingScoreType.PAID.value:
        return PassingScoreType.PAID
    if "сред" in text or text == PassingScoreType.AVERAGE.value:
        return PassingScoreType.AVERAGE
    return PassingScoreType.OTHER


def normalize_competition_type(value: str, *, score: Decimal | None) -> AdmissionCompetitionType:
    text = value.casefold().replace("ё", "е").strip()
    try:
        return AdmissionCompetitionType(text)
    except ValueError:
        if score is None:
            raise ValueError(f"unknown competition type for a score without a numeric value: {value}") from None
        return AdmissionCompetitionType.OTHER


def normalize_passing_status(value: str, *, score: Decimal | None) -> PassingScoreStatus:
    text = value.casefold().replace("ё", "е").strip()
    try:
        return PassingScoreStatus(text)
    except ValueError:
        return PassingScoreStatus.NUMERIC if score is not None else PassingScoreStatus.BVI


def normalize_currency(value: str) -> str:
    text = value.strip()
    return "RUB" if text in {"₽", "руб", "руб.", "р"} else text.upper()


def normalize_code(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("–", "-").replace("—", "-"))


__all__ = [
    "normalize_code",
    "normalize_competition_type",
    "normalize_currency",
    "normalize_funding",
    "normalize_passing_score",
    "normalize_passing_status",
    "normalize_quota",
    "normalize_study_form",
]
