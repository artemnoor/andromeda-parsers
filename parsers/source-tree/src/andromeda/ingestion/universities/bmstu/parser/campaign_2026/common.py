from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlparse

from .....fetch_policy import SourceHostPolicy
from ...fetch import FetchConfig, Fetcher


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = unquote(str(value)).replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_code(value: object) -> str:
    return re.sub(r"\s+", "", clean_text(value)).replace("–", "-").replace("—", "-").replace("−", "-")


def slug(value: str, limit: int = 72) -> str:
    text = re.sub(r"[^A-Za-zА-Яа-яЁё0-9._-]+", "_", clean_text(value)).strip("._-")
    return (text or "source")[:limit]


def jsonl_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


@dataclass(frozen=True, slots=True)
class CapturedArtifact:
    source_key: str
    source_type: str
    requested_url: str
    final_url: str
    retrieved_at: str
    status_code: int
    content_type: str | None
    sha256: str
    byte_size: int
    raw_path: str | None
    storage_status: str
    note: str | None = None


class CaptureStore:
    """Fetch only links from official BMSTU pages and preserve byte evidence."""

    def __init__(self, bundle_root: Path) -> None:
        self.bundle_root = bundle_root
        self.raw_root = bundle_root / "raw" / "files"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.fetcher = Fetcher(FetchConfig(browser_mode="never", max_body_bytes=30_000_000))
        self.artifacts: dict[str, CapturedArtifact] = {}
        self._bodies: dict[str, bytes] = {}

    def close(self) -> None:
        self.fetcher.close()

    def get(
        self,
        url: str,
        source_type: str,
        *,
        save: bool = True,
        name: str | None = None,
        note: str | None = None,
        omission_status: str = "omitted_privacy_sensitive_applicant_records",
    ) -> tuple[CapturedArtifact, bytes]:
        return self._get_with_fetcher(url, source_type, self.fetcher, save=save, name=name, note=note, omission_status=omission_status)

    def get_verified_external(
        self,
        url: str,
        source_type: str,
        *,
        verified_domains: set[str],
        save: bool = True,
        name: str | None = None,
        note: str | None = None,
        omission_status: str = "omitted_privacy_sensitive_applicant_records",
    ) -> tuple[CapturedArtifact, bytes]:
        """Fetch a URL only when its host came from an official organizer index."""
        external = Fetcher(FetchConfig(browser_mode="never", max_body_bytes=30_000_000))
        external.policy = replace(
            external.policy,
            host_policy=SourceHostPolicy(allowed_hosts=frozenset(host.casefold().rstrip(".") for host in verified_domains)),
        )
        try:
            return self._get_with_fetcher(url, source_type, external, save=save, name=name, note=note, omission_status=omission_status)
        finally:
            external.close()

    def _get_with_fetcher(
        self,
        url: str,
        source_type: str,
        fetcher: Fetcher,
        *,
        save: bool,
        name: str | None,
        note: str | None,
        omission_status: str,
    ) -> tuple[CapturedArtifact, bytes]:
        if url in self.artifacts:
            artifact = self.artifacts[url]
            if artifact.source_type != source_type:
                raise ValueError(f"one URL was assigned incompatible source types: {url}")
            if not save and artifact.storage_status == "saved":
                raise ValueError(f"source was already persisted but is now marked for omission: {url}")
            body = self._bodies.get(url, b"")
            if not body and artifact.raw_path:
                body = (self.bundle_root / artifact.raw_path).read_bytes()
            return artifact, body

        resource = fetcher.fetch_http(url)
        if resource.error or resource.status_code is None or not resource.body or not 200 <= resource.status_code < 300:
            digest = sha256(resource.body).hexdigest() if resource.body else ""
            self.artifacts[url] = CapturedArtifact(
                source_key=f"source_artifact:url-sha256:{sha256(url.encode('utf-8')).hexdigest()}",
                source_type=source_type,
                requested_url=url,
                final_url=resource.final_url or url,
                retrieved_at=resource.fetched_at or utc_now(),
                status_code=resource.status_code or 0,
                content_type=resource.content_type,
                sha256=digest,
                byte_size=len(resource.body),
                raw_path=None,
                storage_status="not_captured",
                note=f"fetch_error={resource.error_code or 'empty_response'}",
            )
            self._bodies[url] = resource.body
            raise RuntimeError(f"official source fetch failed ({resource.error_code or resource.status_code}): {url}")
        digest = sha256(resource.body).hexdigest()
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix.lower()
        if not ext:
            content_type = (resource.content_type or "").split(";", 1)[0].lower()
            ext = {"text/html": ".html", "application/json": ".json", "application/pdf": ".pdf"}.get(content_type, ".bin")
        raw_path = None
        if save:
            base = slug(name or Path(parsed.path).stem or parsed.hostname or "source")
            filename = f"{sha256(url.encode('utf-8')).hexdigest()[:12]}_{base}{ext}"
            path = self.raw_root / filename
            path.write_bytes(resource.body)
            raw_path = path.relative_to(self.bundle_root).as_posix()
        artifact = CapturedArtifact(
            source_key=f"source_artifact:url-sha256:{sha256(url.encode('utf-8')).hexdigest()}",
            source_type=source_type,
            requested_url=url,
            final_url=resource.final_url or url,
            retrieved_at=resource.fetched_at or utc_now(),
            status_code=resource.status_code,
            content_type=resource.content_type,
            sha256=digest,
            byte_size=len(resource.body),
            raw_path=raw_path,
            storage_status="saved" if save else omission_status,
            note=note,
        )
        self.artifacts[url] = artifact
        self._bodies[url] = resource.body
        return artifact, resource.body

    def add_local_file(
        self,
        path: Path,
        *,
        source_type: str,
        local_reference: str,
        name: str | None = None,
        note: str | None = None,
    ) -> CapturedArtifact:
        """Copy a user-provided local source into the bundle with byte provenance."""
        body = path.read_bytes()
        digest = sha256(body).hexdigest()
        filename = f"{sha256(local_reference.encode('utf-8')).hexdigest()[:12]}_{slug(name or path.stem)}{path.suffix.lower()}"
        output = self.raw_root / filename
        output.write_bytes(body)
        artifact = CapturedArtifact(
            source_key=f"source_artifact:url-sha256:{sha256(local_reference.encode('utf-8')).hexdigest()}",
            source_type=source_type,
            requested_url=local_reference,
            final_url=local_reference,
            retrieved_at=utc_now(),
            status_code=200,
            content_type="application/pdf" if path.suffix.lower() == ".pdf" else None,
            sha256=digest,
            byte_size=len(body),
            raw_path=output.relative_to(self.bundle_root).as_posix(),
            storage_status="saved",
            note=note,
        )
        self.artifacts[local_reference] = artifact
        self._bodies[local_reference] = body
        return artifact

    def write_manifest(self) -> None:
        jsonl_write(self.bundle_root / "source_artifacts.jsonl", [asdict(item) for item in self.artifacts.values()])


def evidence(artifact: CapturedArtifact, locator: str | None = None) -> dict[str, Any]:
    return {
        "source_artifact_key": artifact.source_key,
        "url": artifact.requested_url,
        "sha256": artifact.sha256,
        "locator": locator,
    }
