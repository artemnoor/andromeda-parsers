from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(body: bytes) -> str:
    return sha256(body).hexdigest()


@dataclass(slots=True)
class SourceDefinition:
    """Minimal source metadata needed by BMSTU parser stages."""

    id: str
    name: str
    url: str
    officiality: str | None = None
    scope: str | None = None
    format: str | None = None
    availability: str | None = None
    method: str | None = None
    data_description: str | None = None
    history: str | None = None
    refresh: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FetchedResource:
    """Fetched body plus safe provenance used before raw snapshot validation."""

    requested_url: str
    final_url: str
    status_code: int | None
    content_type: str | None
    body: bytes
    fetched_at: str
    access_mode: str = "http"
    encoding: str | None = None
    network_payloads: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    truncated: bool = False
    attempts: int = 1
    retry_class: str | None = None
    redirects: tuple[str, ...] = ()

    @property
    def content_hash(self) -> str:
        return content_hash(self.body)

    @property
    def ok(self) -> bool:
        return bool(self.body) and self.status_code is not None and 200 <= self.status_code < 400 and not self.error

    def snapshot_dict(self, path: str | None = None) -> dict[str, Any]:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "fetched_at": self.fetched_at,
            "access_mode": self.access_mode,
            "encoding": self.encoding,
            "content_hash": self.content_hash if self.body else None,
            "bytes": len(self.body),
            "path": path,
            "network_payload_count": len(self.network_payloads),
            "error": self.error,
            "error_code": self.error_code,
            "truncated": self.truncated,
            "attempts": self.attempts,
            "retry_class": self.retry_class,
            "redirect_count": len(self.redirects),
        }


__all__ = ["FetchedResource", "SourceDefinition", "content_hash", "utc_now"]
