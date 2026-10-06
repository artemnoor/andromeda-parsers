from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import logging
import unicodedata

from andromeda.ingestion.contracts.normalized import CanonicalSnapshot
from andromeda.ingestion.contracts.raw import RawTracerBundle
from andromeda.ingestion.contracts.source import source_gap_reference
from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.universities.contracts.public import Direction, University
from andromeda.shared.contracts.enums import AssessmentType, EducationLevel, SourceKind
from andromeda.shared.contracts.errors import ContractError, ErrorCode, ErrorDetail
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference

from ..identity import direction_codes


logger = logging.getLogger("andromeda.ingestion.hse.normalize")


def normalize_bundle(raw: RawTracerBundle) -> CanonicalSnapshot:
    university = University(id="university:hse", name=_text(raw.university.name), city=_text(raw.university.city), official_site=raw.university.official_site, address=_text(raw.university.address))
    raw_directions = raw.directions or (raw.direction,)
    directions: list[Direction] = []
    seen: set[str] = set()
    for raw_direction in raw_directions:
        for code in direction_codes(raw_direction.code) or (raw_direction.code,):
            if code in seen:
                continue
            seen.add(code)
            directions.append(Direction(id=f"direction:{university.id.removeprefix('university:')}:{code}", university_id=university.id, code=code, name=_text(raw_direction.name), education_level=_level(raw_direction.education_level)))
    if not directions:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "HSE source has no canonical directions")
    direction = directions[0]
    directions_by_code = {item.code: item for item in directions}
    programs = tuple(
        Program(id=f"program:{university.id.removeprefix('university:')}:{_code(item.code)}", direction_id=f"direction:{university.id.removeprefix('university:')}:{_program_direction(item, directions_by_code, direction.code)}", code=_code(item.code), name=_text(item.name), education_year=item.education_year, study_plan_url=item.study_plan_url, source_url=item.source_url, provenance=_source_attribution(raw, str(item.source_url), ("hse_program_detail", "hse_program_catalog"), field="program", record_key=_code(item.code)), source_gaps=_source_gaps(raw, _code(item.code), str(item.source_url), field="program"))
        for item in raw.programs
    )
    if len({item.code for item in programs}) != len(programs):
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Duplicate HSE canonical program code")
    programs_by_code = {item.code: item for item in programs}
    items_by_program: dict[str, list[CurriculumItem]] = {item.code: [] for item in programs}
    disciplines: dict[str, Discipline] = {}
    for row in raw.curriculum_rows:
        program_code = _code(row.program_code)
        program = programs_by_code.get(program_code)
        if program is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"HSE curriculum row points to unknown program {program_code}")
        normalized_name = unicodedata.normalize("NFKC", " ".join(_text(row.discipline).casefold().split()))
        discipline_id = f"discipline:{sha256(normalized_name.encode('utf-8')).hexdigest()[:16]}"
        disciplines.setdefault(discipline_id, Discipline(id=discipline_id, name=_text(row.discipline), normalized_name=normalized_name))
        semester_key = str(row.semester) if row.semester is not None else "unassigned"
        item = CurriculumItem(id=f"curriculum-item:{program.id}:{discipline_id}:{semester_key}", discipline_id=discipline_id, source_name=_text(row.discipline), semester=row.semester, hours=row.hours, credits=_credits(row.credits, row.locator.field or "credits"), assessment_types=_assessment(row.assessment), source_position=row.source_position)
        _append(items_by_program[program.code], item)
    curricula = tuple(
        Curriculum(id=f"curriculum:{program.id.removeprefix('program:')}-{program.education_year}", program_id=program.id, education_year=program.education_year, source_url=program.study_plan_url, captured_at=_captured_at(raw, program), items=tuple(items_by_program[program.code]), provenance=_source_attribution(raw, str(program.study_plan_url), ("hse_curriculum_document", "hse_curriculum_index"), field="curriculum", record_key=program.id), source_gaps=_source_gaps(raw, program.code, str(program.study_plan_url), field="curriculum"))
        for program in programs
        if items_by_program[program.code]
    )
    sources = tuple(SourceAttribution(kind=_source_kind(snapshot.source_kind), url=snapshot.requested_url, captured_at=snapshot.captured_at, content_sha256=snapshot.content_sha256) for snapshot in raw.snapshots)
    result = CanonicalSnapshot(university=university, direction=direction, programs=programs, disciplines=tuple(disciplines.values()), curricula=curricula, sources=sources, directions=tuple(directions), source_gaps=tuple(raw.source_gaps))
    logger.info("stage=canonical_complete university=hse programs=%d directions=%d disciplines=%d curricula=%d items=%d gaps=%d", len(programs), len(directions), len(disciplines), len(curricula), sum(len(value.items) for value in curricula), len(raw.source_gaps))
    return result


def _append(items: list[CurriculumItem], item: CurriculumItem) -> None:
    for index, current in enumerate(items):
        if (current.discipline_id, current.semester) != (item.discipline_id, item.semester):
            continue
        items[index] = current.model_copy(update={"hours": max(current.hours, item.hours), "credits": current.credits if current.credits is not None else item.credits, "source_position": min(value for value in (current.source_position, item.source_position) if value is not None) if current.source_position is not None or item.source_position is not None else None})
        return
    items.append(item)


def _text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value.replace("\xa0", " "))
    value = " ".join(value.strip().split())
    if not value:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Required HSE source text is empty")
    return value


def _code(value: str) -> str:
    return _text(value).replace("–", "-").replace("—", "-").replace(" ", "")


def _level(value: str) -> EducationLevel:
    key = _text(value).casefold()
    if "специал" in key:
        return EducationLevel.SPECIALIST
    if "магистр" in key:
        return EducationLevel.MASTER
    return EducationLevel.BACHELOR


def _program_direction(program: object, directions: dict[str, Direction], fallback: str) -> str:
    raw = getattr(program, "direction_code", "")
    candidates = direction_codes(raw) if isinstance(raw, str) else ()
    return next((candidate for candidate in candidates if candidate in directions), fallback)


def _credits(value: str | float | int | None, path: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "HSE credits value is not numeric", (ErrorDetail(path=path, message="numeric value expected", type="source_value"),)) from exc


def _assessment(value: str | None) -> tuple[AssessmentType, ...] | None:
    if not value:
        return None
    key = value.casefold()
    if "экз" in key:
        return (AssessmentType.EXAM,)
    if "зач" in key:
        return (AssessmentType.CREDIT,)
    return None


def _source_kind(value: str) -> SourceKind:
    try:
        return SourceKind(value)
    except ValueError as exc:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Unknown HSE source kind: {value}") from exc


def _source_attribution(
    raw: RawTracerBundle,
    source_url: str,
    source_kinds: tuple[str, ...],
    *,
    field: str,
    record_key: str,
) -> tuple[SourceAttribution, ...]:
    snapshot = next(
        (
            item
            for item in raw.snapshots
            if item.source_kind in source_kinds and str(item.requested_url) == source_url
        ),
        next((item for item in raw.snapshots if item.source_kind in source_kinds), None),
    )
    if snapshot is None:
        return ()
    return (
        SourceAttribution(
            kind=SourceKind(snapshot.source_kind),
            url=snapshot.requested_url,
            captured_at=snapshot.captured_at,
            content_sha256=snapshot.content_sha256,
            university_id="university:hse",
            field=field,
            record_key=record_key,
        ),
    )


def _source_gaps(raw: RawTracerBundle, record_key: str, source_url: str, *, field: str) -> tuple[SourceGapReference, ...]:
    return tuple(
        source_gap_reference(gap, field=field, record_key=record_key)
        for gap in raw.source_gaps
        if record_key in gap.entity_key or source_url in str(gap.source_url)
    )


def _captured_at(raw: RawTracerBundle, program: object) -> datetime:
    plan_url = str(getattr(program, "study_plan_url"))
    matches = [snapshot.captured_at for snapshot in raw.snapshots if str(snapshot.requested_url) == plan_url or snapshot.source_kind == "hse_curriculum_document"]
    return matches[0] if matches else raw.snapshots[0].captured_at


__all__ = ["normalize_bundle"]
