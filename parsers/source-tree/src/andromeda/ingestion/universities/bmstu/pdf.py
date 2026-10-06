from __future__ import annotations

import io
import re
from collections.abc import Iterable
from typing import Any

from andromeda.ingestion.pdf_policy import DEFAULT_PDF_POLICY, PdfResourceError, validate_page_count, validate_pdf_payload, validate_text_size


def is_pdf(body: bytes, content_type: str | None = None, url: str = "") -> bool:
    return body.startswith(b"%PDF") or "pdf" in (content_type or "").casefold() or url.casefold().split("?", 1)[0].endswith(".pdf")


def extract_pdf_text(body: bytes) -> str:
    validate_pdf_payload(body)
    try:
        import fitz  # type: ignore[import-untyped]

        document = fitz.open(stream=body, filetype="pdf")
        try:
            validate_page_count(document.page_count)
            return validate_text_size("\n\n".join(page.get_text() or "" for page in document).strip())
        finally:
            document.close()
    except PdfResourceError:
        raise
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        validate_page_count(len(reader.pages))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return validate_text_size("\n\n".join(pages).strip())
    except PdfResourceError:
        raise
    except Exception:
        return ""


def pdf_metadata(body: bytes) -> dict[str, Any]:
    validate_pdf_payload(body)
    try:
        import fitz

        document = fitz.open(stream=body, filetype="pdf")
        try:
            validate_page_count(document.page_count)
            metadata = document.metadata or {}
            return {
                "pages": document.page_count,
                "title": str(metadata.get("title", "") or ""),
                "author": str(metadata.get("author", "") or ""),
                "subject": str(metadata.get("subject", "") or ""),
            }
        finally:
            document.close()
    except PdfResourceError:
        raise
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        validate_page_count(len(reader.pages))
        metadata = reader.metadata or {}
        return {
            "pages": len(reader.pages),
            "title": str(metadata.get("/Title", "") or ""),
            "author": str(metadata.get("/Author", "") or ""),
            "subject": str(metadata.get("/Subject", "") or ""),
        }
    except PdfResourceError:
        raise
    except Exception:
        return {"pages": None, "title": "", "author": "", "subject": ""}


def extract_pdf_tables(body: bytes, max_pages: int | None = 120) -> list[dict[str, Any]]:
    """Извлекает таблицы PDF, если установлен pdfplumber.

    pypdf хорошо подходит для текста и метаданных, но конкурсные списки
    сохраняют полезную структуру только в координатах PDF. Табличный слой
    остаётся опциональным: при проблемном шаблоне исходный PDF всё равно
    сохраняется, а текстовый fallback продолжает работать.
    """
    validate_pdf_payload(body)
    page_limit = DEFAULT_PDF_POLICY.max_pages if max_pages is None else min(max_pages, DEFAULT_PDF_POLICY.max_pages)
    try:
        import pdfplumber

        result: list[dict[str, Any]] = []
        with pdfplumber.open(io.BytesIO(body)) as document:
            validate_page_count(len(document.pages), DEFAULT_PDF_POLICY)
            if len(document.pages) > page_limit:
                raise PdfResourceError("pdf_table_page_limit_exceeded")
            pages = document.pages
            for page_number, page in enumerate(pages, start=1):
                for table_number, table in enumerate(page.extract_tables(), start=1):
                    rows = [
                        [str(cell or "").strip() for cell in row]
                        for row in table
                        if row and any(str(cell or "").strip() for cell in row)
                    ]
                    if rows:
                        result.append({"page": page_number, "table": table_number, "rows": rows})
        return result
    except PdfResourceError:
        raise
    except Exception:
        return []


def iter_registered_rows(text: str) -> Iterable[dict[str, Any]]:
    """Разбирает многостраничный PDF зарегистрированных поступающих.

    Этот формат обычно содержит одну строку на абитуриента и переносит
    программы на следующую строку. Разбор по тексту заметно дешевле полного
    восстановления координатных таблиц для PDF на сотни страниц.
    """
    current: dict[str, Any] | None = None
    lines = [re.sub(r"\s+", " ", raw_line).strip() for raw_line in text.splitlines()]
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line:
            index += 1
            continue
        row_match = re.match(r"^(\d{1,5})\s+(\d{5,8})(?:\s+\*)?\s*(.*)$", line)
        separate_row = False
        if not row_match and re.fullmatch(r"\d{1,5}", line) and index + 1 < len(lines):
            applicant_match = re.match(r"^(\d{5,8})(?:\s+\*)?\s*$", lines[index + 1])
            if applicant_match:
                row_match = re.match(r"^(\d{1,5})$", line)
                line = f"{line} {lines[index + 1]}"
                separate_row = True
        if row_match:
            if current:
                yield current
            if separate_row:
                applicant_id = re.match(r"^\d{1,5}\s+(\d{5,8})", line)
                current = {
                    "row_no": int(row_match.group(1)),
                    "applicant_id": applicant_id.group(1) if applicant_id else None,
                    "is_special": "*" in line,
                    "raw_parts": [line],
                    "is_data_row": True,
                }
                index += 2
                continue
            current = {
                "row_no": int(row_match.group(1)),
                "applicant_id": row_match.group(2),
                "is_special": "*" in line,
                "raw_parts": [line],
                "is_data_row": True,
            }
            index += 1
            continue
        if current:
            current["raw_parts"].append(line)
        index += 1
    if current:
        yield current


def iter_order_rows(text: str) -> Iterable[dict[str, Any]]:
    """Разбирает текст приказа о зачислении.

    В текущем PDF МГТУ часть кириллицы имеет нестандартное сопоставление
    шрифта, поэтому якоримся на стабильной нумерации строки, ID и числах,
    а не на названиях полей.
    """
    normalized = re.sub(r"\s+", " ", text)
    chunks = re.split(r"(?=\s*[^\d\s]?\d+\.\s+)", normalized)
    for chunk in chunks:
        row_match = re.match(r"\s*[^\d\s]?(\d+)\.\s+", chunk)
        if not row_match:
            continue
        score_matches: list[tuple[int, int, int]] = []
        for match in re.finditer(r"(?<!\d)(\d{2,3})\s*\(([^)]*)\)", chunk):
            parts = re.findall(r"\d{1,3}", match.group(2))
            if len(parts) >= 2:
                score_matches.append((int(match.group(1)), int(parts[0]), int(parts[1])))
        if not score_matches:
            continue
        score_total, score_base, score_individual = score_matches[-1]
        applicant_match = re.search(r":\s*(\d{5,8})\s*;", chunk)
        program_match = re.search(r"\b\d{2}\.\d{2}\.\d{2}\b", chunk)
        yield {
            "row_no": int(row_match.group(1)),
            "applicant_id": applicant_match.group(1) if applicant_match else None,
            "score": score_total,
            "score_base": score_base,
            "score_individual": score_individual,
            "program_code": program_match.group(0) if program_match else None,
            "raw": chunk.strip(),
            "is_data_row": True,
        }


def extract_admission_year(text: str) -> int | None:
    patterns = [
        r"при[её]м(?:а|ной кампани[ия])?[^\d]{0,30}(20\d{2})",
        r"учебн(?:ый|ого)\s+год[^\d]{0,10}(20\d{2})",
        r"\b(20\d{2})\s*/\s*20\d{2}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    fallback = re.findall(r"\b(20\d{2})\b", text[:20_000])
    if fallback:
        return int(fallback[0])
    return None
