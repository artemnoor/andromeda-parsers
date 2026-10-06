from __future__ import annotations

import logging
import re
from html import unescape
from pathlib import Path
from collections.abc import Mapping
from typing import cast

from bs4 import BeautifulSoup
from pydantic import ValidationError

from .curriculum import _study_plan_records
from andromeda.ingestion.contracts.constraints import http_url
from andromeda.ingestion.contracts.raw import (
    JsonObject,
    RawCurriculumRow,
    RawDirectionRecord,
    RawProgramRecord,
    RawParserDiagnostic,
    RawSourceSnapshot,
    RawSourceGap,
    RawTracerBundle,
    RawUniversityRecord,
    SourceLocator,
)
from ..source_models import FetchedResource, SourceDefinition
from ..html import parse_page
from andromeda.ingestion.contracts.normalized import CanonicalSnapshot
from andromeda.shared.contracts.errors import ContractError, ErrorCode, ErrorDetail, details_from_validation
from ..capture import CapturedSources, BmstuSource, _detail_data, _json_object


from ..normalizers.canonical import normalize_bundle
from ..identity import canonicalize_program_records, direction_codes

logger = logging.getLogger("andromeda.ingestion.bmstu.parser")


def parse_sources(
    source: BmstuSource,
    mode: str = "fixture",
    fixture_dir: Path | None = None,
    program_codes: tuple[str, ...] | None = None,
) -> tuple[RawTracerBundle, CanonicalSnapshot]:
    captured = source.capture(mode=mode, fixture_dir=fixture_dir)
    try:
        raw_bundle = parse_captured(captured, program_codes=program_codes)
    except ValidationError as exc:
        raise ContractError(
            ErrorCode.SOURCE_CONTRACT_ERROR,
            "Raw source data does not satisfy the parser contract",
            details_from_validation(exc.errors()),
        ) from exc
    logger.debug("parser_stage raw_dto_validated programs=%d curriculum_rows=%d", len(raw_bundle.programs), len(raw_bundle.curriculum_rows))
    try:
        normalized = normalize_bundle(raw_bundle)
    except ValidationError as exc:
        raise ContractError(
            ErrorCode.SOURCE_CONTRACT_ERROR,
            "Normalized domain data does not satisfy the domain contract",
            details_from_validation(exc.errors()),
        ) from exc
    logger.debug("parser_stage normalized programs=%d curricula=%d", len(normalized.programs), len(normalized.curricula))
    return raw_bundle, normalized


def parse_captured(captured: CapturedSources, program_codes: tuple[str, ...] | None = None) -> RawTracerBundle:
    university = _parse_university(captured.first("bmstu_common"))
    detail_snapshots = captured.by_kind("bmstu_major_detail")
    if not detail_snapshots:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU catalog has no detail snapshots")
    directions: list[RawDirectionRecord] = []
    programs: list[RawProgramRecord] = []
    gaps: list[RawSourceGap] = list(captured.source_gaps)
    source_years = _source_education_years(captured)
    for detail_snapshot in detail_snapshots:
        direction, detail_programs, detail_gaps = _parse_detail(detail_snapshot, program_codes, source_years)
        directions.append(direction)
        programs.extend(detail_programs)
        gaps.extend(detail_gaps)
    if not programs:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU details contain no selected programs")
    programs = list(canonicalize_program_records(programs))
    normalized_directions = _direction_aliases(directions)
    if not normalized_directions:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU details contain no valid direction codes")
    selected_codes = set(program_codes) if program_codes is not None else None
    if selected_codes is not None and {program.code for program in programs} != selected_codes:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Selected programs are incomplete")
    rows: list[RawCurriculumRow] = []
    dynamic_discovery = len(detail_snapshots) > 1
    for program in programs:
        documents = _documents_for_program(captured, program)
        if not documents:
            metadata = _metadata_for_program(captured, program)
            if not metadata and not dynamic_discovery:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Could not select curriculum document for {program.code}")
            gaps.append(_curriculum_gap(program, "published study plan has no downloadable document"))
            continue
        duplicate_hashes = [snapshot.content_sha256 for snapshot in documents]
        if len(duplicate_hashes) != len(set(duplicate_hashes)):
            if not dynamic_discovery:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Could not select curriculum document for {program.code}")
            gaps.append(_curriculum_gap(program, "duplicate study-plan source snapshot"))
            continue
        try:
            program_rows = []
            for document in documents:
                program_rows.extend(_parse_curriculum(document, program.code, program.source_code or program.code))
            rows.extend(program_rows)
            if not program_rows:
                gaps.append(_curriculum_gap(program, "study-plan document produced no curriculum rows"))
        except ContractError:
            if not dynamic_discovery:
                raise
            gaps.append(_curriculum_gap(program, "study-plan document could not be parsed"))
    direction = normalized_directions[0]
    return RawTracerBundle(
        snapshots=captured.snapshots,
        university=university,
        direction=direction,
        programs=tuple(programs),
        curriculum_rows=tuple(rows),
        directions=tuple(normalized_directions),
        source_gaps=tuple(gaps),
        diagnostics=tuple(_diagnostics_from_gaps(gaps)),
    )


def _parse_university(snapshot: object) -> RawUniversityRecord:
    from andromeda.ingestion.contracts.raw import RawSourceSnapshot

    typed = cast(RawSourceSnapshot, snapshot)
    page = parse_page(typed.body, str(typed.final_url))
    soup = page.soup
    labels = page.labels
    name = _first_label(labels, "наимен", "полное") or _first_label(labels, "наимен") or _title(soup)
    if name and "Полное наименование на русском языке:" in name:
        match = re.search(
            r"Полное наименование на русском языке:\s*(.+?)(?=\s+Сокращенное наименование)",
            name,
        )
        name = match.group(1).strip() if match else name
    address = _first_label(labels, "местонахождение") or _first_label(labels, "адрес")
    city = _city(address)
    if not name or not address or not city:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "S01 university page does not contain required identity fields")
    return RawUniversityRecord(
        name=name,
        city=city,
        address=address,
        official_site=http_url("https://bmstu.ru/"),
        locator=SourceLocator(source_url=typed.requested_url),
    )


def _parse_detail(
    snapshot: object,
    program_codes: tuple[str, ...] | None,
    source_years: Mapping[str, int],
) -> tuple[RawDirectionRecord, list[RawProgramRecord], list[RawSourceGap]]:
    from andromeda.ingestion.contracts.raw import RawSourceSnapshot
    typed = cast(RawSourceSnapshot, snapshot)
    data = _detail_data_from_body(typed.body)
    additional = _obj(data.get("additional"))
    direction_code = _text(additional.get("code"))
    direction_name = _text(additional.get("name"))
    if not direction_code or not direction_name:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "S06 detail has no direction identity")
    direction = RawDirectionRecord(
        code=direction_code,
        name=direction_name,
        education_level="бакалавриат",
        locator=SourceLocator(source_url=typed.requested_url),
    )
    chairs = _obj(data.get("chairs"))
    records: list[RawProgramRecord] = []
    gaps: list[RawSourceGap] = []
    for chair_value in _list(chairs.get("items")):
        chair = _obj(chair_value)
        educational = _obj(chair.get("educationalProgram"))
        for program_value in _list(educational.get("items")):
            program = _obj(program_value)
            source_code = _text(program.get("code"))
            code = _canonical_code(source_code)
            name = _text(program.get("name"))
            plan = _text(program.get("plan"))
            if not source_code or not code:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "S06 detail contains a program without a code")
            if program_codes is not None and code not in program_codes:
                continue
            if not name or not plan:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Target program {code} is missing name or plan")
            education_year = _education_year(data) or source_years.get(plan)
            if education_year is None:
                gaps.append(_program_gap(code, plan, typed.requested_url, "program education year is absent from official sources"))
                continue
            records.append(
                RawProgramRecord(
                    code=code,
                    name=unescape(name),
                    direction_code=direction_code,
                    education_level="бакалавриат",
                    education_year=education_year,
                    study_plan_url=http_url(plan),
                    source_url=typed.requested_url,
                    locator=SourceLocator(source_url=typed.requested_url),
                    source_code=source_code,
                )
            )
    if program_codes is not None and len(records) != len(program_codes):
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "S06 detail did not contain exactly the selected programs")
    return direction, records, gaps


def _source_education_years(captured: CapturedSources) -> dict[str, int]:
    """Read academic year only from official study-plan document metadata."""

    result: dict[str, int] = {}
    for snapshot in captured.by_kind("bmstu_curriculum_document"):
        resource = FetchedResource(
            requested_url=str(snapshot.requested_url),
            final_url=str(snapshot.final_url),
            status_code=snapshot.status_code,
            content_type=snapshot.content_type,
            body=snapshot.body,
            fetched_at=snapshot.captured_at.isoformat(),
        )
        try:
            records = _study_plan_records(
                SourceDefinition(id="S06", name="BMSTU curriculum", url=str(snapshot.requested_url)),
                resource,
                snapshot.captured_at.isoformat(),
                context={},
            )
        except Exception:
            continue
        years = {
            int(value["education_year"])
            for value in records
            if isinstance(value, Mapping) and isinstance(value.get("education_year"), int)
        }
        if len(years) == 1:
            result[str(snapshot.requested_url)] = next(iter(years))
    return result


def _parse_curriculum(snapshot: RawSourceSnapshot, program_code: str, source_program_code: str) -> list[RawCurriculumRow]:
    typed = snapshot
    source_definition = SourceDefinition(id="S06", name="BMSTU curriculum", url=str(typed.requested_url))
    resource = FetchedResource(
        requested_url=str(typed.requested_url),
        final_url=str(typed.final_url),
        status_code=typed.status_code,
        content_type=typed.content_type,
        body=typed.body,
        fetched_at=typed.captured_at.isoformat(),
    )
    records = _study_plan_records(
        source_definition,
        resource,
        typed.captured_at.isoformat(),
        context={"program_profile_code": program_code, "study_plan_url": str(typed.requested_url)},
    )
    result: list[RawCurriculumRow] = []
    for value in records:
        if value.get("record_type") != "StudyPlan":
            continue
        record = cast(Mapping[str, object], value)
        discipline = _object_text(record.get("discipline"))
        semester = _object_int(record.get("semester"))
        hours = _object_int(record.get("hours"))
        credit_value = record.get("credits")
        credits = credit_value if isinstance(credit_value, (str, int, float)) else None
        if not discipline or hours is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Curriculum row for {program_code} is incomplete")
        result.append(
            RawCurriculumRow(
                program_code=program_code,
                discipline=discipline,
                semester=semester,
                hours=hours,
                credits=credits,
                assessment=_object_text(record.get("assessment_type")),
                source_position=semester and (_object_int(record.get("row_no")) or None),
                source_url=typed.requested_url,
                locator=SourceLocator(source_url=typed.requested_url, row=_object_int(record.get("row_no"))),
                source_program_code=source_program_code,
            )
        )
    if not result:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Curriculum document for {program_code} produced no rows")
    logger.debug("parser_stage curriculum_raw program=%s rows=%d", program_code, len(result))
    return result


def _documents_for_program(captured: CapturedSources, program: RawProgramRecord) -> tuple[RawSourceSnapshot, ...]:
    plan_url = str(program.study_plan_url)
    matches = tuple(
        snapshot
        for snapshot in captured.by_kind("bmstu_curriculum_document")
        if str(snapshot.requested_url) == plan_url
    )
    return matches


def _metadata_for_program(captured: CapturedSources, program: RawProgramRecord) -> tuple[RawSourceSnapshot, ...]:
    plan_url = str(program.study_plan_url)
    return tuple(snapshot for snapshot in captured.by_kind("bmstu_curriculum_metadata") if str(snapshot.requested_url) == plan_url)


def _curriculum_gap(program: RawProgramRecord, reason: str) -> RawSourceGap:
    from hashlib import sha256

    key = f"program|{program.code}|{program.study_plan_url}|{reason}"
    return RawSourceGap(
        id=f"source-gap:{sha256(key.encode('utf-8')).hexdigest()[:24]}",
        entity_type="program",
        entity_key=f"program:{program.code}",
        reason=reason,
        source_url=program.study_plan_url,
        locator=program.locator,
    )


def _direction_aliases(values: list[RawDirectionRecord]) -> list[RawDirectionRecord]:
    result: list[RawDirectionRecord] = []
    seen: set[str] = set()
    for value in values:
        for code in direction_codes(value.code):
            if code in seen:
                continue
            seen.add(code)
            result.append(value.model_copy(update={"code": code}))
    return result


def _detail_data_from_body(body: bytes) -> JsonObject:
    try:
        root: JsonObject = _json_object(body)
    except ContractError:
        soup = BeautifulSoup(body, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "S06 detail has neither JSON nor __NEXT_DATA__")
        root = _json_object(script.string.encode("utf-8"))
    return _detail_data(root)


def _first_label(labels: dict[str, str], *fragments: str) -> str | None:
    for key, value in labels.items():
        lowered = key.casefold()
        if all(fragment.casefold() in lowered for fragment in fragments):
            return value
    return None


def _title(soup: BeautifulSoup) -> str | None:
    node = soup.find("h1") or soup.find("title")
    return _clean(node.get_text(" ", strip=True)) if node else None


def _city(address: str | None) -> str | None:
    if not address:
        return None
    match = re.search(r"(?:г\.|город)\s*([^,]+)", address, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _education_year(data: Mapping[str, object]) -> int | None:
    text = _text(data.get("description")) or ""
    match = re.search(r"20\d{2}", text)
    if match:
        return int(match.group(0))
    return None


def _program_gap(code: str, plan_url: str, source_url: object, reason: str) -> RawSourceGap:
    from hashlib import sha256

    typed_url = http_url(str(source_url))
    key = f"program|{code}|{plan_url}|{reason}"
    return RawSourceGap(
        id=f"source-gap:{sha256(key.encode('utf-8')).hexdigest()[:24]}",
        entity_type="program",
        entity_key=f"program:{code}",
        reason=reason,
        source_url=typed_url,
        locator=SourceLocator(source_url=typed_url),
    )


def _diagnostics_from_gaps(gaps: list[RawSourceGap]) -> list[RawParserDiagnostic]:
    return [
        RawParserDiagnostic(
            code=gap.reason[:128],
            stage="capture" if gap.entity_type == "source" else "parse",
            message=gap.reason[:512],
            severity="ambiguous" if "ambig" in gap.reason.casefold() else "warning",
            source_url=gap.source_url,
        )
        for gap in gaps
    ]


def _canonical_code(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("–", "-").replace("—", "-").replace("/", "-").replace(" ", "")


def _clean(value: str) -> str:
    return " ".join(unescape(value).replace("\xa0", " ").split())


def _obj(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _object_text(value: object) -> str | None:
    return _text(value)


def _object_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None



__all__ = ["BmstuSource", "CapturedSources", "parse_captured", "parse_sources"]
