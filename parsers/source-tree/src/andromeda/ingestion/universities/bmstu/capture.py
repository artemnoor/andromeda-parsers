from __future__ import annotations

import json
import logging
import re
from html import unescape
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import cast
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .fetch import FetchConfig, Fetcher
from .source_models import FetchedResource
from .pdf import is_pdf
from andromeda.ingestion.contracts.constraints import http_url
from andromeda.ingestion.contracts.raw import JsonValue, RawSourceGap, RawSourceSnapshot
from andromeda.ingestion.contracts.source import CapturedSources, source_fetch_gap
from andromeda.shared.contracts.errors import ContractError, ErrorCode, ErrorDetail

JsonObject = dict[str, JsonValue]
logger = logging.getLogger("andromeda.ingestion.bmstu.source.fetch")
selection_logger = logging.getLogger("andromeda.ingestion.bmstu.source.select")

S01_URL = "https://bmstu.ru/sveden/common"
S06_CATALOG_URL = "https://bmstu.ru/bachelor/majors"
S06_API_BASE_URL = "https://api.www.bmstu.ru/majors/baccalaureate-and-specialty"
S06_DETAIL_API_BASE_URL = "https://api.www.bmstu.ru/majors/"
ORDERS_MANIFEST_URL = "https://priem.bmstu.ru/lists/orders.json"
PUBLIC_PLAN_HOSTS = frozenset(("disk.yandex.ru", "clck.ru", "clck.su"))
PUBLIC_DOWNLOAD_HOST_SUFFIXES = (".yandex.ru", ".yandex.net")
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "tracer" / "raw"


@dataclass(frozen=True, slots=True)
class AdmissionOrderManifestEntry:
    """One validated item from the official ``lists/orders.json`` manifest."""

    title: str
    requested_url: str
    enabled: bool = True
    link: tuple[str, ...] = ()


def write_fixture(captured: CapturedSources, fixture_dir: Path) -> None:
    """Persist a captured source set with hashes and stable public provenance."""
    fixture_dir.mkdir(parents=True, exist_ok=True)
    snapshots: list[dict[str, object]] = []
    used_names: dict[str, int] = {}
    for snapshot in captured.snapshots:
        base_name = {
            "bmstu_common": "common",
            "bmstu_major_catalog": "catalog",
            "bmstu_major_detail": "detail",
            "bmstu_curriculum_document": "curriculum",
            "bmstu_admission_orders_index": "admission-orders",
            "bmstu_admission_orders_document": "admission-order",
        }.get(snapshot.source_kind, "source")
        index = used_names.get(base_name, 0)
        used_names[base_name] = index + 1
        suffix = f"_{index + 1}" if index else ""
        extension = ".pdf" if is_pdf(snapshot.body) else (".json" if snapshot.content_type and "json" in snapshot.content_type else ".html")
        body_path = f"{base_name}{suffix}{extension}"
        (fixture_dir / body_path).write_bytes(snapshot.body)
        snapshots.append(
            {
                "source_kind": snapshot.source_kind,
                "requested_url": str(snapshot.requested_url),
                "final_url": str(snapshot.requested_url),
                "status_code": snapshot.status_code,
                "content_type": snapshot.content_type,
                "captured_at": snapshot.captured_at.isoformat(),
                "content_sha256": snapshot.content_sha256,
                "body_path": body_path,
            }
        )
    (fixture_dir / "source_manifest.json").write_text(
        json.dumps({"snapshots": snapshots}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class BmstuSource:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher(FetchConfig(browser_mode="auto"))
        self._owns_fetcher = fetcher is None
        self._capture_gaps: list[RawSourceGap] = []

    def close(self) -> None:
        if self._owns_fetcher:
            self.fetcher.close()

    def capture(self, mode: str = "fixture", fixture_dir: Path | None = None) -> CapturedSources:
        logger.info("source_capture_start mode=%s", mode)
        self._capture_gaps = []
        if mode == "fixture":
            captured = self._load_fixture(fixture_dir or DEFAULT_FIXTURE_DIR)
        elif mode == "live":
            captured = self._capture_live()
        else:
            raise ContractError(
                ErrorCode.VALIDATION_ERROR,
                "source mode must be fixture or live",
                [ErrorDetail(path="mode", message="unsupported source mode", type="value_error")],
            )
        logger.info("source_capture_complete snapshot_count=%d", len(captured.snapshots))
        return captured

    def _capture_live(self) -> CapturedSources:
        snapshots: list[RawSourceSnapshot] = []
        snapshots.append(self._fetch_snapshot("bmstu_common", S01_URL))
        snapshots.append(self._fetch_snapshot("bmstu_major_catalog", S06_CATALOG_URL))
        catalog_items: list[JsonObject] = []
        offset = 0
        page_size = 100
        while True:
            url = f"{S06_API_BASE_URL}?limit={page_size}&offset={offset}"
            page_snapshot = self._fetch_snapshot("bmstu_major_catalog", url)
            snapshots.append(page_snapshot)
            page_items, total = _catalog_page(page_snapshot.body)
            catalog_items.extend(page_items)
            if not page_items:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU catalog page is empty before meta.count")
            previous_offset = offset
            offset += len(page_items)
            if offset >= total:
                break
            if offset <= previous_offset:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU catalog pagination made no progress")

        slugs: list[str] = []
        for index, item in enumerate(catalog_items, start=1):
            slug = _text(item.get("slug"))
            if not slug:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"BMSTU catalog card {index} has no detail slug")
            slugs.append(slug)
        if len(slugs) != len(set(slugs)):
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU catalog contains duplicate slugs")
        detail_snapshots: list[RawSourceSnapshot] = []
        plan_urls: list[str] = []
        for slug in slugs:
            detail_url = S06_DETAIL_API_BASE_URL + quote(slug, safe="")
            detail_snapshot = self._fetch_snapshot("bmstu_major_detail", detail_url)
            detail_snapshots.append(detail_snapshot)
            plan_urls.extend(_detail_plan_urls(detail_snapshot.body))
        snapshots.extend(detail_snapshots)

        for plan_url in dict.fromkeys(plan_urls):
            snapshots.extend(self._fetch_public_documents(plan_url))
        orders_manifest = self._fetch_snapshot("bmstu_admission_orders_index", ORDERS_MANIFEST_URL)
        snapshots.append(orders_manifest)
        orders = parse_orders_manifest(orders_manifest.body, ORDERS_MANIFEST_URL)
        logger.info(
            "orders_manifest_fetched url=%s documents=%d updated=%s",
            ORDERS_MANIFEST_URL,
            len(orders),
            _orders_updated_at(orders_manifest.body),
        )
        for entry in orders:
            snapshots.append(self._fetch_snapshot("bmstu_admission_orders_document", str(entry.requested_url)))
        logger.info(
            "orders_documents_fetched documents=%d urls=%d",
            len(orders),
            len({str(entry.requested_url) for entry in orders}),
        )
        selection_logger.info(
            "catalog_discovered cards=%d details=%d profiles=%d unique_plans=%d",
            len(catalog_items),
            len(detail_snapshots),
            sum(len(_detail_profiles(snapshot.body)) for snapshot in detail_snapshots),
            len(set(plan_urls)),
        )
        return CapturedSources(tuple(snapshots), source_gaps=tuple(self._capture_gaps))

    def _fetch_public_documents(self, public_url: str) -> tuple[RawSourceSnapshot, ...]:
        if not _is_supported_public_plan_url(public_url):
            selection_logger.warning("study_plan_host_rejected plan_url=%s", public_url)
            self._capture_gaps.append(source_fetch_gap("bmstu_curriculum_metadata", public_url, "unsupported_source_host"))
            return ()
        if "disk.yandex.ru/" in public_url:
            resolved_url = public_url.split("?", 1)[0]
        else:
            fetch_http = getattr(self.fetcher, "fetch_http", None)
            resolver_resource = fetch_http(public_url) if fetch_http is not None else self.fetcher.fetch(public_url)
            resolved_url = _public_resource_url(resolver_resource, public_url)
        metadata_url = "https://cloud-api.yandex.net/v1/disk/public/resources?public_key=" + quote(resolved_url, safe="")
        metadata = self.fetcher.fetch_http(metadata_url)
        if metadata.error or not metadata.body:
            selection_logger.warning("study_plan_metadata_unavailable plan_url=%s", public_url)
            self._capture_gaps.append(source_fetch_gap("bmstu_curriculum_metadata", public_url, metadata.error_code or "source_unavailable"))
            return ()
        payload = _json_object(metadata.body)
        embedded = _object(payload.get("_embedded"))
        items = _list(embedded.get("items")) if embedded else []
        direct_urls: list[str] = []
        top_level_file = _text(payload.get("file"))
        if top_level_file:
            direct_urls.append(top_level_file)
        for item in items:
            item_object = _object(item)
            if item_object is None:
                continue
            direct_url = _text(item_object.get("file"))
            if direct_url:
                direct_urls.append(direct_url)
        metadata_snapshot = self._snapshot("bmstu_curriculum_metadata", public_url, metadata)
        if not direct_urls:
            selection_logger.warning("study_plan_document_unavailable plan_url=%s resource_type=%s", public_url, payload.get("type"))
            self._capture_gaps.append(source_fetch_gap("bmstu_curriculum_document", public_url, "document_missing"))
            return (metadata_snapshot,)
        snapshots = [metadata_snapshot]
        for direct_url in dict.fromkeys(direct_urls):
            if not _is_supported_download_url(direct_url):
                selection_logger.warning("study_plan_download_host_rejected plan_url=%s", public_url)
                self._capture_gaps.append(source_fetch_gap("bmstu_curriculum_document", public_url, "download_host_rejected"))
                continue
            resource = self.fetcher.fetch_http(direct_url)
            if resource.error or not resource.body:
                selection_logger.warning("study_plan_download_failed plan_url=%s", public_url)
                self._capture_gaps.append(source_fetch_gap("bmstu_curriculum_document", public_url, resource.error_code or "download_unavailable"))
                continue
            snapshots.append(self._snapshot("bmstu_curriculum_document", public_url, resource))
        return tuple(snapshots)

    def _fetch_snapshot(self, kind: str, url: str) -> RawSourceSnapshot:
        fetch_http = getattr(self.fetcher, "fetch_http", None)
        resource = (
            fetch_http(url)
            if fetch_http is not None and _requires_http_fetch(url)
            else self.fetcher.fetch(url)
        )
        return self._snapshot(kind, url, resource)

    @staticmethod
    def _snapshot(kind: str, public_url: str, resource: FetchedResource) -> RawSourceSnapshot:
        if resource.error or resource.status_code is None or not resource.body:
            raise ContractError(
                ErrorCode.SOURCE_CONTRACT_ERROR,
                f"Source fetch failed for {public_url}: {resource.error_code or resource.error or 'unknown'}",
                [ErrorDetail(path="source", message=resource.error_code or resource.error or "source returned no valid body", type="source_fetch")],
            )
        digest = sha256(resource.body).hexdigest()
        logger.info(
            "source_fetched kind=%s host_path=%s status=%s bytes=%d sha256=%s access_mode=%s",
            kind,
            public_url.split("?", 1)[0],
            resource.status_code,
            len(resource.body),
            digest,
            resource.access_mode,
        )
        return RawSourceSnapshot(
            source_kind=kind,
            requested_url=http_url(public_url),
            final_url=http_url(resource.final_url or public_url),
            status_code=resource.status_code,
            content_type=resource.content_type,
            captured_at=datetime.fromisoformat(resource.fetched_at),
            content_sha256=digest,
            body=resource.body,
            response_class="success",
            access_mode=resource.access_mode,
            truncated=resource.truncated,
        )

    @staticmethod
    def _load_fixture(fixture_dir: Path) -> CapturedSources:
        manifest_path = fixture_dir / "source_manifest.json"
        if not manifest_path.exists():
            raise ContractError(
                ErrorCode.SOURCE_CONTRACT_ERROR,
                f"Source fixture manifest not found: {manifest_path}",
                [ErrorDetail(path="fixture_dir", message="missing source_manifest.json", type="source_fixture")],
            )
        manifest = _json_object(manifest_path.read_bytes())
        snapshots_value = _list(manifest.get("snapshots"))
        snapshots: list[RawSourceSnapshot] = []
        for index, value in enumerate(snapshots_value):
            item = _object(value)
            if item is None:
                raise ContractError(
                    ErrorCode.SOURCE_CONTRACT_ERROR,
                    "Fixture manifest contains a non-object snapshot",
                    [ErrorDetail(path=f"snapshots[{index}]", message="object expected", type="source_fixture")],
                )
            body_path = _text(item.get("body_path"))
            if not body_path:
                raise ContractError(
                    ErrorCode.SOURCE_CONTRACT_ERROR,
                    "Fixture snapshot has no body path",
                    [ErrorDetail(path=f"snapshots[{index}].body_path", message="required", type="source_fixture")],
                )
            body_file = (fixture_dir / body_path).resolve()
            if fixture_dir.resolve() not in body_file.parents:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Fixture body path escapes fixture directory")
            body = body_file.read_bytes()
            digest = sha256(body).hexdigest()
            expected = _text(item.get("content_sha256"))
            if digest != expected:
                raise ContractError(
                    ErrorCode.SOURCE_CONTRACT_ERROR,
                    "Fixture body hash does not match manifest",
                    [ErrorDetail(path=f"snapshots[{index}].content_sha256", message="hash mismatch", type="source_fixture")],
                )
            snapshots.append(
                RawSourceSnapshot(
                    source_kind=_required_text(item, "source_kind", index),
                    requested_url=http_url(_required_text(item, "requested_url", index)),
                    final_url=http_url(_required_text(item, "final_url", index)),
                    status_code=_required_int(item, "status_code", index),
                    content_type=_text(item.get("content_type")),
                    captured_at=_required_datetime(item, "captured_at", index),
                    content_sha256=digest,
                    body=body,
                )
            )
        return CapturedSources(tuple(snapshots))


def _catalog_page(body: bytes) -> tuple[list[JsonObject], int]:
    root = _json_object(body)
    values = _list(root.get("data"))
    meta = _object(root.get("meta"))
    total = meta.get("count") if meta is not None else None
    if not isinstance(total, int) or total < len(values):
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU catalog response has invalid meta.count")
    items: list[JsonObject] = []
    for value in values:
        item = _object(value)
        if item is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU catalog response contains a non-object item")
        items.append(item)
    return items, total


def parse_orders_manifest(body: bytes, manifest_url: str) -> tuple[AdmissionOrderManifestEntry, ...]:
    """Parse the public BMSTU orders manifest without selecting filenames."""

    root = _json_object(body)
    raw_items = root.get("list")
    if not isinstance(raw_items, list):
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU orders manifest list must be an array")
    result: list[AdmissionOrderManifestEntry] = []
    seen_urls: set[str] = set()
    for index, value in enumerate(raw_items):
        item = _object(value)
        if item is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"BMSTU orders manifest item {index} must be an object")
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"BMSTU orders manifest enabled flag {index} must be boolean")
        if not enabled:
            continue
        title = _text(item.get("title"))
        raw_href = _text(item.get("href")) or _text(item.get("data"))
        if not title or not raw_href:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"BMSTU orders manifest item {index} is incomplete")
        resolved = urljoin(str(manifest_url), raw_href)
        parsed = urlparse(resolved)
        if parsed.scheme != "https" or parsed.hostname != "priem.bmstu.ru":
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"BMSTU orders manifest item {index} has an unsafe URL")
        if resolved in seen_urls:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"BMSTU orders manifest contains duplicate URL: {resolved}")
        seen_urls.add(resolved)
        links = item.get("link")
        link_values = (
            (links.strip(),)
            if isinstance(links, str) and links.strip()
            else tuple(link.strip() for link in links if isinstance(link, str) and link.strip())
            if isinstance(links, list)
            else ()
        )
        result.append(AdmissionOrderManifestEntry(title=title, requested_url=resolved, link=link_values))
    if not result:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU orders manifest has no enabled documents")
    return tuple(result)


def _requires_http_fetch(url: str) -> bool:
    return "api.www.bmstu.ru" in url or "cloud-api.yandex.net" in url or "priem.bmstu.ru/lists/" in url


def _orders_updated_at(body: bytes) -> str:
    try:
        root = _json_object(body)
    except ContractError:
        return "unknown"
    value = root.get("updatedAt")
    return str(value) if isinstance(value, (int, float, str)) else "unknown"


def _detail_plan_urls(body: bytes) -> list[str]:
    return [plan for _, _, plan in _detail_plan_records(body)]


def _detail_profiles(body: bytes) -> list[JsonObject]:
    return [{"code": code, "name": name, "plan": plan} for code, name, plan in _detail_plan_records(body)]


def _detail_plan_records(body: bytes) -> list[tuple[str, str, str]]:
    root: JsonObject
    try:
        root = _json_object(body)
    except ContractError:
        soup = BeautifulSoup(body, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "S06 detail has neither JSON nor __NEXT_DATA__")
        root = _json_object(script.string.encode("utf-8"))
    data = _detail_data(root)
    chairs = _object(data.get("chairs"))
    result: list[tuple[str, str, str]] = []
    for chair_value in _list(chairs.get("items")) if chairs else []:
        chair = _object(chair_value)
        if chair is None:
            continue
        educational = _object(chair.get("educationalProgram"))
        for program_value in _list(educational.get("items")) if educational else []:
            program = _object(program_value)
            if program is None:
                continue
            code = _text(program.get("code"))
            name = _text(program.get("name"))
            plan = _text(program.get("plan"))
            if code and name and plan:
                result.append((code, unescape(name), plan))
    return result


def _detail_data(root: JsonObject) -> JsonObject:
    if _object(root.get("additional")) or _object(root.get("chairs")):
        return root
    direct = _object(root.get("data"))
    if direct and (_object(direct.get("additional")) or _object(direct.get("chairs"))):
        return direct
    props = _object(root.get("props"))
    initial_state = _object(props.get("initialState")) if props else None
    details = _object(initial_state.get("bachelorMajorsDetails")) if initial_state else None
    data = _object(details.get("data")) if details else None
    return data or {}


def _public_resource_url(resource: FetchedResource, fallback: str) -> str:
    candidate = resource.final_url.split("?", 1)[0] if "disk.yandex.ru/" in resource.final_url else ""
    if candidate:
        return candidate
    matches = re.findall(r"https://disk\.yandex\.ru/(?:d|i)/[A-Za-z0-9_-]+", resource.body.decode("utf-8", errors="ignore"))
    return matches[0] if matches else fallback


def _is_supported_public_plan_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname in PUBLIC_PLAN_HOSTS


def _is_supported_download_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = parsed.hostname or ""
    return parsed.scheme == "https" and any(hostname == suffix[1:] or hostname.endswith(suffix) for suffix in PUBLIC_DOWNLOAD_HOST_SUFFIXES)


def _canonical_code(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("–", "-").replace("—", "-").replace("/", "-").replace(" ", "")


def _json_object(body: bytes) -> JsonObject:
    try:
        value: JsonValue = cast(JsonValue, json.loads(body.decode("utf-8-sig")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Source JSON is malformed") from exc
    result = _object(value)
    if result is None:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Source JSON root must be an object")
    return result


def _object(value: JsonValue | object) -> JsonObject | None:
    return value if isinstance(value, dict) else None


def _list(value: JsonValue | object) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def _text(value: JsonValue | object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _required_text(item: JsonObject, key: str, index: int) -> str:
    value = _text(item.get(key))
    if not value:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Fixture field {key} is missing at index {index}")
    return value


def _required_int(item: JsonObject, key: str, index: int) -> int:
    value = item.get(key)
    if not isinstance(value, int):
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Fixture field {key} must be an integer at index {index}")
    return value


def _required_datetime(item: JsonObject, key: str, index: int) -> datetime:
    value = _required_text(item, key, index)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Fixture field {key} is not an ISO datetime") from exc


__all__ = [
    "AdmissionOrderManifestEntry",
    "BmstuSource",
    "CapturedSources",
    "DEFAULT_FIXTURE_DIR",
    "ORDERS_MANIFEST_URL",
    "S01_URL",
    "S06_API_BASE_URL",
    "S06_CATALOG_URL",
    "S06_DETAIL_API_BASE_URL",
    "_catalog_page",
    "_detail_plan_records",
    "_is_supported_download_url",
    "_is_supported_public_plan_url",
    "parse_orders_manifest",
    "write_fixture",
]
