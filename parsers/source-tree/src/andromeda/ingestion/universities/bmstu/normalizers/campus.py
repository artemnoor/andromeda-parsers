"""Canonicalize BMSTU campus points and resolve existing catalog IDs."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from andromeda.modules.campus.contracts.public import CampusPoint, CampusPointType
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.errors import ContractError, ErrorCode
from andromeda.shared.contracts.provenance import SourceAttribution

from ....contracts.raw import RawCampusPointRecord, RawSourceSnapshot
from ..normalizers.codes import normalize_code


logger = logging.getLogger("andromeda.ingestion.bmstu.campus")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_campus_points(
    records: Sequence[RawCampusPointRecord],
    *,
    programs: Sequence[Program],
    snapshots: Sequence[RawSourceSnapshot],
    known_program_codes: Sequence[str] | None = None,
) -> tuple[CampusPoint, ...]:
    snapshots_by_url = {
        str(snapshot.requested_url): snapshot
        for snapshot in snapshots
        if snapshot.source_kind == SourceKind.BMSTU_CAMPUS_POINTS.value
    }
    program_by_code = {normalize_code(program.code): program.id for program in programs}
    known_codes = {
        normalize_code(code)
        for code in (known_program_codes if known_program_codes is not None else tuple(program.code for program in programs))
    }
    result: list[CampusPoint] = []
    seen_ids: set[str] = set()
    logger.debug(
        "campus_normalize_start selected_program_count=%d known_program_count=%d input_point_count=%d",
        len(program_by_code),
        len(known_codes),
        len(records),
    )
    for index, record in enumerate(records):
        if record.source_kind != SourceKind.BMSTU_CAMPUS_POINTS.value:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Campus point has an unexpected source kind")
        snapshot = snapshots_by_url.get(str(record.source_url))
        if snapshot is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Campus source is not captured: {record.source_url}")
        university_slug = _university_slug(record.university_ids[0])
        point_id = f"venue:{university_slug}:{_slug(record.external_key)}"
        if point_id in seen_ids:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Campus point identity collision: {point_id}")
        seen_ids.add(point_id)
        program_ids: list[str] = []
        for code in record.program_codes:
            normalized_code = normalize_code(code)
            if normalized_code not in known_codes:
                if known_program_codes is not None:
                    logger.warning(
                        "campus_program_ignored source_key=%s code=%s reason=outside_selected_program_scope",
                        record.external_key,
                        code,
                    )
                    continue
                logger.error("campus_program_rejected source_key=%s code=%s reason=unknown_program", record.external_key, code)
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Unknown BMSTU campus program identity: {code}")
            program_id = program_by_code.get(normalized_code)
            if program_id is not None and program_id not in program_ids:
                program_ids.append(program_id)
        if record.program_codes and not program_ids:
            logger.warning("campus_program_links_empty source_key=%s reason=outside_selected_program_scope", record.external_key)
        department_ids = tuple(_department_id(code) for code in record.department_codes)
        point = CampusPoint(
            id=point_id,
            point_type=CampusPointType(record.point_type),
            name=record.name,
            address=record.address,
            latitude=record.latitude,
            longitude=record.longitude,
            university_ids=record.university_ids,
            department_ids=department_ids,
            program_ids=tuple(program_ids),
            provenance=(
                SourceAttribution(
                    kind=SourceKind.BMSTU_CAMPUS_POINTS,
                    url=snapshot.requested_url,
                    captured_at=snapshot.captured_at,
                    content_sha256=snapshot.content_sha256,
                    locator=record.locator.field,
                ),
            ),
        )
        result.append(point)
        logger.debug(
            "campus_point_normalized source_key=%s index=%d point_id=%s point_type=%s department_count=%d program_count=%d",
            record.external_key,
            index,
            point.id,
            point.point_type.value,
            len(point.department_ids),
            len(point.program_ids),
        )
    logger.info(
        "campus_normalize_complete input_point_count=%d output_point_count=%d selected_program_count=%d",
        len(records),
        len(result),
        len(program_by_code),
    )
    return tuple(result)


def _department_id(value: str) -> str:
    normalized = value.strip().casefold().removeprefix("department:bmstu:")
    slug = _slug(normalized)
    return f"department:bmstu:{slug}"


def _university_slug(university_id: str) -> str:
    return university_id.removeprefix("university:")


def _slug(value: str) -> str:
    normalized = value.casefold().strip().replace("ё", "е")
    normalized = _SLUG_RE.sub("-", normalized).strip("-")
    if not normalized:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Campus source identity cannot be empty")
    # VenueId reserves at most 63 characters for the external-key segment.
    return normalized[:63]


__all__ = ["normalize_campus_points"]
