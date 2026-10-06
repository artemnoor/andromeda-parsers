from __future__ import annotations

import logging
from hashlib import sha256
from pathlib import Path
from typing import Sequence

from ...contracts.normalized import CanonicalSnapshot
from ...contracts.raw import RawAdmissionPassingScore, RawAdmissionRecord, RawProgramRecord, RawSourceGap, RawTracerBundle, SourceLocator
from ...contracts.source import CapturedSources, RawSourceSnapshot
from ....modules.disciplines.contracts.public import Discipline
from ....shared.contracts.enums import SourceKind
from ....shared.contracts.provenance import SourceAttribution
from ....modules.disciplines.services.classifier import RuleBasedDisciplineClassifier
from .selectors import DEFAULT_CAMPUS_FIXTURE_DIR, DEFAULT_EVENT_FIXTURE_DIR, DEFAULT_FIXTURE_DIR, select_program_codes
from .mappings.discipline_areas import BMSTU_DISCIPLINE_AREA_OVERRIDES
from .normalizers.admissions import normalize_admissions
from .normalizers.campus import normalize_campus_points
from .normalizers.events import normalize_events
from .parser.admissions import parse_detail_admissions
from .parser.admission_orders import iter_pdf_pages, parse_admission_order_document
from .parser.campus import load_campus_fixture, parse_campus_points
from .parser.events import load_event_fixture, parse_events
from .parser.tracer import parse_captured
from .capture import BmstuSource, _detail_plan_records, parse_orders_manifest
from .identity import direction_codes as extract_direction_codes, map_source_program_code
from .normalizers.canonical import normalize_bundle
from .source_metadata import classify_order_document


fetch_logger = logging.getLogger("andromeda.ingestion.bmstu.fetch")
select_logger = logging.getLogger("andromeda.ingestion.bmstu.select")
parse_logger = logging.getLogger("andromeda.ingestion.bmstu.parse")
normalize_logger = logging.getLogger("andromeda.ingestion.bmstu.normalize")


class BmstuUniversityAdapter:
    """Typed BMSTU boundary for source capture, parsing, and normalization."""

    def __init__(self, fetcher: object | None = None) -> None:
        self._source = BmstuSource(fetcher=fetcher)  # type: ignore[arg-type]
        self._classifier = RuleBasedDisciplineClassifier(BMSTU_DISCIPLINE_AREA_OVERRIDES)

    def close(self) -> None:
        self._source.close()

    def capture(
        self,
        mode: str = "fixture",
        fixture_dir: Path | None = None,
        event_fixture_dir: Path | None = None,
        campus_fixture_dir: Path | None = None,
    ) -> CapturedSources:
        fetch_logger.debug("stage=capture mode=%s", mode)
        captured = self._source.capture(mode=mode, fixture_dir=fixture_dir or DEFAULT_FIXTURE_DIR)
        snapshots = captured.snapshots
        if mode == "fixture":
            event_snapshot = load_event_fixture(event_fixture_dir or DEFAULT_EVENT_FIXTURE_DIR)
            campus_snapshot = load_campus_fixture(campus_fixture_dir or DEFAULT_CAMPUS_FIXTURE_DIR)
            snapshots += (event_snapshot, campus_snapshot)
        result = CapturedSources(snapshots=snapshots, source_gaps=captured.source_gaps)
        fetch_logger.info(
            "stage=capture_complete mode=%s snapshots=%d event_source=%s campus_source=%s",
            mode,
            len(result.snapshots),
            mode == "fixture",
            mode == "fixture",
        )
        return result

    def parse(
        self,
        captured: CapturedSources,
        program_codes: Sequence[str] | None = None,
    ) -> tuple[RawTracerBundle, CanonicalSnapshot]:
        selected = select_program_codes(tuple(program_codes)) if program_codes is not None else _fixture_documented_codes(captured)
        campus_source_kind = "bmstu_campus_points"
        parser_snapshots = tuple(
            snapshot
            for snapshot in captured.snapshots
            if snapshot.source_kind != campus_source_kind
        )
        parser_captured = CapturedSources(snapshots=parser_snapshots, source_gaps=captured.source_gaps)
        select_logger.debug("stage=selected source_snapshots=%d programs=%s", len(parser_snapshots), len(selected) if selected is not None else "discovery")
        parse_logger.debug("stage=parse source_snapshots=%d programs=%s", len(parser_snapshots), len(selected) if selected is not None else "discovery")
        raw = parse_captured(parser_captured, program_codes=selected).model_copy(
            update={"snapshots": captured.snapshots}
        )
        admission_records = tuple(
            record
            for detail_snapshot in captured.by_kind("bmstu_major_detail")
            for record in parse_detail_admissions(detail_snapshot, selected)
        )
        order_records, order_gaps = _parse_order_admissions(captured, raw.programs)
        admission_records, admission_gaps = _canonicalize_admission_records(
            (*admission_records, *order_records),
            raw.programs,
        )
        event_snapshots = captured.by_kind("bmstu_events")
        if len(event_snapshots) > 1:
            raise ValueError("expected at most one BMSTU event source snapshot")
        event_records = parse_events(event_snapshots[0]) if event_snapshots else ()
        campus_snapshots = captured.by_kind(campus_source_kind)
        if len(campus_snapshots) > 1:
            raise ValueError("expected at most one BMSTU campus source snapshot")
        campus_records = parse_campus_points(campus_snapshots[0]) if campus_snapshots else ()
        raw = raw.model_copy(
            update={
                "admissions": admission_records,
                "source_gaps": (*raw.source_gaps, *order_gaps, *admission_gaps),
                "events": event_records,
                "campus_points": campus_records,
            }
        )
        canonical = normalize_bundle(raw)
        if campus_snapshots and not any(source.kind is SourceKind.BMSTU_CAMPUS_POINTS for source in canonical.sources):
            campus_snapshot = campus_snapshots[0]
            canonical = canonical.model_copy(
                update={
                    "sources": (
                        *canonical.sources,
                        SourceAttribution(
                            kind=SourceKind.BMSTU_CAMPUS_POINTS,
                            url=campus_snapshot.requested_url,
                            captured_at=campus_snapshot.captured_at,
                            content_sha256=campus_snapshot.content_sha256,
                        ),
                    )
                }
            )
        order_source_snapshots = (
            *captured.by_kind("bmstu_admission_orders_index"),
            *captured.by_kind("bmstu_admission_orders_document"),
        )
        if order_source_snapshots:
            existing_sources = {
                (str(source.kind), str(source.url), source.content_sha256)
                for source in canonical.sources
            }
            missing_order_sources = tuple(
                snapshot
                for snapshot in order_source_snapshots
                if (
                    snapshot.source_kind,
                    str(snapshot.requested_url),
                    snapshot.content_sha256,
                )
                not in existing_sources
            )
            canonical = canonical.model_copy(
                update={
                    "sources": (
                        *canonical.sources,
                        *(
                            SourceAttribution(
                                kind=SourceKind(snapshot.source_kind),
                                url=snapshot.requested_url,
                                captured_at=snapshot.captured_at,
                                content_sha256=snapshot.content_sha256,
                            )
                            for snapshot in missing_order_sources
                        ),
                    )
                }
            )
        classified_disciplines = tuple(
            Discipline.model_validate(
                {
                    **discipline.model_dump(),
                    "area_weights": self._classifier.classify(discipline.name),
                }
            )
            for discipline in canonical.disciplines
        )
        classification_outcomes = tuple(
            self._classifier.classify_with_outcome(
                discipline.name,
                discipline_id=discipline.id,
            )
            for discipline in canonical.disciplines
        )
        canonical = CanonicalSnapshot.model_validate(
            {
                **canonical.model_dump(),
                "disciplines": classified_disciplines,
                "classification_outcomes": classification_outcomes,
                "source_gaps": raw.source_gaps,
                "admissions": normalize_admissions(
                    raw.admissions,
                    programs=canonical.programs,
                    snapshots=raw.snapshots,
                ),
                "events": normalize_events(
                    raw.events,
                    programs=canonical.programs,
                    snapshots=raw.snapshots,
                    known_program_codes=tuple(program.code for program in canonical.programs),
                ),
                "campus_points": normalize_campus_points(
                    raw.campus_points,
                    programs=canonical.programs,
                    snapshots=raw.snapshots,
                    known_program_codes=tuple(program.code for program in canonical.programs),
                ),
            }
        )
        area_count = len({weight.area for discipline in canonical.disciplines for weight in discipline.area_weights})
        normalize_logger.info(
            "stage=canonical_complete programs=%d disciplines=%d curricula=%d items=%d areas=%d",
            len(canonical.programs),
            len(canonical.disciplines),
            len(canonical.curricula),
            sum(len(curriculum.items) for curriculum in canonical.curricula),
            area_count,
        )
        normalize_logger.info("stage=events_complete events=%d", len(canonical.events))
        normalize_logger.info("stage=campus_complete points=%d", len(canonical.campus_points))
        normalize_logger.info(
            "stage=orders_complete documents=%d records=%d gaps=%d numeric=%d bvi=%d",
            len(captured.by_kind("bmstu_admission_orders_document")),
            len(order_records),
            len(order_gaps),
            sum(1 for record in order_records for score in record.passing_scores if score.status == "numeric"),
            sum(1 for record in order_records for score in record.passing_scores if score.status == "bvi"),
        )
        return raw, canonical

    def parse_sources(
        self,
        mode: str = "fixture",
        fixture_dir: Path | None = None,
        event_fixture_dir: Path | None = None,
        campus_fixture_dir: Path | None = None,
        program_codes: Sequence[str] | None = None,
    ) -> tuple[RawTracerBundle, CanonicalSnapshot]:
        captured = self.capture(
            mode=mode,
            fixture_dir=fixture_dir,
            event_fixture_dir=event_fixture_dir,
            campus_fixture_dir=campus_fixture_dir,
        )
        return self.parse(captured, program_codes=program_codes)


def _canonicalize_admission_code(record: RawAdmissionRecord, programs: Sequence[RawProgramRecord]) -> RawAdmissionRecord:
    source_code = record.program_code
    source_name = record.program_name
    source_directions = extract_direction_codes(source_code)
    canonical = (
        source_directions[0]
        if record.scope == "direction" and len(source_directions) == 1
        else map_source_program_code(
            source_code,
            source_name,
            programs,
        )
    )
    return record.model_copy(update={"program_code": canonical, "source_program_code": source_code})


def _canonicalize_admission_records(
    records: Sequence[RawAdmissionRecord],
    programs: Sequence[RawProgramRecord],
) -> tuple[tuple[RawAdmissionRecord, ...], tuple[RawSourceGap, ...]]:
    """Canonicalize source rows and quarantine identities outside this catalog.

    BMSTU publishes historical and cross-catalog admission rows together with
    the current detail payload.  An unknown direction/profile must not be
    projected to a current program, but it is still useful source evidence.
    Ambiguous mappings continue to raise from ``_canonicalize_admission_code``
    so a parser change cannot silently guess a target.
    """

    known_program_codes = {_canonical_code(program.code) for program in programs}
    known_direction_codes = {
        direction
        for program in programs
        for direction in (
            extract_direction_codes(program.direction_code)
            or extract_direction_codes(program.code)
            or (_canonical_code(program.direction_code),)
        )
    }
    accepted: list[RawAdmissionRecord] = []
    gaps: list[RawSourceGap] = []
    for source_record in records:
        record = _canonicalize_admission_code(source_record, programs)
        code = _canonical_code(record.program_code)
        if record.scope == "direction":
            known = code in known_direction_codes or any(
                program_code.startswith(f"{code}-") for program_code in known_program_codes
            )
        else:
            known = code in known_program_codes
        if known:
            accepted.append(record)
            continue
        gap = _admission_identity_gap(record)
        gaps.append(gap)
        parse_logger.warning(
            "admission_source_gap reason=%s program_code=%s source_url=%s locator=%s",
            gap.reason,
            record.program_code,
            record.source_url,
            record.locator.field or record.locator.page or record.locator.row,
        )
    return tuple(accepted), tuple(gaps)


def _admission_identity_gap(record: RawAdmissionRecord) -> RawSourceGap:
    stable = "|".join(
        (
            record.id,
            record.program_code,
            str(record.admission_year),
            str(record.source_url),
            record.locator.field or "",
        )
    )
    return RawSourceGap(
        id=f"source-gap:bmstu-admission-identity:{sha256(stable.encode('utf-8')).hexdigest()}",
        entity_type="admission",
        entity_key=f"{record.program_code}:{record.admission_year}:{record.id}",
        reason="admission-program-identity-unknown",
        source_url=record.source_url,
        locator=record.locator,
    )


def _parse_order_admissions(
    captured: CapturedSources,
    programs: Sequence[RawProgramRecord],
) -> tuple[tuple[RawAdmissionRecord, ...], tuple[RawSourceGap, ...]]:
    order_snapshots = captured.by_kind("bmstu_admission_orders_document")
    if not order_snapshots:
        return (), ()
    manifest_snapshots = captured.by_kind("bmstu_admission_orders_index")
    if len(manifest_snapshots) != 1:
        raise ValueError("BMSTU order documents require exactly one orders manifest snapshot")
    entries = parse_orders_manifest(manifest_snapshots[0].body, str(manifest_snapshots[0].requested_url))
    entries_by_url = {entry.requested_url: entry for entry in entries}
    direction_codes = tuple(
        sorted(
            {
                direction
                for program in programs
                for direction in (
                    extract_direction_codes(program.direction_code)
                    or (_canonical_code(program.direction_code) or _canonical_code(program.code) or program.code,)
                )
            }
        )
    )
    records: list[RawAdmissionRecord] = []
    gaps: list[RawSourceGap] = []
    for snapshot in order_snapshots:
        requested_url = str(snapshot.requested_url)
        entry = entries_by_url.get(requested_url)
        if entry is None:
            gaps.append(_order_gap(snapshot, "manifest_entry_missing", None, None))
            continue
        pages = iter_pdf_pages(snapshot.body)
        metadata = classify_order_document(entry, pages)
        if not metadata.supported_catalog:
            select_logger.info(
                "[FIX:source-gap] orders_document_unsupported url=%s kind=%s",
                requested_url,
                metadata.document_kind.value,
            )
            gaps.append(_order_gap(snapshot, "unsupported_document_kind", metadata, None))
            continue
        if metadata.admission_year is None:
            select_logger.warning("[FIX:source-gap] orders_document_missing_year url=%s", requested_url)
            gaps.append(_order_gap(snapshot, "admission_year_unknown", metadata, None))
            continue
        result = parse_admission_order_document(snapshot.body, metadata)
        if result.failed:
            gaps.append(_order_gap(snapshot, "order_document_parse_failed", metadata, None))
            continue
        for warning in result.warnings:
            if warning.startswith("competition_heading_unknown"):
                gaps.append(_order_gap(snapshot, warning, metadata, None))
        present_directions = {observation.direction_code for observation in result.observations}
        for direction_code in direction_codes:
            if direction_code not in present_directions:
                gaps.append(_order_gap(snapshot, "direction_section_not_published", metadata, direction_code))
        unknown_directions = sorted(present_directions - set(direction_codes))
        for unknown_direction in unknown_directions:
            gaps.append(_order_gap(snapshot, "order_direction_not_in_catalog", metadata, unknown_direction))
        for observation in result.observations:
            if observation.direction_code not in direction_codes:
                continue
            locator = SourceLocator(
                source_url=snapshot.requested_url,
                page=observation.page,
                row=observation.row,
                field=f"competition={observation.competition_type.value};status={observation.status}",
            )
            score = RawAdmissionPassingScore(
                score_type=observation.score_type,
                competition_type=observation.competition_type.value,
                status=observation.status,
                score=observation.score,
            )
            stable = "|".join(
                (
                    observation.direction_code,
                    str(observation.admission_year),
                    observation.funding_type,
                    observation.competition_type.value,
                    observation.status,
                    str(observation.score),
                )
            )
            records.append(
                RawAdmissionRecord(
                    id=f"admission-order:{sha256(stable.encode('utf-8')).hexdigest()}",
                    program_code=observation.direction_code,
                    admission_year=observation.admission_year,
                    study_form=observation.study_form,
                    funding_type=observation.funding_type,
                    scope="direction",
                    passing_scores=(score,),
                    source_kind="bmstu_admission_orders_document",
                    source_url=snapshot.requested_url,
                    locator=locator,
                    source_program_code=observation.direction_code,
                )
            )
    parse_logger.info(
        "orders_projection_complete documents=%d records=%d gaps=%d directions=%d",
        len(order_snapshots),
        len(records),
        len(gaps),
        len(direction_codes),
    )
    return tuple(records), tuple(gaps)


def _order_gap(
    snapshot: RawSourceSnapshot,
    reason: str,
    metadata: object | None,
    direction_code: str | None,
) -> RawSourceGap:
    year = getattr(metadata, "admission_year", None)
    funding = getattr(getattr(metadata, "funding", None), "value", "unknown")
    stage = getattr(getattr(metadata, "stage", None), "value", "unknown")
    key = "|".join((str(snapshot.requested_url), str(year or "unknown"), direction_code or "document", funding, stage, reason))
    field = f"funding={funding};stage={stage}"
    gap = RawSourceGap(
        id=f"source-gap:bmstu-admission-order:{sha256(key.encode('utf-8')).hexdigest()}",
        entity_type="admission_order",
        entity_key=f"{direction_code or 'document'}:{year or 'unknown'}:{funding}:{stage}",
        reason=reason[:512],
        source_url=snapshot.requested_url,
        locator=SourceLocator(source_url=snapshot.requested_url, field=field),
    )
    parse_logger.warning(
        "orders_source_gap reason=%s direction=%s year=%s funding=%s stage=%s source_url=%s",
        gap.reason,
        direction_code or "document",
        year or "unknown",
        funding,
        stage,
        snapshot.requested_url,
    )
    return gap


def _fixture_documented_codes(captured: CapturedSources) -> tuple[str, ...] | None:
    """Scope only the historical fixture when its HTML detail has extra profiles."""

    detail_snapshots = captured.by_kind("bmstu_major_detail")
    if not detail_snapshots or any("api.www.bmstu.ru/majors/" in str(snapshot.requested_url) for snapshot in detail_snapshots):
        return None
    document_urls = {str(snapshot.requested_url) for snapshot in captured.by_kind("bmstu_curriculum_document")}
    if not document_urls:
        return None
    codes = tuple(
        _canonical_code(code)
        for snapshot in detail_snapshots
        for code, _, plan in _detail_plan_records(snapshot.body)
        if plan in document_urls
    )
    return tuple(dict.fromkeys(codes)) or None


def _canonical_code(value: str) -> str:
    return value.replace("–", "-").replace("—", "-").replace("/", "-").replace(" ", "")


__all__ = ["BmstuUniversityAdapter"]
