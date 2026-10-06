from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urldefrag, urlparse

from andromeda.ingestion.contracts.constraints import http_url
from andromeda.ingestion.contracts.raw import RawSourceSnapshot

from ..html import clean_text, extract_links, official_hse_url, visible_text


_CODE_RE = re.compile(r"(?<!\d)(\d{2}\.\d{2}\.\d{2})(?!\d)")
_PDF_RE = re.compile(r"https?://[^\s\"']+\.pdf(?:\?[^\s\"']*)?", re.IGNORECASE)
_DETAIL_SUFFIXES = ("/admission", "/tracks", "/requirements", "/courses", "/vacant", "/documents", "/learn_plans")


@dataclass(frozen=True, slots=True)
class HseProgramPage:
    url: str
    name: str
    direction_code: str | None
    direction_name: str
    education_level: str
    education_year: int | None


def canonical_url(url: str) -> str:
    value, _ = urldefrag(url)
    return value.rstrip("/") + "/"


def discover_program_links(body: bytes | str, base_url: str) -> tuple[str, ...]:
    result: list[str] = []
    for _, url in extract_links(body, base_url):
        if not official_hse_url(url):
            continue
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").casefold()
        if "/ba/" not in f"{path}/" and "/bacnn/" not in f"{path}/" and "/bacalavr/" not in f"{path}/":
            continue
        if path.endswith("/admission"):
            path = path[: -len("/admission")]
            url = f"{parsed.scheme}://{parsed.netloc}{path}/"
        elif any(path.endswith(suffix) for suffix in _DETAIL_SUFFIXES):
            continue
        if path.count("/") < 2 or path in {"/ba", "/bacnn", "/bacalavr"}:
            continue
        value = canonical_url(url)
        if value not in result:
            result.append(value)
    return tuple(result)


def parse_program_detail(snapshot: RawSourceSnapshot) -> HseProgramPage:
    text = visible_text(snapshot.body)
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    codes = _CODE_RE.findall(text)
    title = _title(snapshot.body)
    if not title:
        raise ValueError(f"HSE detail has no program title: {snapshot.requested_url}")
    direction_code = codes[0] if codes else None
    code_line = next((line for line in lines if direction_code and direction_code in line), "")
    direction_name = clean_text(code_line.replace(direction_code or "", "")) or title
    education_level = "специалитет" if "специалитет" in text.casefold() else "бакалавриат"
    years = [int(value) for value in re.findall(r"\b(20\d{2})\b", text)]
    education_year = max((year for year in years if 2020 <= year <= 2100), default=None)
    return HseProgramPage(canonical_url(str(snapshot.requested_url)), title, direction_code, direction_name, education_level, education_year)


def study_plan_urls(body: bytes | str, base_url: str) -> tuple[str, ...]:
    candidates = [url for _, url in extract_links(body, base_url) if "/dbs/education/" in url and ".pdf" in url.casefold()]
    raw = _PDF_RE.findall(body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body)
    candidates.extend(raw)
    result: list[str] = []
    for value in candidates:
        if official_hse_url(value) and value not in result:
            result.append(value)
    return tuple(result)


def _title(body: bytes) -> str | None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body, "html.parser")
    node = soup.find("h1") or soup.find("title")
    if node is None:
        return None
    value = clean_text(node.get_text(" ", strip=True))
    value = re.sub(r"^НИУ ВШЭ\s*[—-]\s*", "", value, flags=re.IGNORECASE)
    return value or None


__all__ = ["HseProgramPage", "canonical_url", "discover_program_links", "parse_program_detail", "study_plan_urls"]
