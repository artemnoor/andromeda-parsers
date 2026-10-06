from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from time import monotonic, sleep
from typing import Any
from urllib.parse import urljoin

import httpx

from andromeda.ingestion.fetch_policy import (
    FetchPolicy,
    ResolveHost,
    SourceHostPolicy,
    SourcePolicyError,
    resolve_redirect,
    retry_after_seconds,
    retry_class_for_status,
    safe_url_for_log,
    validate_source_url,
)

from .html import extract_text, is_blocked_page, is_js_shell
from .source_models import FetchedResource, utc_now


logger = logging.getLogger("andromeda.ingestion.bmstu.fetch")


BMSTU_SOURCE_HOST_POLICY = SourceHostPolicy(
    allowed_hosts=frozenset(
        {
            "bmstu.ru",
            "www.bmstu.ru",
            "mirror.bmstu.ru",
            "api.www.bmstu.ru",
            "api.mirror.bmstu.ru",
            "priem.bmstu.ru",
            "course.bmstu.ru",
            "isot.bmstu.ru",
            "rsr-olymp.ru",
            "disk.yandex.ru",
            "clck.ru",
            "clck.su",
            "cloud-api.yandex.net",
        }
    ),
    allowed_suffixes=(".yandex.ru", ".yandex.net"),
)


@dataclass(slots=True)
class FetchConfig:
    timeout_seconds: float = 30.0
    retries: int = 2
    user_agent: str = "Andromeda-BMSTU-Parser/0.1 (+research; contact owner)"
    browser_mode: str = "auto"
    max_body_bytes: int = 30_000_000
    retry_delay_seconds: float = 0.8
    retry_max_delay_seconds: float = 8.0
    retry_after_max_seconds: float = 10.0
    total_budget_seconds: float = 90.0
    max_redirects: int = 5

    def as_policy(self) -> FetchPolicy:
        return FetchPolicy(
            host_policy=BMSTU_SOURCE_HOST_POLICY,
            timeout_seconds=self.timeout_seconds,
            retries=self.retries,
            retry_delay_seconds=self.retry_delay_seconds,
            retry_max_delay_seconds=self.retry_max_delay_seconds,
            retry_after_max_seconds=self.retry_after_max_seconds,
            total_budget_seconds=self.total_budget_seconds,
            max_body_bytes=self.max_body_bytes,
            max_redirects=self.max_redirects,
        )


class Fetcher:
    def __init__(
        self,
        config: FetchConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: ResolveHost | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        clock_fn: Callable[[], float] | None = None,
    ) -> None:
        self.config = config or FetchConfig()
        self.policy = self.config.as_policy()
        self._resolver = resolver
        self._sleep = sleep_fn or sleep
        self._clock = clock_fn or monotonic
        client_kwargs: dict[str, Any] = {
            "follow_redirects": False,
            "timeout": self.config.timeout_seconds,
            "headers": {
                "User-Agent": self.config.user_agent,
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        self.client = httpx.Client(**client_kwargs)

    def close(self) -> None:
        self.client.close()

    def fetch(self, url: str, force_browser: bool = False) -> FetchedResource:
        direct = self._fetch_http(url)
        should_use_browser = force_browser or self.config.browser_mode == "always" or (
            self.config.browser_mode == "auto"
            and (
                direct.status_code in {401, 403, 429}
                or is_js_shell(extract_text(direct.body), direct.body)
                or is_blocked_page(extract_text(direct.body), direct.body)
            )
        )
        if not should_use_browser:
            return direct

        try:
            from .browser import fetch_with_browser

            browser_result = fetch_with_browser(
                url,
                timeout_seconds=self.config.timeout_seconds,
                max_body_bytes=self.config.max_body_bytes,
                policy=self.policy.host_policy,
                resolver=self._resolver,
            )
            if browser_result.body:
                return browser_result
            direct.error = browser_result.error or "browser_empty_body"
            direct.error_code = browser_result.error_code or "browser_empty_body"
        except Exception:  # Browser is deliberately optional and bounded.
            direct.error = "browser_unavailable"
            direct.error_code = "browser_unavailable"
        return direct

    def fetch_http(self, url: str) -> FetchedResource:
        """Fetch a resource without browser fallback.

        Machine-readable metadata and immutable PDF downloads must not start a
        browser session merely because a CDN response resembles a JS shell.
        """
        return self._fetch_http(url)

    def _fetch_http(self, url: str) -> FetchedResource:
        started = self._clock()
        try:
            validate_source_url(url, self.policy.host_policy, resolver=self._resolver)
        except SourcePolicyError as exc:
            return self._failure(url, url, None, exc.code, attempts=0)

        current_url = url
        redirects: list[str] = []
        total_attempts = 0
        for redirect_count in range(self.policy.max_redirects + 1):
            for hop_attempt in range(self.policy.retries + 1):
                if self._clock() - started >= self.policy.total_budget_seconds:
                    return self._failure(
                        url,
                        current_url,
                        None,
                        "total_budget_exceeded",
                        attempts=total_attempts,
                        redirects=redirects,
                    )
                total_attempts += 1
                try:
                    response = self.client.get(current_url)
                except httpx.TimeoutException:
                    if self._should_retry(hop_attempt, started):
                        self._wait(hop_attempt, None, started)
                        continue
                    return self._failure(
                        url,
                        current_url,
                        None,
                        "retry_exhausted",
                        attempts=total_attempts,
                        retry_class="timeout",
                        redirects=redirects,
                    )
                except (httpx.HTTPError, OSError):
                    if self._should_retry(hop_attempt, started):
                        self._wait(hop_attempt, None, started)
                        continue
                    return self._failure(
                        url,
                        current_url,
                        None,
                        "retry_exhausted",
                        attempts=total_attempts,
                        retry_class="connection",
                        redirects=redirects,
                    )

                retry_class = retry_class_for_status(response.status_code)
                if retry_class is not None:
                    retry_after = retry_after_seconds(response.headers.get("retry-after"))
                    if self._should_retry(hop_attempt, started):
                        response.close()
                        self._wait(hop_attempt, retry_after, started)
                        continue
                    body, truncated = self._read_body(response)
                    return self._resource(
                        url,
                        current_url,
                        response,
                        body,
                        error_code="retry_exhausted",
                        retry_class=retry_class,
                        truncated=truncated,
                        attempts=total_attempts,
                        redirects=redirects,
                    )

                if 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    response.close()
                    redirect_target = urljoin(current_url, location or "")
                    try:
                        target = resolve_redirect(
                            current_url,
                            location or "",
                            self.policy.host_policy,
                            resolver=self._resolver,
                        )
                    except SourcePolicyError as exc:
                        logger.warning(
                            "source_redirect_rejected requested=%s current=%s target=%s status=%s code=%s",
                            safe_url_for_log(url),
                            safe_url_for_log(current_url),
                            safe_url_for_log(redirect_target),
                            response.status_code,
                            exc.code,
                        )
                        return self._failure(
                            url,
                            current_url,
                            response.status_code,
                            f"redirect_{exc.code}",
                            attempts=total_attempts,
                            redirects=redirects,
                        )
                    redirects.append(target)
                    current_url = target
                    break

                body, truncated = self._read_body(response)
                if truncated:
                    return self._resource(
                        url,
                        current_url,
                        response,
                        body,
                        error_code="response_body_truncated",
                        truncated=True,
                        attempts=total_attempts,
                        redirects=redirects,
                    )
                if response.status_code >= 400:
                    return self._resource(
                        url,
                        current_url,
                        response,
                        body,
                        error_code="http_error",
                        attempts=total_attempts,
                        redirects=redirects,
                    )
                if not body:
                    return self._resource(
                        url,
                        current_url,
                        response,
                        body,
                        error_code="empty_body",
                        attempts=total_attempts,
                        redirects=redirects,
                    )
                blocked = is_blocked_page(self._safe_text(body), body)
                return self._resource(
                    url,
                    current_url,
                    response,
                    body,
                    error_code="blocked_page" if blocked else None,
                    attempts=total_attempts,
                    redirects=redirects,
                )
            else:
                continue
            continue

        return self._failure(
            url,
            current_url,
            None,
            "redirect_limit_exceeded",
            attempts=total_attempts,
            redirects=redirects,
        )

    def _should_retry(self, hop_attempt: int, started: float) -> bool:
        return hop_attempt < self.policy.retries and self._clock() - started < self.policy.total_budget_seconds

    def _wait(self, hop_attempt: int, retry_after: float | None, started: float) -> None:
        delay = min(
            self.policy.retry_delay_seconds * (2**hop_attempt),
            self.policy.retry_max_delay_seconds,
        )
        if retry_after is not None:
            delay = max(delay, min(retry_after, self.policy.retry_after_max_seconds))
        remaining = self.policy.total_budget_seconds - (self._clock() - started)
        if remaining > 0:
            self._sleep(min(delay, remaining))

    def _read_body(self, response: httpx.Response) -> tuple[bytes, bool]:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.policy.max_body_bytes:
                    body_bytes = response.content[: self.policy.max_body_bytes]
                    response.close()
                    return body_bytes, True
            except ValueError:
                pass
        body = bytearray()
        try:
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > self.policy.max_body_bytes:
                    response.close()
                    return bytes(body[: self.policy.max_body_bytes]), True
        finally:
            response.close()
        return bytes(body), False

    def _resource(
        self,
        requested_url: str,
        final_url: str,
        response: httpx.Response,
        body: bytes,
        *,
        error_code: str | None,
        attempts: int,
        retry_class: str | None = None,
        truncated: bool = False,
        redirects: list[str] | None = None,
    ) -> FetchedResource:
        response_class = "success" if error_code is None else error_code
        return FetchedResource(
            requested_url=requested_url,
            final_url=str(response.url) if response.url else final_url,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            body=body,
            fetched_at=utc_now(),
            access_mode="http",
            encoding=response.encoding,
            error=error_code,
            error_code=error_code,
            truncated=truncated,
            attempts=attempts,
            retry_class=retry_class,
            redirects=tuple(redirects or ()),
        )

    @staticmethod
    def _failure(
        requested_url: str,
        final_url: str,
        status_code: int | None,
        error_code: str,
        *,
        attempts: int,
        retry_class: str | None = None,
        redirects: list[str] | None = None,
    ) -> FetchedResource:
        logger.warning(
            "source_fetch_failed code=%s requested=%s final=%s status=%s attempts=%d",
            error_code,
            safe_url_for_log(requested_url),
            safe_url_for_log(final_url),
            status_code,
            attempts,
        )
        return FetchedResource(
            requested_url=requested_url,
            final_url=final_url,
            status_code=status_code,
            content_type=None,
            body=b"",
            fetched_at=utc_now(),
            access_mode="http",
            error=error_code,
            error_code=error_code,
            attempts=attempts,
            retry_class=retry_class,
            redirects=tuple(redirects or ()),
        )

    @staticmethod
    def _safe_text(body: bytes) -> str:
        return body.decode("utf-8", errors="ignore")[:2_000_000]
