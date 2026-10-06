"""Deterministic metadata classification for BMSTU admission documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from .capture import AdmissionOrderManifestEntry, parse_orders_manifest
from .pdf import extract_admission_year


class BmstuOrderDocumentKind(StrEnum):
    BACHELOR_SPECIALIST = "bachelor_specialist"
    MASTER = "master"
    POSTGRADUATE = "postgraduate"
    UNKNOWN = "unknown"


class BmstuOrderFunding(StrEnum):
    BUDGET = "budget"
    PAID = "paid"
    UNKNOWN = "unknown"


class BmstuOrderStage(StrEnum):
    MAIN = "main"
    FIRST = "first"
    UNKNOWN = "unknown"


class BmstuOrderCampus(StrEnum):
    MOSCOW = "moscow"
    MYTISHCHI = "mytishchi"
    KALUGA = "kaluga"
    UNKNOWN = "unknown"


class BmstuOrderCompetition(StrEnum):
    GENERAL = "general"
    SPECIAL_QUOTA = "special_quota"
    SEPARATE_QUOTA = "separate_quota"
    TARGETED = "targeted"
    BVI = "bvi"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class BmstuOrderDocumentMetadata:
    manifest_entry: AdmissionOrderManifestEntry
    document_kind: BmstuOrderDocumentKind
    funding: BmstuOrderFunding
    stage: BmstuOrderStage
    campus: BmstuOrderCampus
    admission_year: int | None
    study_form: str | None
    warnings: tuple[str, ...] = ()

    @property
    def supported_catalog(self) -> bool:
        return self.document_kind is BmstuOrderDocumentKind.BACHELOR_SPECIALIST


def classify_order_document(
    manifest_entry: AdmissionOrderManifestEntry,
    pages: Sequence[str],
) -> BmstuOrderDocumentMetadata:
    """Classify one official document using title and extracted page headings."""

    normalized_title = _normalize(manifest_entry.title)
    normalized_pages = tuple(_normalize(page) for page in pages)
    sample = " ".join((normalized_title, *normalized_pages[:2]))
    warnings: list[str] = []
    kind = _document_kind(sample)
    funding = _funding(sample)
    stage = _stage(sample)
    campus = _campus(sample)
    admission_year = _admission_year(normalized_pages)
    study_form = _study_form(sample)
    if kind is BmstuOrderDocumentKind.UNKNOWN:
        warnings.append("education_level_unknown")
    if funding is BmstuOrderFunding.UNKNOWN:
        warnings.append("funding_unknown")
    if admission_year is None:
        warnings.append("admission_year_unknown")
    return BmstuOrderDocumentMetadata(
        manifest_entry=manifest_entry,
        document_kind=kind,
        funding=funding,
        stage=stage,
        campus=campus,
        admission_year=admission_year,
        study_form=study_form,
        warnings=tuple(warnings),
    )


def classify_competition_heading(text: str) -> tuple[BmstuOrderCompetition, str | None]:
    """Map an official section heading to one competition route."""

    normalized = _normalize(text)
    if "без проведения вступительных испытаний" in normalized or "без вступительных испытаний" in normalized:
        return BmstuOrderCompetition.BVI, None
    if "особ" in normalized and "прав" in normalized:
        return BmstuOrderCompetition.SPECIAL_QUOTA, None
    if "отдельн" in normalized and "квот" in normalized:
        return BmstuOrderCompetition.SEPARATE_QUOTA, None
    if "целев" in normalized and "квот" in normalized:
        return BmstuOrderCompetition.TARGETED, None
    if any(anchor in normalized for anchor in ("основн", "договор", "оплатой стоимости")):
        return BmstuOrderCompetition.GENERAL, None
    return BmstuOrderCompetition.OTHER, "competition_heading_unknown"


def _document_kind(text: str) -> BmstuOrderDocumentKind:
    if "магистратур" in text:
        return BmstuOrderDocumentKind.MASTER
    if "аспирантур" in text:
        return BmstuOrderDocumentKind.POSTGRADUATE
    if "бакалавриат" in text or "специалитет" in text:
        return BmstuOrderDocumentKind.BACHELOR_SPECIALIST
    return BmstuOrderDocumentKind.UNKNOWN


def _funding(text: str) -> BmstuOrderFunding:
    if "платн" in text or "оплатой стоимости" in text:
        return BmstuOrderFunding.PAID
    if "бюджет" in text:
        return BmstuOrderFunding.BUDGET
    return BmstuOrderFunding.UNKNOWN


def _stage(text: str) -> BmstuOrderStage:
    if "основн" in text:
        return BmstuOrderStage.MAIN
    if "перв" in text or "квот" in text or "бви" in text:
        return BmstuOrderStage.FIRST
    return BmstuOrderStage.UNKNOWN


def _campus(text: str) -> BmstuOrderCampus:
    if "мытищ" in text:
        return BmstuOrderCampus.MYTISHCHI
    if "калуж" in text:
        return BmstuOrderCampus.KALUGA
    if "москв" in text:
        return BmstuOrderCampus.MOSCOW
    return BmstuOrderCampus.UNKNOWN


def _admission_year(pages: Sequence[str]) -> int | None:
    for page in pages[:3]:
        year = extract_admission_year(page)
        if year is not None:
            return year
    return None


def _study_form(text: str) -> str | None:
    if "очно заочн" in text:
        return "evening"
    if "заочн" in text:
        return "part_time"
    if "очн" in text:
        return "full_time"
    return None


def _normalize(value: str) -> str:
    value = value.replace("ё", "е").replace("Ё", "Е").replace("\xa0", " ")
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    return re.sub(r"\s+", " ", value.casefold()).strip()


__all__ = [
    "AdmissionOrderManifestEntry",
    "BmstuOrderCampus",
    "BmstuOrderCompetition",
    "BmstuOrderDocumentKind",
    "BmstuOrderDocumentMetadata",
    "BmstuOrderFunding",
    "BmstuOrderStage",
    "classify_competition_heading",
    "classify_order_document",
    "parse_orders_manifest",
]
