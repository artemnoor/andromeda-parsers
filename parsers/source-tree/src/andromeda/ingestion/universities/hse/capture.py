from __future__ import annotations

import json
import logging
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urljoin

from andromeda.ingestion.contracts.constraints import http_url
from andromeda.ingestion.contracts.raw import JsonObject, JsonValue, RawSourceGap, RawSourceSnapshot
from andromeda.ingestion.contracts.source import CapturedSources, source_fetch_gap
from andromeda.shared.contracts.errors import ContractError, ErrorCode, ErrorDetail

from .fetch import Fetcher
from .html import extract_links, official_hse_url
from .parser.catalog import discover_program_links, study_plan_urls
from .pdf import is_pdf
from .source_models import FetchedResource


logger = logging.getLogger("andromeda.ingestion.hse.capture")
selection_logger = logging.getLogger("andromeda.ingestion.hse.select")

CATALOG_URL = "https://admissions.hse.ru/undergraduate-apply/programmes_list"
COMMON_URL = "https://www.hse.ru/contacts/"
ADMISSION_ROOT_URL = "https://ba.hse.ru/"
MINIMUMS_URL = "https://ba.hse.ru/minkrit"
PLACES_URL = "https://ba.hse.ru/kolmest"
TUITION_URL = "https://ba.hse.ru/price"
ENROLLMENT_INDEX_URLS = (
    "https://ba.hse.ru/enrolled?d=ba",
    "https://spb.hse.ru/ba/finlist",
    "https://nnov.hse.ru/bacnn/finlist",
    "https://perm.hse.ru/bacalavr/prikaz26",
)
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "hse" / "raw"


class HseSource:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher()
        self._owns_fetcher = fetcher is None
        self._capture_gaps: list[RawSourceGap] = []

    def close(self) -> None:
        if self._owns_fetcher:
            self.fetcher.close()

    def capture(self, mode: str = "fixture", fixture_dir: Path | None = None) -> CapturedSources:
        logger.info("source_capture_start university=hse mode=%s", mode)
        self._capture_gaps = []
        if mode == "fixture":
            captured = self._load_fixture(fixture_dir or DEFAULT_FIXTURE_DIR)
        elif mode == "live":
            captured = self._capture_live()
        else:
            raise ContractError(ErrorCode.VALIDATION_ERROR, "source mode must be fixture or live", (ErrorDetail(path="mode", message="unsupported source mode", type="value_error"),))
        logger.info("source_capture_complete university=hse snapshots=%d", len(captured.snapshots))
        return captured

    def _capture_live(self) -> CapturedSources:
        snapshots: list[RawSourceSnapshot] = [self._required_snapshot("hse_common", COMMON_URL), self._required_snapshot("hse_program_catalog", CATALOG_URL)]
        catalog_snapshot = snapshots[-1]
        program_urls = discover_program_links(catalog_snapshot.body, str(catalog_snapshot.final_url))
        if not program_urls:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "HSE official catalog contains no program links")
        detail_urls = tuple(program_urls)
        selection_logger.info("catalog_discovered university=hse programs=%d", len(detail_urls))
        fetched_detail_urls: set[str] = set()
        curriculum_index_urls: set[str] = set()
        plan_urls: set[str] = set()
        for program_url in detail_urls:
            # HSE publishes the machine-readable direction code on the
            # programme's official admission passport, while the catalog link
            # itself is a marketing overview page. Keep the base URL for plan
            # discovery and capture the passport as the detail source.
            detail_url = program_url.rstrip("/") + "/admission/"
            snapshot = self._optional_snapshot("hse_program_detail", detail_url)
            if snapshot is None:
                snapshot = self._optional_snapshot("hse_program_detail", program_url)
            if snapshot is None:
                continue
            snapshots.append(snapshot)
            fetched_detail_urls.add(program_url)
            index_url = program_url.rstrip("/") + "/learn_plans/"
            curriculum_index_urls.add(index_url)
            index_snapshot = self._optional_snapshot("hse_curriculum_index", index_url)
            if index_snapshot is None:
                continue
            snapshots.append(index_snapshot)
            plan_urls.update(study_plan_urls(index_snapshot.body, str(index_snapshot.final_url)))
        for plan_url in sorted(plan_urls):
            if not official_hse_url(plan_url) or not ("/dbs/education/" in plan_url or "/mirror/pubs/share/" in plan_url):
                selection_logger.warning("study_plan_url_rejected url=%s", plan_url)
                continue
            snapshot = self._optional_snapshot("hse_curriculum_document", plan_url)
            if snapshot is not None:
                snapshots.append(snapshot)
        snapshots.extend(self._optional_snapshot_tuple("hse_admission_rules", MINIMUMS_URL))
        snapshots.extend(self._optional_snapshot_tuple("hse_admission_places", PLACES_URL))
        snapshots.extend(self._optional_snapshot_tuple("hse_tuition", TUITION_URL))
        admission_root = self._optional_snapshot("hse_passing_scores", ADMISSION_ROOT_URL)
        if admission_root is not None:
            snapshots.append(admission_root)
            result_urls = tuple(
                url
                for _, url in extract_links(admission_root.body, str(admission_root.final_url))
                if official_hse_url(url) and "/result20" in url
            )
            for url in dict.fromkeys(result_urls):
                result_snapshot = self._optional_snapshot("hse_passing_scores", url)
                if result_snapshot is not None:
                    snapshots.append(result_snapshot)
        for index_url in ENROLLMENT_INDEX_URLS:
            index_snapshot = self._optional_snapshot("hse_enrollment_index", index_url)
            if index_snapshot is None:
                continue
            snapshots.append(index_snapshot)
            document_urls = _enrollment_document_urls(index_snapshot.body, str(index_snapshot.final_url))
            for document_url in document_urls:
                document_snapshot = self._optional_snapshot("hse_enrollment_document", document_url)
                if document_snapshot is not None:
                    snapshots.append(document_snapshot)
        snapshots = _dedupe_snapshots(snapshots)
        logger.info(
            "source_capture_live_complete university=hse detail_pages=%d curriculum_indexes=%d plans=%d snapshots=%d",
            len(fetched_detail_urls),
            len(curriculum_index_urls),
            len(plan_urls),
            len(snapshots),
        )
        return CapturedSources(tuple(snapshots), source_gaps=tuple(self._capture_gaps))

    def _required_snapshot(self, kind: str, url: str) -> RawSourceSnapshot:
        snapshot = self._optional_snapshot(kind, url)
        if snapshot is None:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"HSE source fetch failed for {url}")
        return snapshot

    def _optional_snapshot(self, kind: str, url: str) -> RawSourceSnapshot | None:
        if not official_hse_url(url):
            logger.warning("source_url_rejected kind=%s url=%s", kind, url)
            self._capture_gaps.append(source_fetch_gap(kind, url, "unsupported_source_host"))
            return None
        fetch_http = getattr(self.fetcher, "fetch_http", None)
        resource = fetch_http(url) if fetch_http is not None else self.fetcher.fetch(url)
        # HSE currently serves the official contacts payload inside its branded
        # contacts template with HTTP 404. Preserve that official body so the
        # identity parser can validate the address; every other failed source
        # remains fail-closed.
        acceptable_error_page = kind == "hse_common" and resource.status_code == 404 and bool(resource.body)
        if (resource.error and not acceptable_error_page) or resource.status_code is None or not resource.body or (resource.status_code >= 400 and not acceptable_error_page):
            logger.warning("source_fetch_gap kind=%s url=%s error=%s", kind, url, resource.error or resource.status_code)
            self._capture_gaps.append(source_fetch_gap(kind, url, resource.error_code or "source_unavailable"))
            return None
        if acceptable_error_page:
            logger.warning("[FIX:source-gap] official_contacts_payload_preserved status=404 url=%s", url)
        return self._snapshot(kind, url, resource)

    def _optional_snapshot_tuple(self, kind: str, url: str) -> tuple[RawSourceSnapshot, ...]:
        snapshot = self._optional_snapshot(kind, url)
        return (snapshot,) if snapshot is not None else ()

    @staticmethod
    def _snapshot(kind: str, requested_url: str, resource: FetchedResource) -> RawSourceSnapshot:
        digest = sha256(resource.body).hexdigest()
        logger.info("source_fetched university=hse kind=%s url=%s status=%s bytes=%d sha256=%s", kind, requested_url, resource.status_code, len(resource.body), digest)
        return RawSourceSnapshot(
            source_kind=kind,
            requested_url=http_url(requested_url),
            final_url=http_url(resource.final_url or requested_url),
            status_code=resource.status_code or 200,
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
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Source fixture manifest not found: {manifest_path}")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshots: list[RawSourceSnapshot] = []
        fixture_root = fixture_dir.resolve()
        for index, item in enumerate(payload.get("snapshots", [])):
            body_path = str(item["body_path"])
            body_file = (fixture_root / body_path).resolve()
            if fixture_root not in body_file.parents:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"HSE fixture body path escapes fixture directory: {body_path}")
            body = body_file.read_bytes()
            expected_hash = str(item.get("content_sha256", ""))
            actual_hash = sha256(body).hexdigest()
            if expected_hash != actual_hash:
                raise ContractError(
                    ErrorCode.SOURCE_CONTRACT_ERROR,
                    f"HSE fixture body hash does not match manifest at index {index}",
                    (ErrorDetail(path=f"snapshots[{index}].content_sha256", message="hash mismatch", type="source_fixture"),),
                )
            snapshots.append(RawSourceSnapshot(
                source_kind=str(item["source_kind"]),
                requested_url=http_url(str(item["requested_url"])),
                final_url=http_url(str(item.get("final_url", item["requested_url"]))),
                status_code=int(item.get("status_code", 200)),
                content_type=item.get("content_type"),
                captured_at=datetime.fromisoformat(str(item["captured_at"])),
                content_sha256=actual_hash,
                body=body,
            ))
        if not snapshots:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "HSE source fixture contains no snapshots")
        return CapturedSources(tuple(snapshots))


def write_fixture(captured: CapturedSources, fixture_dir: Path) -> None:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    used: dict[str, int] = {}
    manifest: list[dict[str, object]] = []
    for snapshot in captured.snapshots:
        base = snapshot.source_kind.replace("hse_", "", 1).replace("_", "-") or "source"
        index = used.get(base, 0) + 1
        used[base] = index
        suffix = f"_{index}" if index > 1 else ""
        extension = ".pdf" if is_pdf(snapshot.body, snapshot.content_type, str(snapshot.requested_url)) else ".html"
        filename = f"{base}{suffix}{extension}"
        (fixture_dir / filename).write_bytes(snapshot.body)
        manifest.append({"source_kind": snapshot.source_kind, "requested_url": str(snapshot.requested_url), "final_url": str(snapshot.final_url), "status_code": snapshot.status_code, "content_type": snapshot.content_type, "captured_at": snapshot.captured_at.isoformat(), "content_sha256": snapshot.content_sha256, "body_path": filename})
    (fixture_dir / "source_manifest.json").write_text(json.dumps({"snapshots": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _enrollment_document_urls(body: bytes, base_url: str) -> tuple[str, ...]:
    result: list[str] = []
    for _, url in extract_links(body, base_url):
        if official_hse_url(url) and ("/mirror/pubs/share/" in url or url.casefold().endswith(".pdf")) and url not in result:
            result.append(url)
    return tuple(result)


def _dedupe_snapshots(values: list[RawSourceSnapshot]) -> list[RawSourceSnapshot]:
    result: list[RawSourceSnapshot] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        key = (value.source_kind, str(value.requested_url), value.content_sha256)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


__all__ = ["CATALOG_URL", "HseSource", "write_fixture"]
