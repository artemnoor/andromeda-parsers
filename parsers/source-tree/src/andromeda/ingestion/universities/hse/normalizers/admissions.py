from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from typing import TypeVar

from andromeda.ingestion.contracts.raw import RawAdmissionRecord, RawSourceSnapshot
from andromeda.modules.admissions.contracts.public import AdmissionCompetitionType, AdmissionOffering, AdmissionProvenance, AdmissionScope, ExamRequirement, FundingType, PassingScoreType, ProgramAdmissions, Quota, QuotaType, PassingScore, PassingScoreStatus, StudyForm, TuitionCost
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.errors import ContractError, ErrorCode

from ..identity import resolve_program


_Child = TypeVar("_Child")


def normalize_admissions(records: Iterable[RawAdmissionRecord], *, programs: Sequence[Program], snapshots: Sequence[RawSourceSnapshot]) -> tuple[ProgramAdmissions, ...]:
    by_url = {str(value.requested_url): value for value in snapshots} | {str(value.final_url): value for value in snapshots}
    grouped: dict[str, dict[tuple[object, ...], AdmissionOffering]] = defaultdict(dict)
    for record in records:
        snapshot = by_url.get(str(record.source_url))
        if snapshot is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"HSE admission source is not captured: {record.source_url}")
        program = resolve_program(record.program_code, record.program_name, programs)
        if program is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"HSE admission row has unknown program: {record.program_code}/{record.program_name}")
        provenance = AdmissionProvenance(source_kind=record.source_kind, source_url=record.source_url, captured_at=snapshot.captured_at, content_sha256=snapshot.content_sha256, locator=_locator(record), university_id="university:hse", field="admission_offering", record_key=record.program_code)
        offering = _offering(record, program.id, provenance)
        key = (offering.admission_year, offering.study_form, offering.funding_type, offering.scope)
        current = grouped[program.id].get(key)
        grouped[program.id][key] = _merge(current, offering) if current is not None else offering
    return tuple(ProgramAdmissions(program_id=program_id, offerings=tuple(sorted(values.values(), key=lambda value: value.id))) for program_id, values in sorted(grouped.items()))


def _offering(record: RawAdmissionRecord, program_id: str, provenance: AdmissionProvenance) -> AdmissionOffering:
    form_key = record.study_form or "unknown"
    funding_key = record.funding_type or "unknown"
    return AdmissionOffering(
        id=f"admission-offering:{program_id}:{record.admission_year}:{form_key}:{funding_key}:{record.scope}",
        program_id=program_id,
        admission_year=record.admission_year,
        study_form=_study_form(record.study_form),
        funding_type=_funding(record.funding_type),
        scope=AdmissionScope(record.scope),
        places=record.places,
        exams=tuple(ExamRequirement(subject=item.subject, source_name=item.source_name, minimum_score=item.minimum_score, is_choice=item.is_choice, is_required=item.is_required, provenance=provenance) for item in record.exams),
        quotas=tuple(Quota(quota_type=_quota(item.quota_type), source_name=item.source_name, places=item.places, provenance=provenance) for item in record.quotas),
        passing_scores=tuple(PassingScore(score_type=_score_type(item.score_type), competition_type=_competition(item.competition_type), status=PassingScoreStatus(item.status), score=item.score, provenance=provenance) for item in record.passing_scores),
        tuition=tuple(TuitionCost(amount=item.amount, currency="RUB" if item.currency.casefold() in {"руб", "руб.", "₽"} else item.currency.upper(), academic_year=item.academic_year, period=item.period, study_form=_study_form(item.study_form), is_discounted=item.is_discounted, provenance=provenance) for item in record.tuition),
        provenance=(provenance,),
    )


def _merge(left: AdmissionOffering, right: AdmissionOffering) -> AdmissionOffering:
    return left.model_copy(update={"places": left.places if left.places is not None else right.places, "exams": _unique((*left.exams, *right.exams), lambda item: (item.subject, item.source_name)), "quotas": _unique((*left.quotas, *right.quotas), lambda item: (item.quota_type, item.source_name)), "passing_scores": _merge_scores((*left.passing_scores, *right.passing_scores)), "tuition": _unique((*left.tuition, *right.tuition), lambda item: (item.amount, item.study_form)), "provenance": _unique((*left.provenance, *right.provenance), lambda item: (item.source_kind, item.content_sha256, str(item.source_url)))})


def _unique(values: tuple[_Child, ...], key: Callable[[_Child], object]) -> tuple[_Child, ...]:
    result: list[_Child] = []
    seen: set[object] = set()
    for value in values:
        marker = key(value)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return tuple(result)


def _merge_scores(values: tuple[PassingScore, ...]) -> tuple[PassingScore, ...]:
    groups: dict[tuple[object, object, object], list[PassingScore]] = defaultdict(list)
    for value in values:
        groups[(value.score_type, value.competition_type, value.status)].append(value)
    result: list[PassingScore] = []
    for candidates in groups.values():
        if candidates[0].status is PassingScoreStatus.NUMERIC:
            result.append(min(candidates, key=lambda value: (value.score or Decimal("999"), value.provenance.content_sha256)))
        else:
            result.append(candidates[0])
    return tuple(result)


def _study_form(value: str | None) -> StudyForm | None:
    if not value:
        return None
    text = value.casefold()
    if "очно" in text or value == "full_time":
        return StudyForm.FULL_TIME
    if "заоч" in text or value == "part_time":
        return StudyForm.PART_TIME
    if "онлайн" in text or value == "online":
        return StudyForm.ONLINE
    return None


def _funding(value: str | None) -> FundingType | None:
    if value == "budget":
        return FundingType.BUDGET
    if value == "paid":
        return FundingType.PAID
    if value == "targeted":
        return FundingType.TARGETED
    return None


def _quota(value: str) -> QuotaType:
    return {"special": QuotaType.SPECIAL, "separate": QuotaType.SEPARATE, "targeted": QuotaType.TARGETED}.get(value, QuotaType.OTHER)


def _score_type(value: str) -> PassingScoreType:
    return PassingScoreType.PAID if value == "paid" else PassingScoreType.BUDGET


def _competition(value: str) -> AdmissionCompetitionType:
    try:
        return AdmissionCompetitionType(value)
    except ValueError:
        return AdmissionCompetitionType.OTHER


def _locator(record: RawAdmissionRecord) -> str | None:
    return record.locator.field or (f"page:{record.locator.page}:row:{record.locator.row}" if record.locator.page or record.locator.row else None)


__all__ = ["normalize_admissions"]
