from __future__ import annotations

from dataclasses import dataclass
import re

from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.pdf_policy import PdfResourceError

from ..pdf import extract_pdf_text
from ..identity import direction_codes


@dataclass(frozen=True, slots=True)
class CurriculumObservation:
    direction_code: str | None
    program_name: str | None
    discipline: str
    hours: int
    credits: str | None
    source_position: int


_ROW_START = re.compile(r"^\s*(\d{1,3})\s+(.*)$")
_TYPE = re.compile(r"\s([ОВФO])(?:\s|$)")
_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?(?![\w])")


def parse_work_plan(snapshot: RawSourceSnapshot) -> tuple[CurriculumObservation, ...]:
    text = extract_pdf_text(snapshot.body)
    if not text:
        return ()
    direction = _first_direction(text)
    program_name = _program_name(text, direction)
    structured = _parse_structured_table(snapshot.body, direction, program_name)
    if structured:
        return structured
    blocks = _row_blocks(text)
    observations: list[CurriculumObservation] = []
    for block_number, block in blocks:
        compact = " ".join(line.strip() for line in block.splitlines() if line.strip())
        type_match = _TYPE.search(compact)
        if type_match is None:
            continue
        discipline = compact[: type_match.start()].strip(" -—–")
        discipline = re.sub(r"^\d{1,3}\s+", "", discipline)
        discipline = re.sub(r"\s+\d{1,3}\s+(?=[А-ЯA-ZЁ])", " ", discipline)
        if not discipline or len(discipline) < 2 or _is_header(discipline):
            continue
        numbers = _NUMBER.findall(compact[type_match.end() :])
        credits, hours = _workload(numbers)
        if hours is None:
            continue
        observations.append(
            CurriculumObservation(
                direction_code=direction,
                program_name=program_name,
                discipline=discipline,
                hours=hours,
                credits=credits,
                source_position=block_number,
            )
        )
    return tuple(observations)


def _parse_structured_table(body: bytes, direction: str | None, program_name: str | None) -> tuple[CurriculumObservation, ...]:
    try:
        import io
        import pdfplumber

        observations: list[CurriculumObservation] = []
        with pdfplumber.open(io.BytesIO(body)) as document:
            position = 0
            for page in document.pages:
                for table in page.extract_tables():
                    for row in table:
                        if len(row) < 8:
                            continue
                        kind_index = next((index for index, cell in enumerate(row) if " ".join(str(cell or "").split()) in {"О", "В", "Ф", "O"}), None)
                        if kind_index is None:
                            continue
                        kind = " ".join(str(row[kind_index] or "").split())
                        if kind not in {"О", "В", "Ф", "O"}:
                            continue
                        name = " ".join(str(cell or "").strip() for cell in row[1:kind_index] if str(cell or "").strip())
                        credits_value, hours_value = _structured_workload(row, kind_index)
                        if not name or credits_value is None or hours_value is None or _is_header(name):
                            continue
                        credits = str(credits_value)
                        hours = int(hours_value)
                        position += 1
                        observations.append(CurriculumObservation(direction, program_name, name, hours, credits, position))
        return tuple(observations)
    except PdfResourceError:
        raise
    except Exception:
        return ()


def _first_number(value: str, *, decimal: bool) -> str | int | None:
    pattern = r"\d+(?:[.,]\d+)?" if decimal else r"\d+"
    match = re.search(pattern, value)
    if match is None:
        return None
    parsed = match.group(0).replace(",", ".")
    return parsed if decimal else int(parsed)


def _structured_workload(row: list[str | None], kind_index: int) -> tuple[str | None, int | None]:
    values: list[tuple[int, str, bool]] = []
    for index, cell in enumerate(row[kind_index + 1 :], start=kind_index + 1):
        value = str(cell or "")
        match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)", value)
        if match is None:
            continue
        raw = match.group(1).replace(",", ".")
        try:
            numeric = float(raw)
        except ValueError:
            continue
        values.append((index, raw, "," in match.group(1) or "." in match.group(1)))
    credit = next((item for item in values if item[2] and float(item[1]) <= 60), None)
    if credit is None and values and not values[0][2] and float(values[0][1]) <= 60:
        credit = values[0]
    if credit is None:
        return None, None
    next_values = [item for item in values if item[0] > credit[0]]
    hours_item = next((item for item in next_values if not item[2]), None)
    if hours_item is None:
        return credit[1], None
    return credit[1], int(float(hours_item[1]))


def _row_blocks(text: str) -> tuple[tuple[int, str], ...]:
    blocks: list[tuple[int, list[str]]] = []
    current: tuple[int, list[str]] | None = None
    synthetic_number = 10_000
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        match = _ROW_START.match(line)
        if match:
            if current is not None and _TYPE.search(line) is None:
                current[1].append(line)
                continue
            if current is not None:
                blocks.append(current)
            current = (int(match.group(1)), [line])
        elif _TYPE.search(line) is not None and _NUMBER.search(line) is not None:
            if current is not None:
                blocks.append(current)
            current = (synthetic_number, [line])
            synthetic_number += 1
        elif current is not None and line:
            current[1].append(line)
    if current is not None:
        blocks.append(current)
    return tuple((number, "\n".join(lines)) for number, lines in blocks)


def _workload(numbers: list[str]) -> tuple[str | None, int | None]:
    if not numbers:
        return None, None
    decimal_index = next((index for index, value in enumerate(numbers) if "," in value or "." in value), None)
    if decimal_index is not None:
        credits = numbers[decimal_index].replace(",", ".")
        hours_value = next((value for value in numbers[decimal_index + 1 :] if "." not in value and "," not in value), None)
        return credits, _as_int(hours_value)
    candidates: list[int] = []
    for value in numbers:
        parsed = _as_int(value)
        if parsed is not None and 0 <= parsed <= 2_000:
            candidates.append(parsed)
    if len(candidates) < 2:
        return None, None
    credit_candidate = next((value for value in candidates if value <= 60), None)
    if credit_candidate is None:
        return None, None
    hours = next((value for value in candidates[candidates.index(credit_candidate) + 1 :] if value > 60), None)
    return str(credit_candidate), hours


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _first_direction(text: str) -> str | None:
    values = direction_codes(text)
    return values[0] if values else None


def _program_name(text: str, direction: str | None) -> str | None:
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if direction and direction in line:
            value = re.sub(re.escape(direction), "", line).strip(" :—–-")
            if len(value) > 3 and not value.casefold().startswith(("направление", "код")):
                return value
            if index + 1 < len(lines) and len(lines[index + 1]) > 3:
                return lines[index + 1]
    for line in lines[:30]:
        if any(token in line.casefold() for token in ("образовательная программа", "программа")):
            value = re.sub(r"^.*?программа\s*[:\-–—]?\s*", "", line, flags=re.IGNORECASE)
            if len(value) > 3:
                return value
    return None


def _is_header(value: str) -> bool:
    lowered = value.casefold()
    return any(token in lowered for token in ("наименование дисциплины", "код блока", "трудоемкость", "реализующее подразделение"))


__all__ = ["CurriculumObservation", "parse_work_plan"]
