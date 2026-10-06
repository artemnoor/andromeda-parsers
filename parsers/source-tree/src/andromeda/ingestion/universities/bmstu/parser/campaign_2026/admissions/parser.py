from __future__ import annotations

import re
from typing import Any

import pdfplumber

from ..common import clean_text, normalize_code


SUBJECTS = (
    "russian_language",
    "mathematics",
    "physics",
    "informatics_and_ict",
    "social_studies",
    "history",
    "foreign_language",
    "biology",
    "chemistry",
    "literature",
    "creative_exam",
)


def _pdf(body: bytes) -> pdfplumber.PDF:
    import io

    return pdfplumber.open(io.BytesIO(body))


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip()


def _cell_choice(page: pdfplumber.page.Page, cell: tuple[float, float, float, float] | None) -> bool:
    if cell is None:
        return False
    x0, top, x1, bottom = cell
    width = x1 - x0
    height = bottom - top
    if width <= 0 or height <= 0:
        return False
    for rect in page.rects:
        color = rect.get("non_stroking_color")
        if not rect.get("fill") or not isinstance(color, tuple) or len(color) < 3:
            continue
        # Appendix 1 uses the same pale blue background for the selectable subjects.
        r, g, b = color[:3]
        if not (0.70 <= r <= 0.86 and 0.78 <= g <= 0.92 and 0.88 <= b <= 0.99):
            continue
        overlap_x = max(0.0, min(x1, float(rect["x1"])) - max(x0, float(rect["x0"])))
        overlap_y = max(0.0, min(bottom, float(rect["bottom"])) - max(top, float(rect["top"])))
        if overlap_x / width >= 0.80 and overlap_y / height >= 0.65:
            return True
    return False


def parse_exam_requirements_pdf(body: bytes, source_url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse direction minima and retain the colored OR choices from Appendix 1."""
    rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    with _pdf(body) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            heading = _text(page.extract_text() or "")[:420]
            for table_no, table in enumerate(page.find_tables(), start=1):
                for row_no, table_row in enumerate(table.rows, start=1):
                    values = table_row.cells
                    cells = [(_text(value) if value else "") for value in table.extract()[row_no - 1]]
                    code = normalize_code(cells[1]) if len(cells) > 1 else ""
                    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", code):
                        raw_rows.append({
                            "source_url": source_url,
                            "page": page_no,
                            "table": table_no,
                            "row": row_no,
                            "row_kind": "non_direction_or_continuation",
                            "cells": cells,
                        })
                        continue
                    exams: list[dict[str, Any]] = []
                    for col_no, subject in enumerate(SUBJECTS, start=2):
                        value = cells[col_no] if col_no < len(cells) else ""
                        match = re.search(r"(?<!\d)(\d{1,3})(?!\d)", value)
                        if not match:
                            continue
                        score = int(match.group(1))
                        if score > 100:
                            continue
                        is_choice = _cell_choice(page, values[col_no] if col_no < len(values) else None)
                        rank_match = re.search(r"\b(I{1,3}|IV)\b", value)
                        exams.append({
                            "exam_key": f"exam:bmstu:2026:{subject}",
                            "subject_code": subject,
                            "minimum_score": score,
                            "is_choice": is_choice,
                            "tiebreak_rank": rank_match.group(1) if rank_match else None,
                        })
                    optional = [item for item in exams if item["is_choice"]]
                    required = [item for item in exams if not item["is_choice"]]
                    tree = {"operator": "AND", "children": [{"exam": item} for item in required]}
                    if optional:
                        tree["children"].append({"operator": "OR", "min_count": 1, "children": [{"exam": item} for item in optional]})
                    record = {
                        "external_key": f"exam_requirement:bmstu:2026:app1:{code}:p{page_no}:t{table_no}:r{row_no}",
                        "direction_code": code,
                        "applicant_category_text": heading,
                        "exams": exams,
                        "requirement_tree": tree,
                        "source_url": source_url,
                        "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                        "source_row": cells,
                    }
                    rows.append(record)
                    raw_rows.append({**record, "row_kind": "direction"})
    return rows, raw_rows


def _direction_code_by_table_row(
    page: pdfplumber.page.Page,
    table: pdfplumber.table.Table,
    carried_direction_text: str,
) -> tuple[dict[int, str], str]:
    """Assign merged direction-code cells to the source rows they span.

    Appendix 8.1 merges direction cells vertically. On some pages pdfplumber
    returns those cells as ``None`` for every underlying row even though the
    code is printed in the middle of the merged cell. Full-width horizontal
    rules delimit the direction groups; code words are placed into those bands
    by their PDF coordinates.
    """
    code_cell = next((row.cells[1] for row in table.rows if len(row.cells) > 1 and row.cells[1] is not None), None)
    if code_cell is None:
        return {}, carried_direction_text
    code_x0, _, code_x1, _ = code_cell
    table_x0, table_y0, table_x1, table_y1 = table.bbox
    boundary_candidates = [table_y0, table_y1]
    for edge in page.edges:
        if (
            edge.get("orientation") == "h"
            and float(edge["x0"]) <= table_x0 + 2
            and float(edge["x1"]) >= table_x1 - 2
            and table_y0 - 1 <= float(edge["top"]) <= table_y1 + 1
        ):
            boundary_candidates.append(float(edge["top"]))
    boundary_candidates.sort()
    boundary_groups: list[list[float]] = []
    for value in boundary_candidates:
        if not boundary_groups or value - boundary_groups[-1][-1] > 1.0:
            boundary_groups.append([value])
        else:
            boundary_groups[-1].append(value)
    boundaries = [sum(group) / len(group) for group in boundary_groups]

    code_words = [
        word for word in page.extract_words(x_tolerance=1, y_tolerance=1)
        if code_x0 - 1 <= float(word["x0"])
        and float(word["x1"]) <= code_x1 + 1
        and re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", str(word["text"]))
    ]
    direction_for_row: dict[int, str] = {}
    current_direction = carried_direction_text
    for top, bottom in zip(boundaries, boundaries[1:]):
        words = [
            word for word in code_words
            if top - 1 <= (float(word["top"]) + float(word["bottom"])) / 2 <= bottom + 1
        ]
        codes = list(dict.fromkeys(str(word["text"]) for word in sorted(words, key=lambda word: float(word["top"]))))
        if codes:
            current_direction = " / ".join(codes)
        for row_no, row in enumerate(table.rows, start=1):
            department_cell = row.cells[3] if len(row.cells) > 3 else None
            if department_cell is None:
                continue
            center = (float(department_cell[1]) + float(department_cell[3])) / 2
            if top - 0.5 <= center <= bottom + 0.5 and current_direction:
                direction_for_row[row_no] = current_direction
    return direction_for_row, current_direction


def parse_intake_plan_pdf(body: bytes, source_url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse Appendix 8.1 while following its campus sections and page continuations.

    The Moscow section starts under an explicit ``город Москва`` label. Later
    rows stay in scope until a printed branch heading (Мытищи or Калуга) is
    encountered. Direction codes may be visually merged across several rows
    and page breaks, so the last explicit code is carried through the source
    table; the raw cell and inherited value are both retained for audit.
    """
    offers: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    campus_scope = "unknown"
    carried_direction_text = ""
    saw_moscow_heading = False
    program_rows_seen = 0
    campus_markers = (
        (re.compile(r"Москва", re.IGNORECASE), "head_moscow"),
        (re.compile(r"Мытищи", re.IGNORECASE), "mytishchi_branch"),
        (re.compile(r"Калуга|Калуж", re.IGNORECASE), "kaluga_branch"),
    )
    with _pdf(body) as pdf:
        if not pdf.pages:
            raise ValueError("admission plan PDF has no pages")
        first_page_text = _text(pdf.pages[0].extract_text() or "").casefold()
        if "приложение 8.1" not in first_page_text or "2026" not in first_page_text:
            raise ValueError("PDF does not identify itself as Appendix 8.1 for the 2026 campaign")
        for page_no, page in enumerate(pdf.pages, start=1):
            markers = sorted(
                (float(match["top"]), scope)
                for pattern, scope in campus_markers
                for match in page.search(pattern)
            )
            marker_index = 0
            for table_no, table in enumerate(page.find_tables(), start=1):
                extracted = table.extract()
                direction_by_row, carried_direction_text = _direction_code_by_table_row(page, table, carried_direction_text)
                cells_by_row = {
                    row_no: [_text(value) if value else "" for value in extracted[row_no - 1]]
                    for row_no in range(1, len(table.rows) + 1)
                }
                scope_by_row: dict[int, str] = {}
                for row_no, table_row in enumerate(table.rows, start=1):
                    cell_boxes = [cell for cell in table_row.cells if cell is not None]
                    row_top = min((float(cell[1]) for cell in cell_boxes), default=float(table.bbox[1]))
                    while marker_index < len(markers) and markers[marker_index][0] <= row_top:
                        campus_scope = markers[marker_index][1]
                        marker_index += 1
                        if campus_scope == "head_moscow":
                            saw_moscow_heading = True
                    scope_by_row[row_no] = campus_scope

                offer_groups: dict[int, dict[str, Any]] = {}
                offer_start_by_member_row: dict[int, int] = {}
                offer_key_by_member_row: dict[int, str] = {}
                for row_no, table_row in enumerate(table.rows, start=1):
                    cells = cells_by_row[row_no]
                    department_text = cells[3] if len(cells) > 3 else ""
                    program_name = cells[5] if len(cells) > 5 else ""
                    budget_places = _integer(cells[7]) if len(cells) > 7 else None
                    if not program_name or budget_places is None:
                        continue
                    program_cell = table_row.cells[5] if len(table_row.cells) > 5 else None
                    if program_cell is None:
                        department_cell = table_row.cells[3] if len(table_row.cells) > 3 else None
                        program_cell = department_cell
                    if program_cell is None:
                        member_rows = [row_no]
                    else:
                        span_top, span_bottom = float(program_cell[1]), float(program_cell[3])
                        member_rows = []
                        for member_no, member_row in enumerate(table.rows, start=1):
                            department_cell = member_row.cells[3] if len(member_row.cells) > 3 else None
                            if department_cell is None:
                                continue
                            center = (float(department_cell[1]) + float(department_cell[3])) / 2
                            if span_top - 0.5 <= center <= span_bottom + 0.5:
                                member_rows.append(member_no)
                        if not member_rows:
                            member_rows = [row_no]
                    member_rows = sorted(set(member_rows))
                    department_rows = []
                    source_locators = []
                    for member_no in member_rows:
                        member_cells = cells_by_row[member_no]
                        member_locator = {"page": page_no, "table": table_no, "row": member_no}
                        source_locators.append(member_locator)
                        department_rows.append({
                            "department_code_in_document": member_cells[3] if len(member_cells) > 3 and member_cells[3] else None,
                            "department_name_in_document": member_cells[4] if len(member_cells) > 4 and member_cells[4] else None,
                            "source_locator": member_locator,
                        })
                    effective_direction_text = direction_by_row.get(row_no, "")
                    direction_codes = list(dict.fromkeys(
                        re.findall(r"(?<!\d)\d{2}\.\d{2}\.\d{2}(?!\d)", effective_direction_text)
                    ))
                    offer_key = f"offering:bmstu:2026:app8.1:p{page_no}:t{table_no}:r{row_no}"
                    offer_groups[row_no] = {
                        "external_key": offer_key,
                        "campaign_year": 2026,
                        "direction_code": direction_codes[0] if len(direction_codes) == 1 else None,
                        "direction_codes_in_document": direction_codes,
                        "direction_code_in_document": effective_direction_text or None,
                        "department_code_in_document": department_text,
                        "department_codes_in_document": [item["department_code_in_document"] for item in department_rows if item["department_code_in_document"]],
                        "department_name_in_document": cells[4] or None if len(cells) > 4 else None,
                        "department_rows_in_document": department_rows,
                        "program_name_in_document": program_name,
                        "study_duration_label": cells[6] or None if len(cells) > 6 else None,
                        "budget_places_at_department": budget_places,
                        "paid_places_at_department": _integer(cells[8]) if len(cells) > 8 else None,
                        "special_quota_places_direction": _integer(cells[9]) if len(cells) > 9 else None,
                        "separate_quota_places_direction": _integer(cells[10]) if len(cells) > 10 else None,
                        "seat_scope_in_document": "multiple_department_rows" if len(member_rows) > 1 else "single_department_row",
                        "campus_scope": scope_by_row[row_no],
                        "source_url": source_url,
                        "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                        "source_locators": source_locators,
                        "source_row": cells,
                    }
                    for member_no in member_rows:
                        offer_start_by_member_row[member_no] = row_no
                    if scope_by_row[row_no] == "head_moscow":
                        offers.append(offer_groups[row_no])
                        program_rows_seen += 1
                        for member_no in member_rows:
                            offer_key_by_member_row[member_no] = offer_key

                for row_no, table_row in enumerate(table.rows, start=1):
                    cells = cells_by_row[row_no]
                    raw_direction_text = cells[1] if len(cells) > 1 else ""
                    effective_direction_text = direction_by_row.get(row_no, "")
                    department_text = cells[3] if len(cells) > 3 else ""
                    program_name = cells[5] if len(cells) > 5 else ""
                    is_start = row_no in offer_groups
                    linked_offer_key = offer_key_by_member_row.get(row_no)
                    group_start = offer_start_by_member_row.get(row_no)
                    group_locator = {"page": page_no, "table": table_no, "row": group_start} if group_start else None
                    row_key = f"admission_plan_source_row:bmstu:2026:app8.1:p{page_no}:t{table_no}:r{row_no}"
                    row_record = {
                        "external_key": row_key,
                        "source_url": source_url,
                        "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                        "campus_scope": scope_by_row[row_no],
                        "included_in_moscow_offers": linked_offer_key is not None,
                        "row_kind": "offering" if is_start else "offering_department_association" if group_start else "header_or_incomplete",
                        "direction_code_in_source_cell": raw_direction_text or None,
                        "direction_code_in_document": effective_direction_text or None,
                        "department_code_in_document": department_text or None,
                        "program_name_in_document": program_name or None,
                        "program_start_locator": group_locator,
                        "normalized_offering_key": linked_offer_key,
                        "cells": cells,
                    }
                    raw_rows.append(row_record)
        if not saw_moscow_heading:
            raise ValueError("Appendix 8.1 does not contain an explicit Moscow campus heading")
        if program_rows_seen == 0:
            raise ValueError("Appendix 8.1 contains no recognizable admission-plan rows")
    return offers, raw_rows


def parse_achievements_pdf(body: bytes, source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with _pdf(body) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table_no, table in enumerate(page.find_tables(), start=1):
                for row_no, row in enumerate(table.extract(), start=1):
                    cells = [_text(v) if v else "" for v in row]
                    if len(cells) < 2 or not cells[0].isdigit() or not cells[1]:
                        continue
                    points = _integer(cells[3]) if len(cells) > 3 else None
                    records.append({
                        "external_key": f"achievement_policy:bmstu:2026:app6:{cells[0]}",
                        "campaign_year": 2026,
                        "row_number": int(cells[0]),
                        "achievement_name": cells[1],
                        "required_document": cells[2] or None if len(cells) > 2 else None,
                        "additional_points": points,
                        "source_url": source_url,
                        "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                    })
    return records


def parse_targeted_quota_pdf(body: bytes, source_url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    with _pdf(body) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table_no, table in enumerate(page.find_tables(), start=1):
                extracted = table.extract()
                campus_label = ""
                direction_code = ""
                for row_no, row in enumerate(extracted, start=1):
                    cells = [_text(value) if value else "" for value in row]
                    if not any(cells):
                        continue
                    if cells[0]:
                        campus_label = cells[0]
                    code_match = re.search(r"\b\d{2}[.‐‑‒–—−]\d{2}[.‐‑‒–—−]\d{2}\b", cells[1] if len(cells) > 1 else "")
                    if code_match:
                        direction_code = normalize_code(code_match.group(0))
                    branch = any(token in campus_label.casefold() for token in ("калуж", "мытищ", "филиал"))
                    kind = "branch" if branch else "head_or_unresolved"
                    row_key = f"target_quota_source_row:bmstu:2026:app8.3:p{page_no}:t{table_no}:r{row_no}"
                    raw_rows.append({"external_key": row_key, "source_url": source_url, "source_locator": {"page": page_no, "table": table_no, "row": row_no}, "campus_scope": kind, "cells": cells})
                    if not direction_code or len(cells) < 8 or not cells[2]:
                        continue
                    if branch:
                        continue
                    count = _integer(cells[7])
                    if count is None:
                        continue
                    records.append({
                        "external_key": f"competition_pool:bmstu:2026:target:app8.3:p{page_no}:t{table_no}:r{row_no}",
                        "campaign_year": 2026,
                        "direction_code": direction_code,
                        "department_code": None,
                        "quota_type": "targeted",
                        "funding_type": "budget",
                        "places": count,
                        "scope_level": "direction_and_target_organization",
                        "target_organization": cells[2],
                        "target_organization_inn": cells[3] or None,
                        "target_organization_kpp": cells[4] or None,
                        "target_organization_ogrn": cells[5] or None,
                        "target_region": cells[6] or None,
                        "campus_label_in_document": campus_label or None,
                        "source_url": source_url,
                        "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                    })
    return records, raw_rows


def _integer(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{1,3})(?!\d)", value)
    return int(match.group(1)) if match else None


__all__ = ["parse_achievements_pdf", "parse_exam_requirements_pdf", "parse_intake_plan_pdf", "parse_targeted_quota_pdf"]
