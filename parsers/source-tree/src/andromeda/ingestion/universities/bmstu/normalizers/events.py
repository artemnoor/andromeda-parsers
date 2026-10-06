"""Canonicalize BMSTU event records and resolve links to existing IDs."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from andromeda.modules.events.contracts.public import Event, EventFormat, EventKind, Venue
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.errors import ContractError, ErrorCode
from andromeda.shared.contracts.provenance import SourceAttribution

from ....contracts.raw import RawEventRecord, RawSourceSnapshot
from ..normalizers.codes import normalize_code


logger = logging.getLogger("andromeda.ingestion.bmstu.events")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_events(
    records: Sequence[RawEventRecord],
    *,
    programs: Sequence[Program],
    snapshots: Sequence[RawSourceSnapshot],
    known_program_codes: Sequence[str] | None = None,
) -> tuple[Event, ...]:
    snapshots_by_url = {
        str(snapshot.requested_url): snapshot
        for snapshot in snapshots
        if snapshot.source_kind == SourceKind.BMSTU_EVENTS.value
    }
    result: list[Event] = []
    seen_ids: set[str] = set()
    program_by_code = {normalize_code(program.code): program.id for program in programs}
    known_codes = {
        normalize_code(code)
        for code in (known_program_codes if known_program_codes is not None else tuple(program.code for program in programs))
    }
    logger.debug(
        "[FIX:events-subset] normalize_scope selected_program_count=%d known_program_count=%d input_event_count=%d",
        len(program_by_code),
        len(known_codes),
        len(records),
    )
    for index, record in enumerate(records):
        if record.source_kind != SourceKind.BMSTU_EVENTS.value:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Event record has an unexpected source kind")
        snapshot = snapshots_by_url.get(str(record.source_url))
        if snapshot is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Event source is not captured: {record.source_url}")
        university_slug = _university_slug(record.university_ids[0])
        event_id = f"event:{university_slug}:{_slug(record.external_key)}"
        if event_id in seen_ids:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Event identity collision: {event_id}")
        seen_ids.add(event_id)
        program_ids: list[str] = []
        for code in record.program_codes:
            normalized_code = normalize_code(code)
            if normalized_code not in known_codes:
                if known_program_codes is not None:
                    logger.warning(
                        "[FIX:events-subset] event_program_ignored source_key=%s code=%s reason=outside_selected_program_scope",
                        record.external_key,
                        code,
                    )
                    continue
                logger.error(
                    "[FIX:events-subset] event_program_rejected source_key=%s code=%s reason=unknown_program",
                    record.external_key,
                    code,
                )
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Unknown BMSTU event program identity: {code}")
            program_id = program_by_code.get(normalized_code)
            if program_id is None:
                continue
            if program_id not in program_ids:
                program_ids.append(program_id)
        if record.program_codes and not program_ids:
            logger.warning(
                "[FIX:events-subset] event_skipped source_key=%s reason=outside_selected_program_scope",
                record.external_key,
            )
            continue
        department_ids = tuple(f"department:bmstu:{_slug(code)}" for code in record.department_codes)
        venue = _venue(record, university_slug) if record.venue is not None else None
        event = Event(
            id=event_id,
            title=record.title,
            kind=EventKind(record.kind),
            format=EventFormat(record.format),
            starts_at=record.starts_at,
            ends_at=record.ends_at,
            description=record.description,
            registration_url=record.registration_url,
            university_ids=record.university_ids,
            department_ids=department_ids,
            program_ids=tuple(program_ids),
            venue=venue,
            provenance=(
                SourceAttribution(
                    kind=SourceKind.BMSTU_EVENTS,
                    url=snapshot.requested_url,
                    captured_at=snapshot.captured_at,
                    content_sha256=snapshot.content_sha256,
                    locator=record.locator.field,
                ),
            ),
        )
        result.append(event)
        logger.debug("event_normalized source_key=%s index=%d event_id=%s", record.external_key, index, event_id)
    logger.info(
        "[FIX:events-subset] event_scope_applied selected_program_count=%d input_event_count=%d output_event_count=%d",
        len(program_by_code),
        len(records),
        len(result),
    )
    logger.info("bmstu_events_canonicalized records=%d events=%d", len(records), len(result))
    return tuple(result)


def _venue(record: RawEventRecord, university_slug: str) -> Venue:
    assert record.venue is not None
    return Venue(
        id=f"venue:{university_slug}:{_slug(record.venue.external_key)}",
        name=record.venue.name,
        address=record.venue.address,
        latitude=record.venue.latitude,
        longitude=record.venue.longitude,
    )


def _university_slug(university_id: str) -> str:
    return university_id.removeprefix("university:")


def _slug(value: str) -> str:
    normalized = value.casefold().strip()
    normalized = normalized.replace("ё", "е")
    normalized = _SLUG_RE.sub("-", normalized).strip("-")
    if not normalized:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Event source identity cannot be empty")
    return normalized[:128]


__all__ = ["normalize_events"]
