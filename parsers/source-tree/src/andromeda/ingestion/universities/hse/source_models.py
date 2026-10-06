from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class FetchedResource:
    requested_url: str
    final_url: str
    status_code: int | None
    content_type: str | None
    body: bytes
    fetched_at: str
    access_mode: str = "http"
    error: str | None = None
    error_code: str | None = None
    truncated: bool = False
    attempts: int = 1
    retry_class: str | None = None
    redirects: tuple[str, ...] = ()

    @property
    def content_hash(self) -> str:
        return sha256(self.body).hexdigest()

    @property
    def ok(self) -> bool:
        return bool(self.body) and self.status_code is not None and 200 <= self.status_code < 400 and not self.error
