"""Fail-closed parser for the BMSTU campus-point fixture."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import NoReturn, cast

from pydantic import HttpUrl, TypeAdapter

from andromeda.modules.campus.domain.entities import CampusPointType
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.errors import ContractError, ErrorCode, ErrorDetail

from ....contracts.raw import RawCampusPointRecord, RawSourceSnapshot, SourceLocator


logger = logging.getLogger("andromeda.ingestion.bmstu.campus")
CAMPUS_SOURCE_URL = "https://bmstu.ru/campus/points"
_HTTP_URL = TypeAdapter(HttpUrl)


def load_campus_fixture(fixture_dir: Path) -> RawSourceSnapshot:
    """Load one hash-checked campus source snapshot from a fixture directory."""
    manifest_path = fixture_dir / "source_manifest.json"
    logger.debug("campus_fixture_load_start fixture_dir=%s", fixture_dir)
    if not manifest_path.exists():
        _fail("fixture_dir", "campus fixture manifest not found")
    manifest = _json_object(manifest_path.read_bytes(), "source_manifest.json")
    snapshots_value = manifest.get("snapshots")
    if not isinstance(snapshots_value, list) or len(snapshots_value) != 1:
        _fail("snapshots", "campus fixture must contain exactly one snapshot")
    item_value: object = snapshots_value[0]
    if not isinstance(item_value, Mapping):
        _fail("snapshots[0]", "snapshot must be an object")
    item = cast(Mapping[str, object], item_value)
    body_path = _required_text(item, "body_path")
    body_file = (fixture_dir / body_path).resolve()
    fixture_root = fixture_dir.resolve()
    if fixture_root not in body_file.parents:
        _fail("snapshots[0].body_path", "fixture body path escapes fixture directory")
    if not body_file.is_file():
        _fail("snapshots[0].body_path", "fixture body does not exist")
    body = body_file.read_bytes()
    digest = sha256(body).hexdigest()
    if digest != _required_text(item, "content_sha256"):
        _fail("snapshots[0].content_sha256", "fixture body hash does not match manifest")
    source_kind = _required_text(item, "source_kind")
    if source_kind != SourceKind.BMSTU_CAMPUS_POINTS.value:
        _fail("snapshots[0].source_kind", "unexpected campus source kind")
    content_type_value = item.get("content_type")
    snapshot = RawSourceSnapshot(
        source_kind=source_kind,
        requested_url=_http_url(_required_text(item, "requested_url")),
        final_url=_http_url(_required_text(item, "final_url")),
        status_code=_required_int(item, "status_code"),
        content_type=content_type_value if isinstance(content_type_value, str) else None,
        captured_at=_required_datetime(item, "captured_at"),
        content_sha256=digest,
        body=body,
    )
    logger.info("campus_fixture_load_complete records_bytes=%d sha256=%s", len(body), digest)
    return snapshot


def parse_campus_points(snapshot: RawSourceSnapshot) -> tuple[RawCampusPointRecord, ...]:
    """Parse source JSON into typed raw campus records."""
    if snapshot.source_kind != SourceKind.BMSTU_CAMPUS_POINTS.value:
        _fail("source_kind", "campus parser received an unexpected source kind", snapshot)
    root = _json_object(snapshot.body, "campus fixture body")
    values_value = root.get("points")
    if not isinstance(values_value, list):
        _fail("points", "campus fixture must contain an array", snapshot)
    values = cast(list[object], values_value)
    records: list[RawCampusPointRecord] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        locator = SourceLocator(source_url=snapshot.requested_url, row=index + 1, field="points")
        if not isinstance(value, Mapping):
            _fail(f"points[{index}]", "point must be an object", snapshot, locator)
        point_value = cast(Mapping[str, object], value)
        external_key = _required_text(point_value, "external_key", locator)
        if external_key in seen:
            _fail(f"points[{index}].external_key", "duplicate campus point external key", snapshot, locator)
        seen.add(external_key)
        record = _parse_record(point_value, snapshot, locator, external_key)
        records.append(record)
        logger.debug(
            "campus_point_parsed source_key=%s index=%d point_type=%s department_count=%d program_count=%d",
            external_key,
            index,
            record.point_type,
            len(record.department_codes),
            len(record.program_codes),
        )
    logger.info("campus_fixture_parsed records=%d", len(records))
    return tuple(records)


def _parse_record(
    value: Mapping[str, object],
    snapshot: RawSourceSnapshot,
    locator: SourceLocator,
    external_key: str,
) -> RawCampusPointRecord:
    try:
        point_type = _required_text(value, "point_type", locator)
        if point_type not in {item.value for item in CampusPointType}:
            _fail(f"points[{locator.row}].point_type", "unknown campus point type", snapshot, locator)
        latitude = _decimal(value.get("latitude"), "latitude", locator)
        longitude = _decimal(value.get("longitude"), "longitude", locator)
        if (latitude is None) != (longitude is None):
            _fail(f"points[{locator.row}]", "latitude and longitude must be provided together", snapshot, locator)
        return RawCampusPointRecord(
            external_key=external_key,
            point_type=point_type,
            name=_required_text(value, "name", locator),
            address=_optional_text(value, "address"),
            latitude=latitude,
            longitude=longitude,
            university_ids=_string_tuple(value, "university_ids", locator, minimum=1),
            department_codes=_string_tuple(value, "department_codes", locator),
            program_codes=_string_tuple(value, "program_codes", locator),
            source_kind=snapshot.source_kind,
            source_url=snapshot.requested_url,
            locator=locator,
        )
    except ContractError:
        raise
    except Exception as exc:
        logger.error("campus_point_rejected locator=%s reason=%s", locator, str(exc))
        raise ContractError(
            ErrorCode.SOURCE_CONTRACT_ERROR,
            f"BMSTU campus point record violates the source contract: {exc}",
            (ErrorDetail(path=f"points[{locator.row}]", message=str(exc), type="source_shape"),),
        ) from exc


def _json_object(body: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(label, "JSON is malformed")
    if not isinstance(value, dict):
        _fail(label, "JSON root must be an object")
    return cast(dict[str, object], value)


def _required_text(value: Mapping[str, object], key: str, locator: SourceLocator | None = None) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate.strip():
        _fail(key, "required non-empty text is missing", locator=locator)
    return candidate.strip()


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    candidate = value.get(key)
    return candidate.strip() if isinstance(candidate, str) and candidate.strip() else None


def _string_tuple(value: Mapping[str, object], key: str, locator: SourceLocator, *, minimum: int = 0) -> tuple[str, ...]:
    candidate = value.get(key, [])
    if not isinstance(candidate, list) or any(not isinstance(item, str) or not item.strip() for item in candidate):
        _fail(key, "must be an array of non-empty strings", locator=locator)
    items = cast(list[object], candidate)
    result = tuple(item.strip() for item in items if isinstance(item, str))
    if len(result) < minimum:
        _fail(key, "does not contain the required number of values", locator=locator)
    if len(result) != len(set(result)):
        _fail(key, "contains duplicate values", locator=locator)
    return result


def _decimal(value: object, key: str, locator: SourceLocator) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        _fail(key, "must be a decimal coordinate", locator=locator)
    try:
        coordinate = Decimal(str(value))
    except InvalidOperation:
        _fail(key, "must be a decimal coordinate", locator=locator)
        raise AssertionError from None
    if key == "latitude" and not Decimal("-90") <= coordinate <= Decimal("90"):
        _fail(key, "coordinate must be between -90 and 90", locator=locator)
    if key == "longitude" and not Decimal("-180") <= coordinate <= Decimal("180"):
        _fail(key, "coordinate must be between -180 and 180", locator=locator)
    return coordinate


def _required_int(value: Mapping[str, object], key: str) -> int:
    candidate = value.get(key)
    if not isinstance(candidate, int) or isinstance(candidate, bool) or not 200 <= candidate <= 599:
        _fail(key, "must be an HTTP status code")
    return candidate


def _required_datetime(value: Mapping[str, object], key: str) -> datetime:
    candidate = _required_text(value, key)
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        _fail(key, "must be an ISO datetime")
        raise AssertionError from None


def _http_url(value: str) -> HttpUrl:
    return _HTTP_URL.validate_python(value)


def _fail(
    path: str,
    message: str,
    snapshot: RawSourceSnapshot | None = None,
    locator: SourceLocator | None = None,
) -> NoReturn:
    del snapshot
    logger.error("campus_source_rejected locator=%s path=%s reason=%s", locator or "manifest", path, message)
    raise ContractError(
        ErrorCode.SOURCE_CONTRACT_ERROR,
        message,
        (ErrorDetail(path=path, message=message, type="source_contract"),),
    )


__all__ = ["CAMPUS_SOURCE_URL", "load_campus_fixture", "parse_campus_points"]
