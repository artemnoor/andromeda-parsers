from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterable
from hashlib import sha1
from typing import Any
from urllib.parse import urlparse

from andromeda.ingestion.pdf_policy import DEFAULT_PDF_POLICY, PdfDependencyError, validate_pdf_payload

from ..html import clean_text, parse_number
from ..source_models import FetchedResource, SourceDefinition


def _scope(url: str, configured_scope: str | None) -> str:
    host = urlparse(url).hostname or ""
    if host.startswith(("mf.", "kf.")):
        return "branch"
    if configured_scope:
        return configured_scope
    return "head_university"


def _record(source: SourceDefinition, captured_at: str, record_type: str, values: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "record_type": record_type,
        "source_id": source.id,
        "source_url": source.url,
        "source_scope": _scope(source.url, source.scope),
        "observed_at": captured_at,
        **values,
    }
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    payload["record_id"] = f"{source.id}:{record_type}:{sha1(stable.encode('utf-8')).hexdigest()[:16]}"
    return payload


def _dedupe_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated PDF rows while keeping the first deterministic record."""

    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        key = (
            record.get("record_type"),
            record.get("source_id"),
            record.get("code"),
            record.get("name"),
            record.get("url"),
            record.get("document_url"),
            record.get("row_no"),
            record.get("program_code"),
            record.get("direction_code"),
            record.get("discipline"),
            record.get("semester"),
            record.get("course"),
            record.get("profile_code"),
            record.get("program_profile_code"),
            record.get("source_document_url"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


_EDUCATION_CODE_RE = re.compile(r"(?<!\d)(?:\d{2}|\d)\.\d{2}\.\d{2}(?:-\d+)?(?!\d)")


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip().casefold()


def _education_code(value: Any) -> str | None:
    match = _EDUCATION_CODE_RE.search(clean_text(value))
    return match.group(0) if match else None


def _pdf_layout_text(body: bytes) -> str:
    """Extract text with Poppler when available.

    BMSTU study-plan PDFs use a font encoding that fitz/pdfplumber expose as
    replacement characters. Poppler's text layer preserves the Cyrillic and
    the fixed column layout, so it is the preferred reader for this document
    family. The normal PDF reader remains the portable fallback.
    """
    validate_pdf_payload(body)
    executable = shutil.which("pdftotext")
    if not executable:
        for candidate in (
            r"C:\\poppler-24.08.0\\Library\\bin\\pdftotext.exe",
            r"C:\\Program Files\\poppler\\Library\\bin\\pdftotext.exe",
        ):
            if shutil.which(candidate):
                executable = candidate
                break
    if not executable:
        raise PdfDependencyError("poppler_missing", "pdftotext is required for BMSTU study-plan PDFs")
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(body)
        pdf_path = handle.name
    try:
        result = subprocess.run(
            [executable, "-layout", "-enc", "UTF-8", pdf_path, "-"],
            capture_output=True,
            timeout=DEFAULT_PDF_POLICY.parser_timeout_seconds,
            check=False,
        )
        return result.stdout.decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    finally:
        try:
            import os

            os.unlink(pdf_path)
        except OSError:
            pass


_PLAN_PROFILE_CODE_RE = re.compile(r"(?<!\d)(\d{1,2}\.\d{2}\.\d{2})\s*([\-–—/])\s*(\d{1,3})(?!\d)")


def _canonical_plan_code(value: Any) -> str:
    """Normalise profile separators without changing slash-based codes."""
    return re.sub(r"\s+", "", clean_text(value)).replace("–", "-").replace("—", "-")


def _plan_header_value(line: str) -> str | None:
    parts = re.split(r"\s+[—–]\s+", line, maxsplit=1)
    return clean_text(parts[1]) if len(parts) == 2 else None


def _plan_header(lines: list[str]) -> dict[str, Any]:
    direction_line = next((line for line in lines[:35] if "Направление подготовки" in line), "")
    profile_line = next((line for line in lines[:35] if re.search(r"\bПрофиль\b", line)), "")
    qualification_line = next((line for line in lines[:35] if "Квалификация" in line), "")
    duration_line = next((line for line in lines[:35] if "Срок обучения" in line), "")
    form_line = next((line for line in lines[:35] if "Форма обучения" in line), "")
    faculty_line = next((line for line in lines[:35] if "Факультет" in line), "")
    department_line = next((line for line in lines[:35] if "Кафедра" in line), "")

    direction_value = _plan_header_value(direction_line) or ""
    direction_code = _education_code(direction_value or direction_line)
    direction_name: str | None = direction_value
    if direction_code:
        direction_name = re.sub(rf"^\s*{re.escape(direction_code)}\s*,?\s*", "", direction_value).strip() or None

    profile_value = _plan_header_value(profile_line) or ""
    profile_match = _PLAN_PROFILE_CODE_RE.search(profile_value)
    profile_code = _canonical_plan_code(profile_match.group(0)) if profile_match else None
    profile_name = _PLAN_PROFILE_CODE_RE.sub("", profile_value).strip(" ,—–-") or None

    duration_value = _plan_header_value(duration_line) or ""
    year_match = re.search(r"Год начала обучения\s*[—–-]\s*(20\d{2})", duration_line)
    duration_match = re.search(r"Срок обучения\s*[—–-]\s*(.*?)(?=\s+Год начала обучения|\s*$)", duration_line)
    return {
        "direction_code": direction_code,
        "direction_name": direction_name,
        "program_profile_code": profile_code,
        "program_profile": profile_name,
        "qualification": _plan_header_value(qualification_line),
        "duration": duration_match.group(1).strip() if duration_match else duration_value or None,
        "education_year": int(year_match.group(1)) if year_match else None,
        "form": _plan_header_value(form_line),
        "faculty": _plan_header_value(faculty_line),
        "department": _plan_header_value(department_line),
    }


def _semester_columns(header: str) -> tuple[list[int], list[int | None]]:
    matches = list(re.finditer(r"Семестр\s+(\d+)\s*-\s*(\d+)\s+нед", header))
    starts = [max(0, match.start() - 4) for match in matches[:12]]
    weeks: list[int | None] = [int(match.group(2)) for match in matches[:12]]
    return starts, weeks


def _numeric_values(value: str) -> list[int | float]:
    return [number for item in re.findall(r"-?\d+(?:[.,]\d+)?", value) if (number := parse_number(item)) is not None]


def _study_plan_semester_summary(lines: list[str]) -> list[dict[str, Any]]:
    marker = next((index for index, line in enumerate(lines) if "IV. РАСПРЕДЕЛЕНИЕ ПО СЕМЕСТРАМ" in line), None)
    if marker is None:
        return []
    header_index = next((index for index in range(marker, min(len(lines), marker + 8)) if "Семестр 1" in lines[index]), None)
    if header_index is None:
        return []
    starts, weeks = _semester_columns(lines[header_index])
    if not starts:
        plain_matches = list(re.finditer(r"Семестр\s+(\d+)", lines[header_index]))
        starts = [max(0, match.start() - 4) for match in plain_matches[:12]]
        week_header = next(
            (line for line in lines[:marker] if "Семестр 1" in line and "нед" in line),
            "",
        )
        _, weeks = _semester_columns(week_header)
        weeks = weeks[: len(starts)] if weeks else [None] * len(starts)
    if not starts:
        return []
    metric_names = {
        "трудоемкость в неделю": "weekly_hours",
        "аудиторные занятия в неделю": "weekly_audited_hours",
        "количество курсовых работ": "coursework_count",
        "количество курсовых проектов": "course_project_count",
        "количество зачетов": "credits_control_count",
        "количество экзаменов": "exam_count",
        "государственный экзамен": "state_exam_count",
        "квалификационная работа": "vkr_defense_count",
    }
    metrics: dict[str, list[int | float | None]] = {}
    for line in lines[header_index + 1 :]:
        label = _normalized_text(line[: starts[0]])
        if not label:
            continue
        metric = next((name for fragment, name in metric_names.items() if fragment in label), None)
        if not metric:
            if "стр " in label:
                break
            continue
        values: list[int | float | None] = []
        numbers = _numeric_values(line)
        for index in range(len(starts)):
            values.append(numbers[index] if index < len(numbers) else None)
        metrics[metric] = values
    result: list[dict[str, Any]] = []
    for index, week_count in enumerate(weeks, start=1):
        item: dict[str, Any] = {
            "semester": index,
            "course": (index + 1) // 2,
            "weeks": week_count,
        }
        for key, values in metrics.items():
            item[key] = values[index - 1] if index - 1 < len(values) else None
        result.append(item)
    return result


def _study_plan_overall_totals(lines: list[str], first_semester_start: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, line in enumerate(lines):
        if "Общая трудоемкость основной образовательной" not in line:
            continue
        values = _numeric_values(line[:first_semester_start])
        if len(values) < 7:
            continue
        label = " ".join(lines[index : index + 2])
        key = "overall_astronomical" if "астрономических" in label else "overall_academic"
        result[key] = {
            "total_credits": values[0],
            "total_hours": values[1],
            "audited_hours": values[2],
            "lectures": values[3],
            "practices": values[4],
            "labs": values[5],
            "self_study": values[6],
        }
    return result


def _study_plan_records(
    source: SourceDefinition,
    resource: FetchedResource,
    captured_at: str,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Parse a BMSTU study-plan PDF into header, summary and semester rows.

    The PDF is a fixed-width A3 table.  A discipline has one total workload
    block followed by one compact block per semester: ZET, hours, audited
    hours, self-study and the control type.  The previous parser copied the
    total lecture/practice/lab values into every semester and associated a
    plan with the first profile of a direction.  Keep those values as totals,
    but make the semester data explicit and preserve the PDF's own profile
    code so the projection can link the document to the right programme.
    """
    context = context or {}
    text = _pdf_layout_text(resource.body)
    if not text or "ПЛАН УЧЕБНОГО ПРОЦЕССА" not in text:
        return []
    lines = text.splitlines()
    plan_header = _plan_header(lines)
    direction_code = plan_header.get("direction_code") or context.get("direction_code")
    profile_code = plan_header.get("program_profile_code") or context.get("profile_code")
    profile_name = plan_header.get("program_profile") or context.get("program_profile") or context.get("title")
    faculty = plan_header.get("faculty")
    department = plan_header.get("department")
    form = plan_header.get("form")

    header_index = next((index for index, line in enumerate(lines) if "Шифр" in line and "Семестр 1" in line), None)
    if header_index is None:
        return []
    # The PDF repeats the plan header on every page, but the fixed-width
    # coordinates are not identical on all pages. Keep a separate set of
    # semester columns for every repeated header; otherwise page 2/3 rows are
    # sliced with page 1 coordinates and most of their semester cells vanish.
    table_headers = [
        (index, line)
        for index, line in enumerate(lines)
        if "Шифр" in line and "Семестр 1" in line
    ]
    if not table_headers:
        table_headers = [(header_index, lines[header_index])]
    plan_end = next(
        (
            index
            for index, line in enumerate(lines[header_index + 1 :], start=header_index + 1)
            if "IV. РАСПРЕДЕЛЕНИЕ ПО СЕМЕСТРАМ" in line
        ),
        len(lines),
    )
    sections: list[tuple[int, int, list[int], list[int | None]]] = []
    for section_index, (section_header_index, section_header) in enumerate(table_headers):
        if section_header_index >= plan_end:
            continue
        section_end = min(
            table_headers[section_index + 1][0] if section_index + 1 < len(table_headers) else plan_end,
            plan_end,
        )
        starts, weeks = _semester_columns(section_header)
        if len(starts) < 1:
            starts = [193 + index * 35 for index in range(12)]
            weeks = [None] * len(starts)
        sections.append((section_header_index + 1, section_end, starts[:12], weeks[:12]))
    if not sections:
        return []
    semester_starts = sections[0][2]
    semester_weeks = sections[0][3]
    number_re = re.compile(r"-?\d+(?:[.,]\d+)?")
    records: list[dict[str, Any]] = []
    summary_semesters = _study_plan_semester_summary(lines)
    overall_totals = _study_plan_overall_totals(lines, semester_starts[0])
    summary_record = {
        **plan_header,
        "program_code": profile_code or direction_code,
        "direction_code": direction_code,
        "program_profile_code": profile_code,
        "program_profile": profile_name,
        "study_plan_url": context.get("study_plan_url") or context.get("document_url"),
        "download_url": context.get("download_url") or resource.final_url,
        "source_document_url": context.get("document_url") or resource.requested_url,
        "semester_count": len(semester_starts),
        "semester_weeks": semester_weeks,
        "semesters": summary_semesters,
        **overall_totals,
        "is_data_row": True,
    }
    records.append(_record(source, captured_at, "StudyPlanSummary", summary_record))

    for section_start, section_end, section_starts, section_weeks in sections:
        # Re-anchor every semester to the actual number positions observed in
        # this page section. This handles both empty early semesters and the
        # small horizontal shifts in the repeated PDF table header.
        observed_positions: list[list[int]] = [[] for _ in section_starts]
        for line in lines[section_start:section_end]:
            if not re.match(r"^\s*\d+\s+", line):
                continue
            positions = [match.start() for match in number_re.finditer(line)]
            for index, expected in enumerate(section_starts):
                # Do not borrow the last total-workload value from the column
                # immediately to the left. It can sit 8–12 characters before
                # a semester header and would shift the whole page backwards.
                nearby = [position for position in positions if expected - 5 <= position <= expected + 16]
                if nearby:
                    observed_positions[index].append(min(nearby))
        aligned_starts = [
            sorted(values)[len(values) // 2] if values else start
            for start, values in zip(section_starts, observed_positions)
        ]

        for line_index in range(section_start, section_end):
            line = lines[line_index]
            stripped = line.strip()
            if not stripped or stripped.startswith("стр "):
                continue
            row_match = re.match(r"^\s*(\d+)\s+", line)
            if not row_match:
                continue

            # Locate the seven total-workload values by their numeric pattern,
            # rather than by the old hard-coded [80:193] slice. The table
            # shifts on later pages and the old slice dropped valid rows.
            first_semester_start = aligned_starts[0] if aligned_starts else len(line)
            matches = [
                match
                for match in number_re.finditer(line)
                if match.start() >= 55 and match.start() < first_semester_start
            ]
            total_match_index: int | None = None
            total_values: list[int | float | None] = []
            for candidate_index in range(max(0, len(matches) - 6)):
                candidate = matches[candidate_index : candidate_index + 7]
                if len(candidate) < 7:
                    continue
                values = [parse_number(item.group(0)) for item in candidate]
                credits, hours = values[0], values[1]
                if credits is None or hours is None:
                    continue
                if not (0 <= float(credits) <= 100 and float(hours) >= 0):
                    continue
                if float(hours) and float(hours) % 36:
                    continue
                if candidate[-1].end() > first_semester_start:
                    continue
                total_match_index = candidate_index
                total_values = values
                break

            # Some rows intentionally leave total ZET blank. Preserve
            # their remaining total columns instead of dropping the discipline.
            if not total_values:
                fallback = matches[-6:]
                if len(fallback) >= 6:
                    total_values = [parse_number(item.group(0)) for item in fallback]
                    total_values = [None, *total_values]
                elif len(fallback) == 5:
                    values = [parse_number(item.group(0)) for item in fallback]
                    total_values = [None, values[0], values[1], values[2], values[3], 0, values[4]]
                if total_values:
                    total_match_index = len(matches) - len(fallback)
            if len(total_values) < 7:
                continue

            row_no = int(row_match.group(1))
            total_start = matches[total_match_index].start() if total_match_index is not None else first_semester_start
            prefix = line[row_match.end() : total_start]
            prefix_tokens = list(re.finditer(r"\S+", prefix))
            chair_match = next(
                (
                    token
                    for token in reversed(prefix_tokens)
                    if len(token.group(0)) <= 8
                    and token.group(0).upper() == token.group(0)
                    and re.fullmatch(r"[A-ZА-ЯЁ][A-ZА-ЯЁ0-9]{0,7}", token.group(0))
                ),
                None,
            )
            name_end = chair_match.start() if chair_match else len(prefix)
            name = clean_text(prefix[:name_end])
            chair = clean_text(prefix[chair_match.start() : chair_match.end()]) if chair_match else None
            # Long discipline names are wrapped onto the next physical line.
            continuation_index = line_index + 1
            while continuation_index < section_end:
                continuation = lines[continuation_index]
                if re.match(r"^\s*\d+\s+", continuation) or continuation.strip().startswith("стр "):
                    break
                continuation_prefix = continuation[:total_start].strip()
                if not continuation_prefix:
                    if continuation.strip():
                        break
                    continuation_index += 1
                    continue
                if number_re.search(continuation_prefix):
                    break
                normalized_continuation = _normalized_text(continuation_prefix)
                if normalized_continuation.startswith((
                    "вариативная часть",
                    "обязательная часть",
                    "фундаментальная",
                    "дисциплины",
                    "общая трудоемкость",
                )):
                    break
                name = clean_text(f"{name} {continuation_prefix}")
                continuation_index += 1
            if not name or name.casefold() in {"дисциплины (модули)", "дисциплины по выбору"}:
                continue

            total = {
                "total_credits": total_values[0],
                "total_hours": total_values[1],
                "audited_hours": total_values[2],
                "total_lectures": total_values[3],
                "total_practices": total_values[4],
                "total_labs": total_values[5],
                "total_self_study": total_values[6],
            }
            base = {
                "program_code": direction_code or context.get("direction_code"),
                "direction_code": direction_code or context.get("direction_code"),
                "program_profile_code": profile_code or context.get("profile_code"),
                "program_profile": profile_name,
                "direction_name": plan_header.get("direction_name"),
                "faculty": faculty,
                "department": department,
                "chair": chair,
                "qualification": plan_header.get("qualification"),
                "education_year": plan_header.get("education_year") or context.get("year"),
                "form": form,
                "duration": plan_header.get("duration") or context.get("duration"),
                "discipline": name,
                "row_no": row_no,
                "study_plan_url": context.get("study_plan_url") or context.get("document_url"),
                "download_url": context.get("download_url") or resource.final_url,
                "source_document_url": context.get("document_url") or resource.requested_url,
                **total,
                "is_data_row": True,
            }
            emitted = 0
            for semester, start in enumerate(aligned_starts, start=1):
                end = aligned_starts[semester] if semester < len(aligned_starts) else min(len(line), start + 55)
                chunk = line[max(0, start) : max(start, end)]
                tokens = chunk.split()
                semester_numbers = [
                    number
                    for value in tokens
                    if number_re.fullmatch(value)
                    and (number := parse_number(value)) is not None
                ]
                if len(semester_numbers) < 4:
                    continue
                if semester_numbers[0] > 60 or semester_numbers[1] > 2_000:
                    repaired = _repair_semester_cell(line, start, number_re)
                    if repaired is not None:
                        semester_numbers, control = repaired
                    else:
                        control = " ".join(value for value in tokens[4:] if not number_re.fullmatch(value)) or None
                else:
                    control = " ".join(value for value in tokens[4:] if not number_re.fullmatch(value)) or None
                records.append(_record(source, captured_at, "StudyPlan", {
                    **base,
                    "course": (semester + 1) // 2,
                    "semester": semester,
                    "credits": semester_numbers[0],
                    "hours": semester_numbers[1],
                    "audited_hours_semester": semester_numbers[2],
                    "self_study": semester_numbers[3],
                    "lectures": None,
                    "practices": None,
                    "labs": None,
                    "total_lectures": total_values[3],
                    "total_practices": total_values[4],
                    "total_labs": total_values[5],
                    "assessment_type": control,
                    "semester_weeks": section_weeks[semester - 1] if semester - 1 < len(section_weeks) else None,
                }))
                emitted += 1
            if not emitted:
                records.append(_record(source, captured_at, "StudyPlan", {
                    **base,
                    "course": None,
                    "semester": None,
                    "credits": total_values[0],
                    "hours": total_values[1],
                    "self_study": total_values[6],
                    "lectures": total_values[3],
                    "practices": total_values[4],
                    "labs": total_values[5],
                    "total_lectures": total_values[3],
                    "total_practices": total_values[4],
                    "total_labs": total_values[5],
                    "assessment_type": None,
                }))
    return _dedupe_records(records)


def _repair_semester_cell(
    line: str,
    expected_start: int,
    number_re: re.Pattern[str],
) -> tuple[list[int | float], str | None] | None:
    """Recover a valid semester cell when a PDF row is horizontally shifted.

    The study-plan PDFs occasionally render elective rows up to one cell left
    of their header. Candidate values are accepted only when the complete
    four-number workload tuple satisfies the domain-level numeric shape.
    """
    matches = list(number_re.finditer(line))
    for candidate_index, candidate in enumerate(matches):
        if not expected_start - 24 <= candidate.start() <= expected_start + 16:
            continue
        following = matches[candidate_index : candidate_index + 4]
        if len(following) < 4 or following[-1].start() - candidate.start() > 55:
            continue
        values = [
            value
            for match in following
            if (value := parse_number(match.group(0))) is not None
        ]
        if len(values) < 4:
            continue
        if not (0 <= float(values[0]) <= 60 and 0 <= float(values[1]) <= 2_000):
            continue
        if float(values[2]) > float(values[1]) or float(values[3]) > float(values[1]):
            continue
        next_number = next((match for match in matches[candidate_index + 4 :] if match.start() > following[-1].end()), None)
        control_text = line[following[-1].end() : next_number.start() if next_number else len(line)]
        control = " ".join(token for token in control_text.split() if not number_re.fullmatch(token)) or None
        return values, control
    return None


__all__ = ["_study_plan_records"]
