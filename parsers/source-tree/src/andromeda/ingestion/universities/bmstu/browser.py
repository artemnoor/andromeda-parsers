from __future__ import annotations

from typing import Any

from andromeda.ingestion.fetch_policy import ResolveHost, SourceHostPolicy, SourcePolicyError, validate_source_url

from .source_models import FetchedResource, utc_now


def fetch_with_browser(
    url: str,
    timeout_seconds: float = 30.0,
    max_body_bytes: int = 30_000_000,
    *,
    policy: SourceHostPolicy | None = None,
    resolver: ResolveHost | None = None,
) -> FetchedResource:
    """Рендерит JS-страницу и сохраняет JSON-ответы, если Playwright установлен."""
    if policy is not None:
        validate_source_url(url, policy, resolver=resolver)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Playwright не установлен. Выполните: pip install -e .[browser] && playwright install chromium") from exc

    payloads: list[dict[str, Any]] = []
    blocked_document_request = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Andromeda-BMSTU-Parser/0.1 (browser mode)",
            locale="ru-RU",
            viewport={"width": 1440, "height": 1100},
        )

        def capture(response: Any) -> None:
            if policy is not None and response.url.casefold().startswith(("http://", "https://")):
                try:
                    validate_source_url(response.url, policy, resolver=resolver)
                except SourcePolicyError:
                    return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type.lower():
                return
            try:
                body = response.body()
                if len(body) > 5_000_000:
                    return
                payloads.append(
                    {
                        "url": response.url,
                        "status": response.status,
                        "content_type": content_type,
                        "body": body.decode("utf-8", errors="replace"),
                    }
                )
            except Exception:
                return

        def guard_request(route: Any) -> None:
            """Keep browser navigation inside the adapter-owned source boundary.

            Official pages commonly load analytics, fonts, or other telemetry
            from unrelated hosts. Those subresources are not source data and
            must not turn an otherwise valid document into a failed capture.
            A disallowed document request is different: it represents a
            redirect/navigation escape and remains fatal.
            """

            nonlocal blocked_document_request
            request = route.request
            request_url = request.url
            if policy is not None and request_url.casefold().startswith(("http://", "https://")):
                try:
                    validate_source_url(request_url, policy, resolver=resolver)
                except SourcePolicyError:
                    if getattr(request, "resource_type", "") == "document":
                        blocked_document_request = True
                    route.abort("blockedbyclient")
                    return
            route.continue_()

        page.route("**/*", guard_request)
        page.on("response", capture)
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000))
            try:
                page.wait_for_load_state("networkidle", timeout=int(timeout_seconds * 1000))
            except Exception:
                pass
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            raw_html = page.content().encode("utf-8")
            html = raw_html[:max_body_bytes]
            final_url = page.url
            status_code = response.status if response is not None else 200
        except Exception:
            browser.close()
            error_code = "browser_redirect_host_not_allowed" if blocked_document_request else "browser_navigation_failed"
            return FetchedResource(
                requested_url=url,
                final_url=url,
                status_code=None,
                content_type="text/html; charset=utf-8",
                body=b"",
                fetched_at=utc_now(),
                access_mode="browser",
                error=error_code,
                error_code=error_code,
            )
        browser.close()
    if policy is not None:
        try:
            validate_source_url(final_url, policy, resolver=resolver)
        except SourcePolicyError as exc:
            return FetchedResource(
                requested_url=url,
                final_url=final_url,
                status_code=status_code,
                content_type="text/html; charset=utf-8",
                body=b"",
                fetched_at=utc_now(),
                access_mode="browser",
                error=f"browser_{exc.code}",
                error_code=f"browser_{exc.code}",
            )
    truncated = len(raw_html) > max_body_bytes
    return FetchedResource(
        requested_url=url,
        final_url=final_url,
        status_code=status_code,
        content_type="text/html; charset=utf-8",
        body=html,
        fetched_at=utc_now(),
        access_mode="browser",
        encoding="utf-8",
        network_payloads=payloads,
        error="response_body_truncated" if truncated else None,
        error_code="response_body_truncated" if truncated else None,
        truncated=truncated,
    )
