from __future__ import annotations

from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup, Tag


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def visible_text(document: bytes | str | BeautifulSoup | Tag) -> str:
    soup = document if isinstance(document, (BeautifulSoup, Tag)) else BeautifulSoup(document, "html.parser")
    for node in soup.select("script, style, noscript, template, svg"):
        node.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())


def extract_links(document: bytes | str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(document, "html.parser")
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urljoin(base_url, href)
        absolute, _ = urldefrag(absolute)
        if absolute in seen:
            continue
        seen.add(absolute)
        result.append((clean_text(anchor.get_text(" ", strip=True)), absolute))
    return result


def extract_tables(document: bytes | str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(document, "html.parser")
    result: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.find_all("table"), start=1):
        rows: list[list[str]] = []
        pending: dict[tuple[int, int], str] = {}
        for row_index, tr in enumerate(table.find_all("tr")):
            values: list[str] = []
            column = 0
            for cell in tr.find_all(["th", "td"], recursive=False):
                while (row_index, column) in pending:
                    values.append(pending.pop((row_index, column)))
                    column += 1
                value = clean_text(cell.get_text(" ", strip=True))
                try:
                    colspan = max(1, int(str(cell.get("colspan") or 1)))
                except ValueError:
                    colspan = 1
                try:
                    rowspan = max(1, int(str(cell.get("rowspan") or 1)))
                except ValueError:
                    rowspan = 1
                for offset in range(colspan):
                    values.append(value)
                    for future in range(1, rowspan):
                        pending[(row_index + future, column + offset)] = value
                column += colspan
            while (row_index, column) in pending:
                values.append(pending.pop((row_index, column)))
                column += 1
            if values:
                rows.append(values)
        if not rows:
            continue
        headers = rows[0] if table.find("th") else []
        result.append({"index": table_index, "headers": headers, "rows": rows[1:] if headers else rows})
    return result


def official_hse_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (host == "hse.ru" or host.endswith(".hse.ru"))


__all__ = ["clean_text", "extract_links", "extract_tables", "official_hse_url", "visible_text"]
