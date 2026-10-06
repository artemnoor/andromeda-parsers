from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from ..common import clean_text, normalize_code


def parse_cost_page(body: bytes, source_url: str) -> dict[str, list[dict[str, Any]]]:
    soup = BeautifulSoup(body, "html.parser")
    records: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for table_no, table in enumerate(soup.find_all("table"), start=1):
        panel = table.find_parent("div", id=re.compile(r"^v-pills-\d+$"))
        panel_text = clean_text(panel.get_text(" ", strip=True)) if panel else ""
        year_match = re.search(r"(20\d{2}\s*/\s*20\d{2})\s*учебн", panel_text, re.I)
        year_label = re.sub(r"\s+", "", year_match.group(1)) if year_match else None
        tab_pane = table.find_parent("div", id=re.compile(r"^list-\d+$"))
        table_category = None
        if tab_pane:
            table_category = "undergraduate_specialty" if tab_pane.get("id") == "list-1" else "masters"
        else:
            accordion = table.find_parent("div", class_="accordion-collapse")
            heading = None
            if accordion and accordion.get("id"):
                button = soup.select_one(f'[data-bs-target="#{accordion.get("id")}"]')
                heading = clean_text(button.get_text(" ", strip=True)) if button else None
            table_category = heading
        rows: list[dict[str, Any]] = []
        for row_no, tr in enumerate(table.find_all("tr"), start=1):
            cells = [clean_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"], recursive=False)]
            if not cells:
                continue
            code_match = re.search(r"\b\d{2}[.‐‑‒–—−]\d{2}[.‐‑‒–—−]\d{2}\b", " ".join(cells))
            code = normalize_code(code_match.group(0)) if code_match else None
            item = {
                "external_key": f"tuition_source_row:bmstu:page:table{table_no}:row{row_no}",
                "source_url": source_url,
                "table_number": table_no,
                "row_number": row_no,
                "direction_code": code,
                "cells": cells,
                "study_year_label": year_label,
                "table_category": table_category,
            }
            rows.append(item)
            if code and len(cells) >= 3 and row_no > 1:
                amount = _money(cells[-1])
                prices = [amount] if amount is not None else []
                records.append({
                    "external_key": f"tuition:bmstu:{code}:{_year_key([year_label] if year_label else [])}:table{table_no}:row{row_no}",
                    "direction_code": code,
                    "direction_name": cells[1] or None,
                    "study_year_label": year_label,
                    "study_level_or_table_category": table_category,
                    "amount_values": prices,
                    "annual_amount_rub": amount,
                    "currency": "RUB" if prices else None,
                    "raw_cells": cells,
                    "source_url": source_url,
                    "source_locator": {"table": table_no, "row": row_no},
                })
        if rows:
            tables.append({
                "external_key": f"tuition_source_table:bmstu:page:{table_no}",
                "source_url": source_url,
                "table_number": table_no,
                "study_year_label": year_label,
                "table_category": table_category,
                "rows": rows,
            })
    visible_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    return {
        "tuition_records": records,
        "raw_tables": tables,
        "page_facts": [{"source_url": source_url, "visible_text": visible_text}],
    }


def _money(value: str) -> int | None:
    normalized = value.replace("\xa0", " ")
    if not any(mark in normalized for mark in ("₽", "руб", "р.")) and not re.search(r"\d[\s\u202f]\d{3}(?:[\s\u202f]\d{3})?", normalized):
        return None
    digits = re.sub(r"\D", "", normalized)
    if 4 <= len(digits) <= 8:
        return int(digits)
    return None


def _year_key(labels: list[str]) -> str:
    if not labels:
        return "year-unspecified"
    match = re.search(r"(20\d{2})\s*[/–-]\s*(20\d{2})", labels[0])
    return f"{match.group(1)}-{match.group(2)}" if match else "year-unspecified"


__all__ = ["parse_cost_page"]
