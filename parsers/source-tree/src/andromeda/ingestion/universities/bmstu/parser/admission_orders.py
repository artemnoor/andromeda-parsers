"""Parser for official BMSTU enrollment-order PDFs."""

from __future__ import annotations

import io
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from andromeda.ingestion.universities.bmstu.source_metadata import (
    BmstuOrderCompetition,
    BmstuOrderDocumentMetadata,
    BmstuOrderFunding,
    classify_competition_heading,
)
from andromeda.ingestion.pdf_policy import PdfResourceError, validate_page_count, validate_pdf_payload, validate_text_size


logger = logging.getLogger("andromeda.ingestion.bmstu.parser.admission_orders")


@dataclass(frozen=True, slots=True)
class BmstuAdmissionOrderObservation:
    direction_code: str
    admission_year: int
    study_form: str | None
    funding_type: str
    score_type: str
    competition_type: BmstuOrderCompetition
    status: str
    score: Decimal | None
    source_url: str
    page: int
    row: int


@dataclass(frozen=True, slots=True)
class BmstuAdmissionOrderParseResult:
    observations: tuple[BmstuAdmissionOrderObservation, ...]
    warnings: tuple[str, ...]
    pages: int
    sections: int
    numeric_rows: int
    bvi_rows: int
    failed: bool = False


def parse_admission_order_document(
    body: bytes,
    metadata: BmstuOrderDocumentMetadata,
) -> BmstuAdmissionOrderParseResult:
    """Parse one captured official order document into route-aware facts."""

    logger.debug(
        "admission_order_parse_start url=%s kind=%s funding=%s year=%s",
        metadata.manifest_entry.requested_url,
        metadata.document_kind.value,
        metadata.funding.value,
        metadata.admission_year,
    )
    pages = tuple(iter_pdf_pages(body))
    warnings = list(metadata.warnings)
    if not pages:
        warnings.append("pdf_text_unavailable")
        return BmstuAdmissionOrderParseResult((), tuple(warnings), 0, 0, 0, 0, failed=True)
    if not metadata.supported_catalog:
        warnings.append(f"unsupported_education_kind:{metadata.document_kind.value}")
        return BmstuAdmissionOrderParseResult((), tuple(warnings), len(pages), 0, 0, 0)
    if metadata.admission_year is None or metadata.funding is BmstuOrderFunding.UNKNOWN:
        warnings.append("document_metadata_incomplete")
        return BmstuAdmissionOrderParseResult((), tuple(warnings), len(pages), 0, 0, 0, failed=True)

    observations, sections, numeric_rows, bvi_rows = _parse_pages(pages, metadata, warnings)
    result = BmstuAdmissionOrderParseResult(
        observations=tuple(observations),
        warnings=tuple(warnings),
        pages=len(pages),
        sections=sections,
        numeric_rows=numeric_rows,
        bvi_rows=bvi_rows,
    )
    logger.info(
        "admission_order_parse_complete url=%s pages=%d sections=%d directions=%d numeric_rows=%d bvi_rows=%d observations=%d warnings=%d",
        metadata.manifest_entry.requested_url,
        result.pages,
        result.sections,
        len({item.direction_code for item in result.observations}),
        result.numeric_rows,
        result.bvi_rows,
        len(result.observations),
        len(result.warnings),
    )
    return result


def iter_pdf_pages(body: bytes) -> tuple[str, ...]:
    """Extract text page-by-page while keeping a deterministic fallback."""

    validate_pdf_payload(body)
    try:
        import fitz  # type: ignore[import-untyped]

        document = fitz.open(stream=body, filetype="pdf")
        try:
            validate_page_count(document.page_count)
            return tuple(validate_text_size((page.get_text() or "").strip()) for page in document)
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
        return tuple((page.extract_text() or "").strip() for page in reader.pages)
    except PdfResourceError:
        raise
    except Exception:
        return ()


def _parse_pages(
    pages: Sequence[str],
    metadata: BmstuOrderDocumentMetadata,
    warnings: list[str],
) -> tuple[tuple[BmstuAdmissionOrderObservation, ...], int, int, int]:
    buckets: OrderedDict[tuple[str, str, str, BmstuOrderCompetition], BmstuAdmissionOrderObservation] = OrderedDict()
    seen_rows: dict[tuple[str, int, BmstuOrderCompetition], BmstuAdmissionOrderObservation] = {}
    current_header: list[str] = []
    current_direction: str | None = None
    current_route = BmstuOrderCompetition.GENERAL if metadata.stage.value == "main" else BmstuOrderCompetition.OTHER
    current_row_no: int | None = None
    current_row_page = 1
    current_row_lines: list[str] = []
    section_count = 0
    numeric_rows = 0
    bvi_rows = 0

    def flush_row() -> None:
        nonlocal numeric_rows, bvi_rows, current_row_no, current_row_lines
        if current_row_no is None or current_direction is None:
            current_row_no = None
            current_row_lines = []
            return
        row_text = _normalize(" ".join(current_row_lines))
        score_match = re.search(r"сумма\s+баллов\s*:\s*(\d{1,3})", row_text)
        explicit_bvi = (
            "без проведения вступительных испытаний" in row_text
            or "без вступительных испытаний" in row_text
        )
        is_bvi = (
            current_route is BmstuOrderCompetition.BVI
            or explicit_bvi
        )
        score: Decimal | None = None
        status = "bvi" if is_bvi else "numeric"
        if score_match:
            total = int(score_match.group(1))
            if 0 <= total <= 400:
                score = Decimal(total)
                numeric_rows += 1
            else:
                warnings.append(f"score_out_of_range:page={current_row_page};row={current_row_no}")
        if is_bvi:
            bvi_rows += 1
        if score is None and not is_bvi:
            warnings.append(f"row_without_score_or_bvi:page={current_row_page};row={current_row_no}")
            current_row_no = None
            current_row_lines = []
            return
        if score is not None and is_bvi:
            warnings.append(f"row_contains_numeric_and_bvi:page={current_row_page};row={current_row_no}")
            status = "numeric"
        route = (
            BmstuOrderCompetition.BVI
            if explicit_bvi
            and current_route in {BmstuOrderCompetition.GENERAL, BmstuOrderCompetition.OTHER}
            else current_route
        )
        observation = BmstuAdmissionOrderObservation(
            direction_code=current_direction,
            admission_year=metadata.admission_year or 0,
            study_form=metadata.study_form,
            funding_type=metadata.funding.value,
            score_type="paid" if metadata.funding is BmstuOrderFunding.PAID else "budget",
            competition_type=route,
            status=status,
            score=score,
            source_url=str(metadata.manifest_entry.requested_url),
            page=current_row_page,
            row=current_row_no,
        )
        row_key = (current_direction, current_row_no, route)
        previous = seen_rows.get(row_key)
        if previous is not None:
            if previous.status == observation.status and previous.score == observation.score:
                current_row_no = None
                current_row_lines = []
                return
            warnings.append(f"duplicate_row_conflict:page={current_row_page};row={current_row_no};direction={current_direction}")
            if previous.status == "bvi" or (observation.score is not None and previous.score is not None and observation.score < previous.score):
                seen_rows[row_key] = observation
        else:
            seen_rows[row_key] = observation
        chosen = seen_rows[row_key]
        bucket_key = (chosen.direction_code, chosen.funding_type, chosen.status, chosen.competition_type)
        existing = buckets.get(bucket_key)
        if existing is None or (
            chosen.status == "numeric"
            and chosen.score is not None
            and existing.score is not None
            and chosen.score < existing.score
        ):
            buckets[bucket_key] = chosen
        current_row_no = None
        current_row_lines = []

    for page_number, page in enumerate(pages, start=1):
        for raw_line in page.splitlines():
            line = _normalize(raw_line)
            if not line:
                continue
            section_match = re.match(r"^(\d+)\.\s+(?=(?:перечень|список|сведения)\b)", line)
            if section_match and not line.startswith("§"):
                flush_row()
                section_count += 1
                current_header = [line]
                current_direction = _direction_code(line) or current_direction
                current_route = BmstuOrderCompetition.GENERAL if metadata.stage.value == "main" else BmstuOrderCompetition.OTHER
                continue
            row_match = re.match(r"^§\s*(\d+)\.\s*(.*)$", line)
            if row_match:
                flush_row()
                current_route, route_warning = classify_competition_heading(" ".join(current_header))
                if route_warning:
                    warnings.append(f"{route_warning}:page={page_number};section={section_count}")
                current_row_no = int(row_match.group(1))
                current_row_page = page_number
                current_row_lines = [row_match.group(2)]
                continue
            if current_row_no is not None:
                current_row_lines.append(line)
            elif current_header:
                current_header.append(line)
                current_direction = _direction_code(" ".join(current_header)) or current_direction

    flush_row()
    return tuple(buckets.values()), section_count, numeric_rows, bvi_rows


def _direction_code(text: str) -> str | None:
    match = re.search(r"\b(\d{2}\.\d{2}\.\d{2})\b", text)
    return match.group(1) if match else None


def _normalize(value: str) -> str:
    value = value.replace("ё", "е").replace("Ё", "Е").replace("\xa0", " ")
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    return re.sub(r"\s+", " ", value.casefold()).strip()


__all__ = [
    "BmstuAdmissionOrderObservation",
    "BmstuAdmissionOrderParseResult",
    "iter_pdf_pages",
    "parse_admission_order_document",
]
