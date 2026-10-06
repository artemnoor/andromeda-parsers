from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ....capture import S06_API_BASE_URL, S06_CATALOG_URL
from ..common import clean_text, normalize_code


CATALOG_URL = "https://bmstu.ru/bachelor/majors"
CATALOG_API_URL = S06_API_BASE_URL
CATALOG_KIND = "bmstu_2026_catalog"


def parse_catalog_html(body: bytes) -> tuple[dict[str, str], ...]:
    """Read actual major-card links from the published catalog page."""
    soup = BeautifulSoup(body, "html.parser")
    found: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        href = clean_text(anchor.get("href"))
        absolute = urljoin(CATALOG_URL, href)
        parsed = urlparse(absolute)
        if parsed.hostname not in {"bmstu.ru", "www.bmstu.ru"}:
            continue
        prefix = "/bachelor/majors/"
        if not parsed.path.startswith(prefix):
            continue
        slug = parsed.path[len(prefix) :].strip("/")
        if slug:
            found[slug] = absolute
    return tuple({"slug": slug, "page_url": url} for slug, url in sorted(found.items()))


def parse_catalog_api(body: bytes) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("BMSTU catalog API response is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("BMSTU catalog API response has no data array")
    records: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    seen_slugs: set[str] = set()
    for index, value in enumerate(payload["data"], start=1):
        if not isinstance(value, dict):
            raise ValueError(f"BMSTU catalog row {index} is not an object")
        code = normalize_code(value.get("code"))
        name = clean_text(value.get("name"))
        slug = clean_text(value.get("slug"))
        if not code or not name or not slug:
            raise ValueError(f"BMSTU catalog row {index} is missing code, name, or slug")
        if code in seen_codes or slug in seen_slugs:
            raise ValueError(f"BMSTU catalog contains duplicate code/slug: {code} / {slug}")
        seen_codes.add(code)
        seen_slugs.add(slug)
        records.append({**value, "code": code, "name": name, "slug": slug})
    return tuple(records)


def is_head_campus(address: str | None) -> bool | None:
    """Classify only from the official chair address; unknown stays unknown."""
    value = clean_text(address).casefold()
    if not value or value == "-":
        return None
    if "калуж" in value or "мытищ" in value:
        return False
    if "москва" in value:
        return True
    return None


def catalog_page_for_slug(pages: tuple[dict[str, str], ...], slug: str) -> str | None:
    return next((page["page_url"] for page in pages if page["slug"] == slug), None)
