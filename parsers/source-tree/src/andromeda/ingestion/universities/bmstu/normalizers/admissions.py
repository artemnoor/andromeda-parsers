"""Normalize BMSTU raw admission rows into public Andromeda contracts."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from typing import TypeVar

from andromeda.modules.admissions.contracts.public import (
    AdmissionCompetitionType,
    AdmissionOffering,
    AdmissionProvenance,
    AdmissionScope,
    ExamRequirement,
    ProgramAdmissions,
    Quota,
    PassingScore,
    PassingScoreStatus,
    TuitionCost,
)
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.errors import ContractError, ErrorCode

from ....contracts.raw import RawAdmissionRecord, RawSourceSnapshot
from ..identity import resolve_programs
from ..mappings.admissions import (
    normalize_currency,
    normalize_competition_type,
    normalize_funding,
    normalize_passing_score,
    normalize_passing_status,
    normalize_quota,
    normalize_study_form,
)


logger = logging.getLogger("andromeda.ingestion.bmstu.normalizers.admissions")
_Child = TypeVar("_Child")


def normalize_admissions(
    records: Iterable[RawAdmissionRecord],
    *,
    programs: Sequence[Program],
    snapshots: Sequence[RawSourceSnapshot],
) -> tuple[ProgramAdmissions, ...]:
    records = tuple(records)
    snapshots_by_url: dict[str, RawSourceSnapshot] = {}
    for snapshot in snapshots:
        snapshots_by_url[str(snapshot.requested_url)] = snapshot
        snapshots_by_url[str(snapshot.final_url)] = snapshot

    grouped: dict[str, dict[tuple[object, ...], AdmissionOffering]] = defaultdict(dict)
    for record in records:
        source_snapshot = snapshots_by_url.get(str(record.source_url))
        if source_snapshot is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Admission source is not captured: {record.source_url}")
        targets = resolve_programs(
            record.program_code,
            source_name=record.program_name,
            scope=record.scope,
            programs=programs,
        )
        provenance = AdmissionProvenance(
            source_kind=record.source_kind,
            source_url=record.source_url,
            captured_at=source_snapshot.captured_at,
            content_sha256=source_snapshot.content_sha256,
            locator=_locator(record),
            university_id="university:bmstu",
            field="admission_offering",
            record_key=record.program_code,
        )
        for program in targets:
            offering = _offering(record, program.id, provenance)
            key = (offering.admission_year, offering.study_form, offering.funding_type, offering.scope)
            current = grouped[program.id].get(key)
            grouped[program.id][key] = _merge(current, offering) if current is not None else offering

    result = tuple(
        ProgramAdmissions(program_id=program_id, offerings=tuple(sorted(offerings.values(), key=lambda item: item.id)))
        for program_id, offerings in sorted(grouped.items())
    )
    logger.info("bmstu_admissions_canonicalized records=%d programs=%d", len(records), len(result))
    return result


def _offering(record: RawAdmissionRecord, program_id: str, provenance: AdmissionProvenance) -> AdmissionOffering:
    form = normalize_study_form(record.study_form)
    funding = normalize_funding(record.funding_type)
    scope = AdmissionScope(record.scope)
    form_key = form.value if form is not None else "unknown"
    funding_key = funding.value if funding is not None else "unknown"
    identifier = f"admission-offering:{program_id}:{record.admission_year}:{form_key}:{funding_key}:{scope.value}"
    child_provenance = provenance
    return AdmissionOffering(
        id=identifier,
        program_id=program_id,
        admission_year=record.admission_year,
        study_form=form,
        funding_type=funding,
        scope=scope,
        places=record.places,
        exams=tuple(
            ExamRequirement(
                subject=item.subject,
                source_name=item.source_name,
                minimum_score=item.minimum_score,
                is_choice=item.is_choice,
                is_required=item.is_required,
                provenance=child_provenance,
            )
            for item in record.exams
        ),
        quotas=tuple(
            Quota(quota_type=normalize_quota(item.quota_type), source_name=item.source_name, places=item.places, provenance=child_provenance)
            for item in record.quotas
        ),
        passing_scores=tuple(
            PassingScore(
                score_type=normalize_passing_score(item.score_type),
                competition_type=normalize_competition_type(item.competition_type, score=item.score),
                status=normalize_passing_status(item.status, score=item.score),
                score=item.score,
                provenance=child_provenance,
            )
            for item in record.passing_scores
        ),
        tuition=tuple(
            TuitionCost(
                amount=item.amount,
                currency=normalize_currency(item.currency),
                academic_year=item.academic_year,
                period=item.period,
                study_form=normalize_study_form(item.study_form),
                is_discounted=item.is_discounted,
                provenance=child_provenance,
            )
            for item in record.tuition
        ),
        provenance=(provenance,),
    )


def _merge(left: AdmissionOffering, right: AdmissionOffering) -> AdmissionOffering:
    return left.model_copy(
        update={
            "places": left.places if left.places is not None else right.places,
            "exams": _unique_children((*left.exams, *right.exams), lambda item: (item.subject, item.source_name)),
            "quotas": _unique_children((*left.quotas, *right.quotas), lambda item: (item.quota_type, item.source_name)),
            "passing_scores": _merge_passing_scores(left.passing_scores, right.passing_scores),
            "tuition": _unique_children((*left.tuition, *right.tuition), lambda item: (item.amount, item.is_discounted, item.study_form)),
            "provenance": _merge_provenance(left.provenance, right.provenance),
        }
    )


def _unique_children(values: tuple[_Child, ...], key: Callable[[_Child], object]) -> tuple[_Child, ...]:
    result: list[_Child] = []
    seen: set[object] = set()
    for value in values:
        marker = key(value)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return tuple(result)


def _merge_passing_scores(left: tuple[PassingScore, ...], right: tuple[PassingScore, ...]) -> tuple[PassingScore, ...]:
    grouped: dict[tuple[object, object, object], list[PassingScore]] = {}
    for value in (*left, *right):
        key = (value.score_type, value.competition_type, value.status)
        grouped.setdefault(key, []).append(value)
    result: list[PassingScore] = []
    for group_key in sorted(grouped, key=lambda item: tuple(str(part) for part in item)):
        candidates = grouped[group_key]
        order_candidates = tuple(item for item in candidates if _is_order_provenance(item))
        selected = order_candidates or tuple(candidates)
        if selected[0].status.value == "numeric":
            result.append(min(selected, key=_numeric_passing_sort_key))
        else:
            result.append(min(selected, key=_passing_provenance_sort_key))
    return tuple(result)


def _merge_provenance(left: tuple[AdmissionProvenance, ...], right: tuple[AdmissionProvenance, ...]) -> tuple[AdmissionProvenance, ...]:
    values = _unique_children(
        (*left, *right),
        lambda item: (item.source_kind, item.content_sha256, item.locator, str(item.source_url)),
    )
    return tuple(sorted(values, key=lambda item: (item.content_sha256, item.locator or "", item.source_kind, str(item.source_url))))


def _is_order_provenance(value: PassingScore) -> bool:
    return value.provenance.source_kind == "bmstu_admission_orders_document"


def _numeric_passing_sort_key(value: PassingScore) -> tuple[Decimal, str, str, str]:
    assert value.score is not None
    return (value.score, value.provenance.content_sha256, value.provenance.locator or "", str(value.provenance.source_url))


def _passing_provenance_sort_key(value: PassingScore) -> tuple[str, str, str]:
    return (value.provenance.content_sha256, value.provenance.locator or "", str(value.provenance.source_url))


def _locator(record: RawAdmissionRecord) -> str | None:
    return record.locator.field or (f"page:{record.locator.page}:row:{record.locator.row}" if record.locator.page or record.locator.row else None)


__all__ = ["normalize_admissions"]
