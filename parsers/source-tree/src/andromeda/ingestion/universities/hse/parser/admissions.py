from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from andromeda.ingestion.contracts.raw import RawAdmissionExamRequirement, RawAdmissionPassingScore, RawAdmissionQuota, RawAdmissionTuition, RawSourceSnapshot

from ..html import clean_text, extract_tables, visible_text
from ..identity import direction_codes
from ..pdf import extract_pdf_text


@dataclass(frozen=True, slots=True)
class ExamObservation:
    direction_code: str | None
    program_name: str
    exams: tuple[RawAdmissionExamRequirement, ...]
    row: int


@dataclass(frozen=True, slots=True)
class FactObservation:
    direction_code: str | None
    program_name: str
    admission_year: int
    study_form: str | None
    funding_type: str | None
    places: int | None
    exams: tuple[RawAdmissionExamRequirement, ...]
    quotas: tuple[RawAdmissionQuota, ...]
    passing_scores: tuple[RawAdmissionPassingScore, ...]
    tuition: tuple[RawAdmissionTuition, ...]
    source_kind: str
    row: int


@dataclass(frozen=True, slots=True)
class EnrollmentObservation:
    direction_code: str | None
    program_name: str
    admission_year: int
    study_form: str
    funding_type: str
    competition_type: str
    status: str
    score: Decimal | None
    row: int


_SUBJECTS = ("русский", "матем", "информат", "физик", "обществозн", "иностран", "истори", "биолог", "хими", "географ", "литератур")
_PROGRAM_EXCLUSIONS = ("направление подготовки", "образовательная программа", "минимальн", "вступительн", "наименование")


def parse_minimum_exams(snapshot: RawSourceSnapshot) -> tuple[ExamObservation, ...]:
    result: list[ExamObservation] = []
    current_direction: str | None = None
    for table in extract_tables(snapshot.body):
        for row_number, cells in enumerate(table["rows"], start=1):
            text = " | ".join(cells)
            codes = direction_codes(text)
            if codes:
                current_direction = codes[0]
            program_name = _program_name(cells)
            if not program_name:
                continue
            subject_cell = next((cell for cell in cells if any(token in cell.casefold() for token in _SUBJECTS)), "")
            scores = [int(value) for value in re.findall(r"(?<!\d)([4-9]\d|100)(?!\d)", text)]
            if not subject_cell or not scores:
                continue
            subjects = [clean_text(value) for value in re.split(r"[/,;]|\s+или\s+", subject_cell, flags=re.IGNORECASE) if clean_text(value)]
            minimum = Decimal(str(scores[-1]))
            exams = tuple(
                RawAdmissionExamRequirement(subject=subject, source_name=subject_cell, minimum_score=minimum, is_choice=len(subjects) > 1, is_required=True)
                for subject in subjects
                if any(token in subject.casefold() for token in _SUBJECTS)
            )
            if exams:
                result.append(ExamObservation(current_direction, program_name, exams, row_number))
    return tuple(_dedupe_exams(result))


def parse_places(snapshot: RawSourceSnapshot, admission_year: int) -> tuple[FactObservation, ...]:
    result: list[FactObservation] = []
    for table in extract_tables(snapshot.body):
        headers = [clean_text(value).casefold() for value in table["headers"]]
        indexes = {
            "budget": _header_index(headers, "бюджет", "мест"),
            "special": _header_index(headers, "особ", "квот"),
            "targeted": _header_index(headers, "целев", "квот"),
            "separate": _header_index(headers, "отдель", "квот"),
            "paid": _header_index(headers, "платн"),
        }
        current_direction: str | None = None
        for row_number, cells in enumerate(table["rows"], start=1):
            text = " | ".join(cells)
            codes = direction_codes(text)
            if codes:
                current_direction = codes[0]
            program_name = _program_name(cells)
            if not program_name:
                continue
            quota_values: list[RawAdmissionQuota] = []
            for quota_name, quota_type in (("special", "special"), ("targeted", "targeted"), ("separate", "separate")):
                quota_index = indexes[quota_name]
                value = _cell_int(cells, quota_index)
                if value is not None:
                    quota_values.append(RawAdmissionQuota(quota_type=quota_type, source_name=headers[quota_index] if quota_index is not None else quota_name, places=value))
            budget = _cell_int(cells, indexes["budget"])
            paid = _cell_int(cells, indexes["paid"])
            if budget is not None or quota_values:
                result.append(FactObservation(current_direction, program_name, admission_year, "full_time", "budget", budget, (), tuple(quota_values), (), (), "hse_admission_places", row_number))
            if paid is not None:
                result.append(FactObservation(current_direction, program_name, admission_year, "full_time", "paid", paid, (), (), (), (), "hse_admission_places", row_number))
    return tuple(result)


def parse_tuition(snapshot: RawSourceSnapshot, admission_year: int) -> tuple[FactObservation, ...]:
    result: list[FactObservation] = []
    for table in extract_tables(snapshot.body):
        for row_number, cells in enumerate(table["rows"], start=1):
            program_name = _program_name(cells)
            if not program_name:
                continue
            amounts = [int(value.replace(" ", "")) for value in re.findall(r"(?<!\d)(\d{3,5})(?!\d)", " ".join(cells))]
            if not amounts:
                continue
            amount = Decimal(str(amounts[-1] * 1000))
            tuition = RawAdmissionTuition(amount=amount, currency="RUB", academic_year=str(admission_year), period="academic_year", study_form="full_time")
            result.append(FactObservation(None, program_name, admission_year, "full_time", "paid", None, (), (), (), (tuition,), "hse_tuition", row_number))
    return tuple(result)


def parse_historical_passing(snapshot: RawSourceSnapshot, admission_year: int) -> tuple[FactObservation, ...]:
    result: list[FactObservation] = []
    for table in extract_tables(snapshot.body):
        headers = [clean_text(value).casefold() for value in table["headers"]]
        score_type = "paid" if any("плат" in value for value in headers) else "budget"
        for row_number, cells in enumerate(table["rows"], start=1):
            program_name = _program_name(cells)
            if not program_name:
                continue
            scores = [Decimal(value) for value in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", " ".join(cells)) if 100 <= int(value) <= 400]
            if not scores:
                continue
            passing = RawAdmissionPassingScore(score_type=score_type, competition_type="general", status="numeric", score=scores[-1])
            result.append(FactObservation(None, program_name, admission_year, "full_time", "paid" if score_type == "paid" else "budget", None, (), (), (passing,), (), "hse_passing_scores", row_number))
    return tuple(result)


def parse_enrollment_document(snapshot: RawSourceSnapshot) -> tuple[EnrollmentObservation, ...]:
    text = extract_pdf_text(snapshot.body)
    if not text:
        return ()
    year_match = re.search(r"\b(20\d{2})\b", text)
    admission_year = int(year_match.group(1)) if year_match else snapshot.captured_at.year
    header = text.casefold()
    competition = _competition_type(header)
    funding = "paid" if any(token in header for token in ("платн", "договор")) else "budget"
    study_form = "full_time" if "очная" in header else "unknown"
    observations: list[EnrollmentObservation] = []
    for row_number, block in _pdf_rows(text):
        code_match = re.search(r"(?<!\d)(\d{2}\.\d{2}\.\d{2})(?!\d)", block)
        direction = code_match.group(1) if code_match else None
        after_identifier = block[code_match.end() :] if code_match else block
        numbers = [int(value) for value in re.findall(r"(?<!\d)(\d{1,3})(?!\d)", after_identifier) if int(value) <= 400]
        name = _enrollment_program_name(block, code_match)
        if not name or len(name) < 3:
            continue
        if competition == "bvi":
            observations.append(EnrollmentObservation(direction, name, admission_year, study_form, funding, competition, "bvi", None, row_number))
        elif numbers:
            observations.append(EnrollmentObservation(direction, name, admission_year, study_form, funding, competition, "numeric", Decimal(str(numbers[-1])), row_number))
    return tuple(observations)


def _pdf_rows(text: str) -> tuple[tuple[int, str], ...]:
    rows: list[tuple[int, list[str]]] = []
    current: tuple[int, list[str]] | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        match = re.match(r"^\s*(\d{5,10})(?:\s+\*)?\s+(.*)$", line)
        if match:
            if current is not None:
                rows.append(current)
            current = (len(rows) + 1, [line])
        elif current is not None:
            current[1].append(line)
    if current is not None:
        rows.append(current)
    return tuple((number, "\n".join(lines)) for number, lines in rows)


def _enrollment_program_name(block: str, code_match: re.Match[str] | None) -> str:
    lines = block.splitlines()
    if not lines:
        return ""
    first_line = re.sub(r"^\s*\d{5,10}(?:\s+\*)?\s+", "", lines[0])
    first_line = re.sub(r"\s+\d{1,3}\s+\d{1,3}\s+\d{1,3}\s*$", "", first_line)
    first_parts = [clean_text(part) for part in re.split(r"\s{2,}", first_line) if clean_text(part)]
    first_textual = [part for part in first_parts if not re.fullmatch(r"[\d\s.,]+", part)]
    if code_match and len(first_textual) >= 3:
        program_parts = [first_textual[-2]]
    else:
        program_parts = [first_textual[-1]] if len(first_textual) >= 2 else []
    for continuation in lines[1:]:
        if code_match:
            continue
        continuation_parts = [clean_text(part) for part in re.split(r"\s{2,}", continuation) if clean_text(part)]
        textual = [part for part in continuation_parts if not re.fullmatch(r"[\d\s.,]+", part)]
        first_non_space = len(continuation) - len(continuation.lstrip())
        if len(textual) >= 2 or (textual and first_non_space >= 35):
            program_parts.append(textual[-1])
        elif textual and program_parts and program_parts[-1].casefold().split()[-1] in {"в", "с", "и", "на", "по", "для"}:
            program_parts.append(textual[0])
    if program_parts:
        return clean_text(" ".join(program_parts)).strip(" -—–;:")
    value = block[code_match.end() :] if code_match else block
    value = re.sub(r"(?<!\d)\d{1,3}(?!\d)", " ", value)
    return clean_text(value).strip(" -—–;:")


def _competition_type(header: str) -> str:
    if "без вступительн" in header:
        return "bvi"
    if "целев" in header:
        return "targeted"
    if "отдельн" in header:
        return "separate_quota"
    if "особ" in header or "специальн" in header:
        return "special_quota"
    return "general"


def _program_name(cells: list[str]) -> str | None:
    for value in cells:
        value = clean_text(value)
        lowered = value.casefold()
        if not value or any(token in lowered for token in _PROGRAM_EXCLUSIONS):
            continue
        if direction_codes(value):
            value = re.sub(r"\d{2}\.\d{2}\.\d{2}", "", value).strip(" -—–")
        if len(value) >= 4 and re.search(r"[а-яa-z]{3}", value, re.IGNORECASE) and not re.fullmatch(r"[\d\s.,/%+-]+", value):
            return value
    return None


def _header_index(headers: list[str], *tokens: str) -> int | None:
    return next((index for index, header in enumerate(headers) if all(token in header for token in tokens)), None)


def _cell_int(cells: list[str], index: int | None) -> int | None:
    if index is None or index >= len(cells):
        return None
    value = clean_text(cells[index]).replace(" ", "")
    if not value or value in {"-", "—", "–"}:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _dedupe_exams(values: list[ExamObservation]) -> list[ExamObservation]:
    result: list[ExamObservation] = []
    seen: set[tuple[str | None, str, tuple[tuple[str, str | None], ...]]] = set()
    for value in values:
        key = (value.direction_code, value.program_name, tuple((item.subject, str(item.minimum_score)) for item in value.exams))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


__all__ = ["EnrollmentObservation", "ExamObservation", "FactObservation", "parse_enrollment_document", "parse_historical_passing", "parse_minimum_exams", "parse_places", "parse_tuition"]
