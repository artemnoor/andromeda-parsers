"""Typed, bounded policies shared by university source fetchers.

The module deliberately contains no university host names.  Adapters own
their allowlists and pass them into these generic safety checks.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import ipaddress
import socket
from urllib.parse import urlparse, urljoin


class SourcePolicyError(ValueError):
    """A source URL or fetch limit violates the ingestion policy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


ResolveHost = Callable[[str], Sequence[str]]


@dataclass(frozen=True, slots=True)
class SourceHostPolicy:
    """Adapter-owned HTTPS host allowlist used for every redirect hop."""

    allowed_hosts: frozenset[str]
    allowed_suffixes: tuple[str, ...] = ()

    def allows(self, host: str) -> bool:
        normalized = host.casefold().rstrip(".")
        if normalized in self.allowed_hosts:
            return True
        return any(normalized.endswith(suffix.casefold()) for suffix in self.allowed_suffixes)


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    """Safe bounds for one adapter's HTTP/browser source profile."""

    host_policy: SourceHostPolicy
    timeout_seconds: float = 30.0
    retries: int = 2
    retry_delay_seconds: float = 0.8
    retry_max_delay_seconds: float = 8.0
    retry_after_max_seconds: float = 10.0
    total_budget_seconds: float = 90.0
    max_body_bytes: int = 30_000_000
    max_redirects: int = 5

    def __post_init__(self) -> None:
        if not 0.1 <= self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be between 0.1 and 120")
        if not 0 <= self.retries <= 5:
            raise ValueError("retries must be between 0 and 5")
        if not 0.0 <= self.retry_delay_seconds <= 30:
            raise ValueError("retry_delay_seconds must be between 0 and 30")
        if not 0.1 <= self.retry_max_delay_seconds <= 60:
            raise ValueError("retry_max_delay_seconds must be between 0.1 and 60")
        if not 0.0 <= self.retry_after_max_seconds <= 120:
            raise ValueError("retry_after_max_seconds must be between 0 and 120")
        if not self.timeout_seconds <= self.total_budget_seconds <= 600:
            raise ValueError("total_budget_seconds must cover timeout and be at most 600")
        if not 1_024 <= self.max_body_bytes <= 100_000_000:
            raise ValueError("max_body_bytes must be between 1 KiB and 100 MB")
        if not 0 <= self.max_redirects <= 8:
            raise ValueError("max_redirects must be between 0 and 8")


def validate_source_url(
    url: str,
    policy: SourceHostPolicy,
    *,
    resolver: ResolveHost | None = None,
) -> None:
    """Validate scheme, host, port, allowlist, and resolved IP safety.

    ``resolver`` is injectable so tests never need external DNS.  Production
    callers use ``socket.getaddrinfo`` and therefore reject private, reserved,
    loopback, link-local, metadata-like, and otherwise non-global addresses.
    """

    parsed = urlparse(url)
    if parsed.scheme.casefold() != "https":
        raise SourcePolicyError("https_required", "source URL must use HTTPS")
    if parsed.username or parsed.password:
        raise SourcePolicyError("credentials_in_url", "source URL must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SourcePolicyError("invalid_port", "source URL contains an invalid port") from exc
    if port not in (None, 443):
        raise SourcePolicyError("non_standard_port", "source URL must use the HTTPS port")
    host = (parsed.hostname or "").casefold().rstrip(".")
    if not host or not policy.allows(host):
        raise SourcePolicyError("host_not_allowed", "source host is not in the adapter allowlist")

    addresses = _resolve_host(host, resolver)
    if not addresses:
        raise SourcePolicyError("dns_resolution_failed", "source host did not resolve")
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise SourcePolicyError("invalid_dns_address", "source host resolved to an invalid address") from exc
        if not parsed_address.is_global:
            raise SourcePolicyError("private_target", "source host resolved to a non-public address")


def resolve_redirect(current_url: str, location: str, policy: SourceHostPolicy, *, resolver: ResolveHost | None = None) -> str:
    """Resolve and validate one redirect before the next network request."""

    if not location.strip():
        raise SourcePolicyError("redirect_missing", "source redirect has no location")
    target = urljoin(current_url, location)
    validate_source_url(target, policy, resolver=resolver)
    return target


def retry_after_seconds(value: str | None, *, now: Callable[[], datetime] | None = None) -> float | None:
    """Parse a numeric or HTTP-date Retry-After header."""

    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        current = now() if now is not None else datetime.now(timezone.utc)
        seconds = (target - current).total_seconds()
    return max(0.0, seconds)


def retry_class_for_status(status_code: int) -> str | None:
    if status_code == 429:
        return "http_429"
    if 500 <= status_code <= 599:
        return "http_5xx"
    return None


def safe_url_for_log(url: str) -> str:
    """Return a URL without query, fragment, user info, or credentials."""

    parsed = urlparse(url)
    host = parsed.hostname or "unknown"
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = host if port is None else f"{host}:{port}"
    return f"{parsed.scheme.casefold()}://{netloc}{parsed.path or '/'}"


def _resolve_host(host: str, resolver: ResolveHost | None) -> tuple[str, ...]:
    if resolver is not None:
        return tuple(resolver(host))
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SourcePolicyError("dns_resolution_failed", "source host could not be resolved") from exc
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


__all__ = [
    "FetchPolicy",
    "ResolveHost",
    "SourceHostPolicy",
    "SourcePolicyError",
    "resolve_redirect",
    "retry_after_seconds",
    "retry_class_for_status",
    "safe_url_for_log",
    "validate_source_url",
]
