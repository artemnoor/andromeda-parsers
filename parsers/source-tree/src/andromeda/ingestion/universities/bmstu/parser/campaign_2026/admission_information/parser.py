from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from ..common import clean_text, normalize_code


def _number(value: str) -> int | None:
    value = clean_text(value)
    if value in {"", "-", "—", "–"}:
        return None
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def parse_admission_information(body: bytes, source_url: str) -> dict[str, list[dict[str, Any]]]:
    """Extract aggregate paid-admission outcomes; never emit applicant-level rows."""
    soup = BeautifulSoup(body, "html.parser")
    raw_tables: list[dict[str, Any]] = []
    historical_results: list[dict[str, Any]] = []

    for table_no, table in enumerate(soup.find_all("table"), start=1):
        rows: list[list[str]] = []
        for row in table.find_all("tr"):
            cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"], recursive=False)]
            if any(cells):
                rows.append(cells)
        if not rows:
            continue
        raw_tables.append({
            "external_key": f"admission_information_table:bmstu:table{table_no}",
            "source_url": source_url,
            "table_number": table_no,
            "rows": rows,
        })

        years: list[int] = []
        for value in rows[0]:
            match = re.fullmatch(r"20\d{2}", value)
            if match:
                years.append(int(value))
        metric_header = rows[1] if len(rows) > 1 else []
        if not years or not metric_header or not any("КОЛИЧЕСТВО ЗАЧИСЛЕННЫХ" in item.upper() for item in metric_header):
            continue
        if len(metric_header) < len(years) * 3:
            continue

        current_direction_code: str | None = None
        for row_no, cells in enumerate(rows[2:], start=3):
            if len(cells) < 1 + len(years) * 3:
                continue
            label = cells[0]
            code_match = re.match(r"^\s*(\d{2}[.‐‑‒–—−]\d{2}[.‐‑‒–—−]\d{2})\s*$", label)
            if code_match:
                current_direction_code = normalize_code(code_match.group(1))
                scope_type = "direction"
                scope_label = label
                department_code = None
            else:
                dept_match = re.search(r"кафедра\s*([А-ЯЁA-Z0-9]+)", label, re.I)
                if not current_direction_code:
                    continue
                scope_type = "department" if dept_match else "subgroup"
                scope_label = label
                department_code = dept_match.group(1) if dept_match else None

            for year_index, year in enumerate(years):
                offset = 1 + year_index * 3
                admitted = _number(cells[offset]) if offset < len(cells) else None
                minimum = _number(cells[offset + 1]) if offset + 1 < len(cells) else None
                maximum = _number(cells[offset + 2]) if offset + 2 < len(cells) else None
                if admitted is None and minimum is None and maximum is None:
                    continue
                key_scope = department_code or ("direction" if scope_type == "direction" else re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "_", scope_label).strip("_"))
                record = {
                    "external_key": f"admission_statistic:bmstu:{year}:{current_direction_code}:paid:{key_scope}",
                    "direction_code": current_direction_code,
                    "direction_key": f"direction:bmstu:{current_direction_code}",
                    "department_code": department_code,
                    "department_key": f"department:bmstu:{department_code}" if department_code else None,
                    "scope_type": scope_type,
                    "scope_label": scope_label,
                    "admission_year": year,
                    "study_form": None,
                    "funding_type": "paid",
                    "outcome_type": "paid_admission_published_aggregate",
                    "admitted_count": admitted,
                    "minimum_score": minimum,
                    "maximum_score": maximum,
                    "average_score": None,
                    "snapshot_date": None,
                    "finality_note": "Official page labels these as admitted students on a paid basis; no dated snapshot is stated.",
                    "source_url": source_url,
                    "source_locator": {"table": table_no, "row": row_no, "year_column": year_index + 1},
                }
                historical_results.append(record)

    visible_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    return {
        "historical_results": historical_results,
        "raw_tables": raw_tables,
        "page_facts": [{"source_url": source_url, "visible_text": visible_text}],
    }


__all__ = ["parse_admission_information"]
