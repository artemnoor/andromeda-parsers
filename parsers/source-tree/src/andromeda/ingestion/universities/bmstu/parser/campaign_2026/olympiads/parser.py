from __future__ import annotations

import hashlib
import re
from typing import Any

import pdfplumber

from ..common import clean_text, normalize_code


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip()


def _key_part(value: str) -> str:
    return hashlib.sha256(_text(value).casefold().encode("utf-8")).hexdigest()[:14]


def _number(value: str) -> str | None:
    match = re.fullmatch(r"\s*(\d{1,4})\s*", value)
    return match.group(1) if match else None


def _eligible_direction_codes(value: str) -> list[str]:
    return list(dict.fromkeys(normalize_code(match.group(0)) for match in re.finditer(r"\d{2}[.‐‑‒–—−]\d{2}[.‐‑‒–—−]\d{2}", value)))


def _benefit_status(value: str) -> str:
    normalized = _text(value).casefold()
    if "не предоставляется" in normalized or "не предоставлено" in normalized:
        return "not_provided"
    if "предоставляется" in normalized or "предоставлено" in normalized:
        return "provided"
    return "unspecified"


def parse_olympiad_appendix(
    body: bytes,
    *,
    appendix: str,
    source_url: str,
) -> dict[str, list[dict[str, Any]]]:
    """Parse every visible table row and emit olympiads, profiles, and benefit rows.

    The raw table-row output is deliberately retained alongside normalized entities;
    this lets a loader/reviewer verify rows where the source layout is ambiguous.
    """
    if appendix not in {"5.1", "5.2", "5.3", "5.4", "5.5"}:
        raise ValueError(f"unsupported olympiad appendix: {appendix}")
    raw_rows: list[dict[str, Any]] = []
    olympiads: dict[str, dict[str, Any]] = {}
    profiles: dict[str, dict[str, Any]] = {}
    benefits: list[dict[str, Any]] = []

    if appendix == "5.5":
        return _parse_international_appendix(body, source_url)

    with pdfplumber.open(__import__("io").BytesIO(body)) as pdf:
        current_number: str | None = None
        current_name = ""
        current_profile_key: str | None = None
        canonical_centers: list[float] | None = None
        pending_direction_scope: str | None = None
        current_direction_scope: str | None = None
        for page_no, page in enumerate(pdf.pages, start=1):
            for table_no, table in enumerate(page.find_tables(), start=1):
                extracted_table = table.extract()
                for row_no, row in enumerate(table.rows, start=1):
                    extracted_cells = [_text(cell) if cell else "" for cell in extracted_table[row_no - 1]]
                    if not any(extracted_cells):
                        continue
                    raw_row_text = " ".join(value for value in extracted_cells if value)
                    if appendix in {"5.1", "5.2", "5.3"}:
                        row_number = _number(extracted_cells[0]) if extracted_cells else None
                        title = extracted_cells[1] if len(extracted_cells) > 1 else ""
                        if canonical_centers is None and row_number and title:
                            canonical_centers = [(cell[0] + cell[2]) / 2 for cell in row.cells if cell is not None]
                        if canonical_centers:
                            cells = [""] * len(canonical_centers)
                            for cell_index, cell in enumerate(row.cells):
                                if cell is None or cell_index >= len(extracted_cells) or not extracted_cells[cell_index]:
                                    continue
                                center = (cell[0] + cell[2]) / 2
                                target = min(range(len(canonical_centers)), key=lambda idx: abs(canonical_centers[idx] - center))
                                cells[target] = " ".join(part for part in (cells[target], extracted_cells[cell_index]) if part)
                        else:
                            cells = extracted_cells
                    else:
                        cells = extracted_cells
                    raw_rows.append({
                        "external_key": f"olympiad_source_row:bmstu:2026:app{appendix}:p{page_no}:t{table_no}:r{row_no}",
                        "appendix": appendix,
                        "source_url": source_url,
                        "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                        "cells": cells,
                        "extracted_cells": extracted_cells,
                    })
                    if appendix in {"5.1", "5.2", "5.3"}:
                        if len(cells) < 3:
                            continue
                        row_number = _number(cells[0])
                        title = cells[1]
                        if raw_row_text.casefold().startswith("для направлений"):
                            pending_direction_scope = raw_row_text
                            continue
                        if row_number and title and "наименование олимпиады" not in title.casefold():
                            current_number, current_name = row_number, title
                            current_profile_key = None
                            current_direction_scope = pending_direction_scope
                            pending_direction_scope = None
                        elif title and not row_number and not current_name:
                            current_name = title
                        profile_name = cells[2]
                        if not current_name or not profile_name or "профиль олимпиады" in profile_name.casefold():
                            if current_profile_key and len(cells) > 3 and cells[3]:
                                profiles[current_profile_key].setdefault("source_row_continuations", []).append({
                                    "locator": {"page": page_no, "table": table_no, "row": row_no},
                                    "mapped_subjects_or_scope": cells[3],
                                })
                            continue
                        olympiad_key = _olympiad_key(current_number, current_name)
                        olympiads.setdefault(olympiad_key, {
                            "external_key": olympiad_key,
                            "official_name_in_mgtu_document": current_name,
                            "rsosh_list_number": current_number,
                            "organizer_name": None,
                            "organizer_official_url": None,
                            "organizer_details_status": "not_yet_verified",
                            "source_appendices": [],
                            "source_url": source_url,
                        })
                        if appendix not in olympiads[olympiad_key]["source_appendices"]:
                            olympiads[olympiad_key]["source_appendices"].append(appendix)
                        profile_key = f"olympiad_profile:bmstu:2026:rsosh:{_key_part(current_name)}:{_key_part(profile_name)}"
                        current_profile_key = profile_key
                        profile = profiles.setdefault(profile_key, {
                            "external_key": profile_key,
                            "olympiad_key": olympiad_key,
                            "name_in_mgtu_document": profile_name,
                            "organizer_profile_name": None,
                            "organizer_profile_details_status": "not_yet_verified",
                            "mapped_subjects_or_program_scope": None,
                            "mgtu_scope_texts": [],
                            "level": None,
                            "source_rows": [],
                            "source_url": source_url,
                        })
                        scope = cells[3] if len(cells) > 3 and cells[3] else None
                        level = cells[4] if len(cells) > 4 and cells[4] else None
                        confirm = cells[5] if len(cells) > 5 and cells[5] else None
                        record_source = {"appendix": appendix, "locator": {"page": page_no, "table": table_no, "row": row_no}}
                        profile["source_rows"].append(record_source)
                        if scope and scope not in profile["mgtu_scope_texts"]:
                            profile["mgtu_scope_texts"].append(scope)
                        if current_direction_scope and current_direction_scope not in profile["mgtu_scope_texts"]:
                            profile["mgtu_scope_texts"].append(current_direction_scope)
                        if level:
                            profile["level"] = level
                        profile["mapped_subjects_or_program_scope"] = scope or profile["mapped_subjects_or_program_scope"]
                        eligible = list(dict.fromkeys(_eligible_direction_codes(scope or "") + _eligible_direction_codes(current_direction_scope or "")))
                        applicability_text = "; ".join(item for item in (scope, current_direction_scope) if item) or None
                        result_columns = () if appendix == "5.2" else ((6, "winner"), (7, "prize_winner"))
                        for col_no, result_name in result_columns:
                            status = _benefit_status(cells[col_no]) if col_no < len(cells) else "unspecified"
                            benefit = "bvi" if appendix == "5.1" else "100_points"
                            benefit_key = f"olympiad_benefit:bmstu:2026:app{appendix}:p{page_no}:t{table_no}:r{row_no}:{result_name}"
                            if status != "unspecified":
                                benefits.append({
                                    "external_key": benefit_key,
                                    "olympiad_profile_key": profile_key,
                                    "result_type": result_name,
                                    "benefit_type": benefit,
                                    "benefit_status": status,
                                    "eligible_direction_codes": eligible,
                                    "applicability_text": applicability_text,
                                    "confirmation_exam_text": confirm,
                                    "confirmation_score": 75 if appendix in {"5.1", "5.2", "5.3"} and confirm else None,
                                    "is_branch_only": False,
                                    "source_appendix": appendix,
                                    "source_url": source_url,
                                    "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                                })
                                if appendix == "5.1" and status == "provided":
                                    benefits.append({
                                        "external_key": f"olympiad_benefit:bmstu:2026:app5.1:other-nps:p{page_no}:t{table_no}:r{row_no}:{result_name}",
                                        "olympiad_profile_key": profile_key,
                                        "result_type": result_name,
                                        "benefit_type": "100_points",
                                        "benefit_status": "conditional_on_bvi_on_listed_nps",
                                        "eligible_direction_codes": [],
                                        "applicability_text": "other NPS under paragraph 7 of Appendix 5; exact other NPS are not enumerated in the rule",
                                        "confirmation_exam_text": confirm,
                                        "confirmation_score": 75 if confirm else None,
                                        "is_branch_only": False,
                                        "requires_bvi_on_eligible_direction": True,
                                        "source_appendix": "5 + 5.1",
                                        "source_url": source_url,
                                        "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                                    })
                        if appendix == "5.2" and len(cells) > 6 and cells[6]:
                            # 5.2 is explicitly limited to the Kaluga and Mytishchi branches.
                            status = "not_provided" if "не предоставляется" in cells[6].casefold() else "provided"
                            if status != "unspecified":
                                benefits.append({
                                    "external_key": f"olympiad_benefit:bmstu:2026:app5.2:p{page_no}:t{table_no}:r{row_no}:branch",
                                    "olympiad_profile_key": profile_key,
                                    "result_type": "winner_or_prize_winner_as_stated_in_appendix",
                                    "benefit_type": "bvi",
                                    "benefit_status": status,
                                    "eligible_direction_codes": eligible,
                                    "applicability_text": cells[6],
                                    "confirmation_exam_text": confirm,
                                    "confirmation_score": 75 if confirm and re.search(r"75\s*бал", confirm, re.I) else None,
                                    "is_branch_only": True,
                                    "source_appendix": appendix,
                                    "source_url": source_url,
                                    "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                                })
                    else:
                        _parse_special_appendix_row(
                            appendix, cells, source_url, page_no, table_no, row_no,
                            olympiads, profiles, benefits,
                        )

    return {
        "olympiads": list(olympiads.values()),
        "profiles": list(profiles.values()),
        "benefits": benefits,
        "source_rows": raw_rows,
    }


def _olympiad_key(number: str | None, name: str) -> str:
    number_piece = f"rsosh-{number}" if number else "unregistered"
    return f"olympiad:bmstu:2026:{number_piece}:{_key_part(name)}"


def _parse_special_appendix_row(
    appendix: str,
    cells: list[str],
    source_url: str,
    page_no: int,
    table_no: int,
    row_no: int,
    olympiads: dict[str, dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
    benefits: list[dict[str, Any]],
) -> None:
    if appendix == "5.4":
        if len(cells) < 2 or not cells[0] or "профиль вош" in cells[0].casefold():
            return
        olympiad_name = "Всероссийская олимпиада школьников"
        profile_name = cells[0]
        exam = cells[1]
        result_text = "особое преимущество посредством приравнивания к лицам, имеющим 100 баллов"
        benefit = "100_points"
        list_no = None
        eligible_text = re.search(r"\(([^)]*\d{2}\.\d{2}\.\d{2}[^)]*)\)", exam)
        scope = eligible_text.group(1) if eligible_text else None
    else:
        # Appendix 5.5 is printed as two small tables; some extracted rows split names vertically.
        if len(cells) < 2 or not any(cells):
            return
        label = " ".join(v for v in cells if v)
        if "профиль международной" in label.casefold() or "соответствие направлений" in label.casefold():
            return
        profile_name = " ".join(cells[:2]).strip()
        exam = cells[-1]
        if not profile_name or not exam or profile_name == exam:
            return
        olympiad_name = profile_name
        result_text = "Appendix 5.5; eligibility and NPS scope as stated in its two tables"
        benefit = "100_points"
        list_no = None
        scope = None

    olympiad_key = _olympiad_key(list_no, olympiad_name)
    olympiads.setdefault(olympiad_key, {
        "external_key": olympiad_key,
        "official_name_in_mgtu_document": olympiad_name,
        "rsosh_list_number": list_no,
        "organizer_name": None,
        "organizer_official_url": None,
        "organizer_details_status": "not_yet_verified",
        "source_appendices": [],
        "source_url": source_url,
    })
    if appendix not in olympiads[olympiad_key]["source_appendices"]:
        olympiads[olympiad_key]["source_appendices"].append(appendix)
    profile_key = f"olympiad_profile:bmstu:2026:special:{_key_part(olympiad_name)}:{_key_part(profile_name)}"
    profiles.setdefault(profile_key, {
        "external_key": profile_key,
        "olympiad_key": olympiad_key,
        "name_in_mgtu_document": profile_name,
        "organizer_profile_name": None,
        "organizer_profile_details_status": "not_yet_verified",
        "mapped_subjects_or_program_scope": scope,
        "level": None,
        "source_rows": [],
        "source_url": source_url,
    })["source_rows"].append({"appendix": appendix, "locator": {"page": page_no, "table": table_no, "row": row_no}})
    benefit_key = f"olympiad_benefit:bmstu:2026:app{appendix}:{_key_part(profile_name)}:{_key_part(exam)}"
    if any(item["external_key"] == benefit_key for item in benefits):
        return
    benefits.append({
        "external_key": benefit_key,
        "olympiad_profile_key": profile_key,
        "result_type": "as_defined_by_rules_2026",
        "benefit_type": benefit,
        "benefit_status": "eligibility_mapping_only",
        "eligible_direction_codes": _eligible_direction_codes(scope or ""),
        "applicability_text": result_text,
        "confirmation_exam_text": exam,
        "confirmation_score": None,
        "is_branch_only": False,
        "source_appendix": appendix,
        "source_url": source_url,
        "source_locator": {"page": page_no, "table": table_no, "row": row_no},
    })


def _parse_international_appendix(body: bytes, source_url: str) -> dict[str, list[dict[str, Any]]]:
    """Read the two official 5.5 crosswalks and join them by full profile name."""
    import io

    parent = "Международные олимпиады школьников"
    olympiad_key = _olympiad_key(None, parent)
    olympiad = {
        "external_key": olympiad_key,
        "official_name_in_mgtu_document": parent,
        "rsosh_list_number": None,
        "organizer_name": None,
        "organizer_official_url": None,
        "organizer_details_status": "not_yet_verified",
        "source_appendices": ["5.5"],
        "source_url": source_url,
    }
    raw_rows: list[dict[str, Any]] = []
    exam_mappings: dict[str, dict[str, Any]] = {}
    bvi_mappings: dict[str, dict[str, Any]] = {}
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table_no, table in enumerate(page.find_tables(), start=1):
                extracted = table.extract()
                for row_no, values in enumerate(extracted, start=1):
                    cells = [_text(value) if value else "" for value in values]
                    if not any(cells):
                        continue
                    raw_rows.append({
                        "external_key": f"olympiad_source_row:bmstu:2026:app5.5:p{page_no}:t{table_no}:r{row_no}",
                        "appendix": "5.5",
                        "source_url": source_url,
                        "source_locator": {"page": page_no, "table": table_no, "row": row_no},
                        "cells": cells,
                    })

                is_exam_table = page_no == 1 and table_no == 1
                is_bvi_table = (page_no == 1 and table_no == 3) or (page_no > 1 and table_no == 1)
                if not is_exam_table and not is_bvi_table:
                    continue
                if is_exam_table:
                    fragments: list[str] = []
                    current_exam: str | None = None
                    current_locator: dict[str, int] | None = None
                    for row_no, values in enumerate(extracted, start=1):
                        cells = [_text(value) if value else "" for value in values]
                        if not any(cells) or any("профиль международной" in cell.casefold() for cell in cells):
                            continue
                        profile_fragment = " ".join(value for value in cells[:2] if value).strip()
                        exam = cells[2] if len(cells) > 2 else ""
                        if exam:
                            if current_exam is not None and fragments:
                                _add_exam_mapping(exam_mappings, " ".join(fragments), current_exam, current_locator or {})
                            fragments = [profile_fragment] if profile_fragment else []
                            current_exam = exam
                            current_locator = {"page": page_no, "table": table_no, "row": row_no}
                        elif profile_fragment and current_exam is not None:
                            fragments.append(profile_fragment)
                    if current_exam is not None and fragments:
                        _add_exam_mapping(exam_mappings, " ".join(fragments), current_exam, current_locator or {})
                else:
                    for row_no, values in enumerate(extracted, start=1):
                        cells = [_text(value) if value else "" for value in values]
                        if len(cells) < 2 or not cells[0] or not cells[1]:
                            continue
                        if "профиль международной" in cells[0].casefold() or "нпс для предоставления" in " ".join(cells).casefold():
                            continue
                        profile_name = cells[0]
                        scope = " ".join(cells[1:]).strip()
                        key_norm = _norm(profile_name)
                        bvi_mappings[key_norm] = {
                            "name": profile_name,
                            "scope": scope,
                            "locator": {"page": page_no, "table": table_no, "row": row_no},
                        }

    profile_names = {**{key: value["name"] for key, value in exam_mappings.items()}, **{key: value["name"] for key, value in bvi_mappings.items()}}
    profiles: list[dict[str, Any]] = []
    benefits: list[dict[str, Any]] = []
    for normalized_name, profile_name in profile_names.items():
        profile_key = f"olympiad_profile:bmstu:2026:special:{_key_part(olympiad_key)}:{_key_part(profile_name)}"
        exam = exam_mappings.get(normalized_name)
        bvi = bvi_mappings.get(normalized_name)
        profile = {
            "external_key": profile_key,
            "olympiad_key": olympiad_key,
            "name_in_mgtu_document": profile_name,
            "organizer_profile_name": None,
            "organizer_profile_details_status": "not_yet_verified",
            "mapped_subjects_or_program_scope": bvi["scope"] if bvi else None,
            "mgtu_scope_texts": [bvi["scope"]] if bvi else [],
            "level": None,
            "source_rows": [],
            "source_url": source_url,
        }
        if exam:
            profile["source_rows"].append({"appendix": "5.5", "locator": exam["locator"]})
            benefits.append({
                "external_key": f"olympiad_benefit:bmstu:2026:app5.5:100:{_key_part(profile_name)}",
                "olympiad_profile_key": profile_key,
                "result_type": "as_defined_by_rules_2026",
                "benefit_type": "100_points",
                "benefit_status": "eligibility_mapping_only",
                "eligible_direction_codes": [],
                "applicability_text": "Appendix 5.5 table title: 100-point examination equivalency",
                "confirmation_exam_text": exam["exam"],
                "confirmation_score": None,
                "is_branch_only": False,
                "source_appendix": "5.5",
                "source_url": source_url,
                "source_locator": exam["locator"],
            })
        if bvi:
            profile["source_rows"].append({"appendix": "5.5", "locator": bvi["locator"]})
            benefits.append({
                "external_key": f"olympiad_benefit:bmstu:2026:app5.5:bvi:{_key_part(profile_name)}",
                "olympiad_profile_key": profile_key,
                "result_type": "as_defined_by_rules_2026",
                "benefit_type": "bvi",
                "benefit_status": "eligibility_mapping_only",
                "eligible_direction_codes": _eligible_direction_codes(bvi["scope"]),
                "applicability_text": bvi["scope"],
                "confirmation_exam_text": exam["exam"] if exam else None,
                "confirmation_score": None,
                "is_branch_only": False,
                "source_appendix": "5.5",
                "source_url": source_url,
                "source_locator": bvi["locator"],
            })
        profiles.append(profile)
    return {"olympiads": [olympiad], "profiles": profiles, "benefits": benefits, "source_rows": raw_rows}


def _add_exam_mapping(target: dict[str, dict[str, Any]], profile_name: str, exam: str, locator: dict[str, int]) -> None:
    name = _text(profile_name)
    if not name:
        return
    target[_norm(name)] = {"name": name, "exam": _text(exam), "locator": locator}


def _norm(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", _text(value).casefold())


__all__ = ["parse_olympiad_appendix"]
