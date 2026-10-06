from __future__ import annotations

import re
from dataclasses import dataclass
from numbers import Number
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
CODE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2}(?:/\d{2}\.\d{2}\.\d{2})?$")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+7|8)\s*[\d()\-\s]{8,}\d")
YEAR_RANGE_RE = re.compile(r"20\d{2}\s*/\s*20\d{2}")


@dataclass(slots=True)
class ParsedPage:
    soup: BeautifulSoup
    text: str
    tables: list[dict[str, Any]]
    labels: dict[str, str]
    links: list[dict[str, str]]


def parse_page(html: str | bytes, base_url: str = "") -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    return ParsedPage(
        soup=soup,
        # extract_text removes script/style nodes while normalising visible
        # text. Feed it the original payload so the structured __NEXT_DATA__
        # script remains available to source-specific adapters.
        text=extract_text(html),
        tables=extract_tables(soup),
        labels=extract_label_values(soup),
        links=extract_links(soup, base_url),
    )


def extract_text(document: BeautifulSoup | Tag | str | bytes) -> str:
    soup = document if isinstance(document, (BeautifulSoup, Tag)) else BeautifulSoup(document, "html.parser")
    for node in soup.select("script, style, noscript, template, svg"):
        node.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _expand_table(table: Tag) -> list[list[str]]:
    grid: list[list[str]] = []
    pending: dict[tuple[int, int], str] = {}
    for row_index, tr in enumerate(table.find_all("tr")):
        row: list[str] = []
        column = 0
        for cell in tr.find_all(["th", "td"], recursive=False):
            while (row_index, column) in pending:
                row.append(pending.pop((row_index, column)))
                column += 1
            value = clean_text(cell.get_text(" ", strip=True))
            try:
                colspan_value = cell.get("colspan")
                colspan = max(1, int(str(colspan_value))) if colspan_value is not None else 1
            except (TypeError, ValueError):
                colspan = 1
            try:
                rowspan_value = cell.get("rowspan")
                rowspan = max(1, int(str(rowspan_value))) if rowspan_value is not None else 1
            except (TypeError, ValueError):
                rowspan = 1
            for offset in range(colspan):
                row.append(value)
                if rowspan > 1:
                    for future_row in range(1, rowspan):
                        pending[(row_index + future_row, column + offset)] = value
            column += colspan
        while (row_index, column) in pending:
            row.append(pending.pop((row_index, column)))
            column += 1
        if row:
            grid.append(row)
    return grid


def _header_names(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(values, start=1):
        base = clean_text(value) or f"column_{index}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base}_{count}")
    return result


def extract_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.find_all("table"), start=1):
        grid = _expand_table(table)
        if not grid:
            continue
        has_header_cells = bool(table.find("th"))
        first_row = grid[0]
        looks_like_header = has_header_cells or any(
            token in clean_text(value).casefold()
            for value in first_row
            for token in ("код", "наименование", "название", "цена", "год", "балл", "мест")
        )
        headers = _header_names(first_row if looks_like_header else [f"column_{index}" for index in range(1, len(first_row) + 1)])
        data_grid = grid[1:] if looks_like_header else grid
        rows: list[dict[str, str]] = []
        for values in data_grid:
            padded = values + [""] * max(0, len(headers) - len(values))
            row = {headers[index]: clean_text(padded[index]) for index in range(len(headers))}
            if any(row.values()):
                rows.append(row)
        caption_node = table.find("caption")
        result.append(
            {
                "index": table_index,
                "caption": clean_text(caption_node.get_text(" ", strip=True)) if caption_node else "",
                "context": _table_context(table),
                "headers": headers,
                "rows": rows,
                "raw_rows": grid,
            }
        )
    return result


def _table_context(table: Tag) -> str:
    """Находит ближайший заголовок/абзац, описывающий таблицу.

    На сайте стоимости часть контекста лежит в обычном ``<p>`` перед tab-pane,
    поэтому поиска только по h1-h6 недостаточно.
    """
    candidates = table.find_all_previous(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div"], limit=60)
    fallback = ""
    for candidate in candidates:
        if candidate.find("table") is not None:
            continue
        text = clean_text(candidate.get_text(" ", strip=True))
        if not text:
            continue
        if not fallback and candidate.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            fallback = text
        if YEAR_RANGE_RE.search(text) or "учебн" in text.casefold() or "поступа" in text.casefold():
            return text[:800]
    return fallback


def extract_links(soup: BeautifulSoup, base_url: str = "") -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urljoin(base_url, href)
        text = clean_text(anchor.get_text(" ", strip=True))
        key = (absolute, text)
        if key in seen:
            continue
        seen.add(key)
        result.append({"text": text, "url": absolute})
    return result


def extract_label_values(soup: BeautifulSoup) -> dict[str, str]:
    labels: dict[str, str] = {}

    def add(key: str, value: str) -> None:
        key = clean_text(key).rstrip(":")
        value = clean_text(value)
        if not key or not value:
            return
        if key in labels and value not in labels[key]:
            labels[key] = f"{labels[key]}; {value}"
        else:
            labels[key] = value

    for definition in soup.find_all("dl"):
        terms = definition.find_all("dt")
        for term in terms:
            detail = term.find_next_sibling("dd")
            if detail:
                add(term.get_text(" ", strip=True), detail.get_text(" ", strip=True))

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if len(cells) == 2:
                add(cells[0].get_text(" ", strip=True), cells[1].get_text(" ", strip=True))

    for element in soup.find_all(["p", "li", "div"]):
        text = clean_text(element.get_text(" ", strip=True))
        if ":" not in text or len(text) > 300:
            continue
        key, value = text.split(":", 1)
        if 2 <= len(key) <= 100 and value.strip():
            add(key, value)
    return labels


def extract_emails(text: str) -> list[str]:
    return sorted(set(EMAIL_RE.findall(text)))


def extract_phones(text: str) -> list[str]:
    return sorted({clean_text(phone) for phone in PHONE_RE.findall(text)})


def extract_years(text: str) -> list[int]:
    return sorted({int(value) for value in YEAR_RE.findall(text)})


def looks_like_code(value: Any) -> bool:
    return bool(CODE_RE.match(clean_text(value).replace(" ", "")))


def parse_number(value: Any) -> int | float | None:
    if isinstance(value, Number) and not isinstance(value, bool):
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return value
        return float(str(value))
    text = clean_text(value).replace("\u202f", " ").replace("\xa0", " ")
    if not text:
        return None
    text = re.sub(r"[^\d,\.\-]", "", text.replace(" ", ""))
    if not text or text in {"-", ".", ","}:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        text = text.replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def is_js_shell(text: str, html: str | bytes) -> bool:
    visible = len(clean_text(text))
    source = html.decode("utf-8", errors="ignore") if isinstance(html, bytes) else html
    has_app_mount = bool(re.search(r"id=[\"'](?:app|root|__next|app-root)[\"']", source, re.IGNORECASE))
    has_scripts = bool(BeautifulSoup(source, "html.parser").find("script"))
    return visible < 250 and has_app_mount and has_scripts


def is_blocked_page(text: str, html: str | bytes = b"") -> bool:
    """Распознаёт короткие anti-bot/заглушки, которые ошибочно возвращаются с HTTP 200."""
    visible = clean_text(text).casefold()
    if len(visible) > 800:
        return False
    markers = (
        "just a moment",
        "access denied",
        "forbidden",
        "captcha",
        "cloudflare",
        "checking your browser",
        "enable javascript and cookies",
    )
    return any(marker in visible for marker in markers)
