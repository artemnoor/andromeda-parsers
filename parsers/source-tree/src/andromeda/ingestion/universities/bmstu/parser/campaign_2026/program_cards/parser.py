from __future__ import annotations

from html import unescape
import json
from typing import Any

from bs4 import BeautifulSoup

from ..common import clean_text, normalize_code
from ..catalog.parser import is_head_campus


def _plain_html(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return clean_text(BeautifulSoup(unescape(value), "html.parser").get_text(" ", strip=True)) or None


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_program_card(body: bytes, expected_direction_code: str, source_url: str) -> dict[str, Any]:
    try:
        root = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"BMSTU card response is not valid JSON: {source_url}") from exc
    if not isinstance(root, dict):
        raise ValueError(f"BMSTU direction card is not an object: {source_url}")
    additional = _object(root.get("additional"))
    direction_code = normalize_code(additional.get("code"))
    direction_name = clean_text(additional.get("name"))
    if direction_code != expected_direction_code or not direction_name:
        raise ValueError(f"BMSTU card identity disagrees with catalog row: {source_url}")

    departments: list[dict[str, Any]] = []
    programs: list[dict[str, Any]] = []
    seen_department: set[str] = set()
    program_code_positions: dict[str, list[dict[str, Any]]] = {}
    for chair_index, chair in enumerate(_list(_object(root.get("chairs")).get("items")), start=1):
        if not isinstance(chair, dict):
            continue
        department_code = clean_text(chair.get("code"))
        department_name = _plain_html(chair.get("title"))
        if not department_code or not department_name:
            continue
        address = _plain_html(chair.get("address"))
        campus = is_head_campus(address)
        department_key = f"department:bmstu:{department_code}"
        if department_code not in seen_department:
            departments.append({
                "external_key": department_key,
                "code": department_code,
                "name": department_name,
                "faculty_name": _plain_html(_object(chair.get("faculty")).get("title")),
                "description": _plain_html(chair.get("description")),
                "address": address,
                "campus_scope": "head_moscow" if campus is True else "out_of_scope" if campus is False else "unverified",
                "source_url": source_url,
            })
            seen_department.add(department_code)
        programs_node = _object(chair.get("educationalProgram"))
        for profile_index, profile in enumerate(_list(programs_node.get("items")), start=1):
            if not isinstance(profile, dict):
                continue
            source_code = clean_text(profile.get("code"))
            code = normalize_code(source_code)
            name = _plain_html(profile.get("name"))
            if not code or not name:
                continue
            position = {"department_code": department_code, "card_position": [chair_index, profile_index]}
            program_code_positions.setdefault(code, []).append(position)
            disciplines = [
                _plain_html(item) for item in _list(profile.get("discipline"))
            ]
            programs.append({
                # BMSTU's catalog API can repeat a direction code in the profile
                # field. Combine official direction/profile/chair codes with the
                # stable source position so distinct official rows are retained.
                "external_key": f"program:bmstu:{direction_code}:{department_code}:{code}:source:{chair_index}-{profile_index}",
                "code": code,
                "source_code": source_code,
                "name": name,
                "direction_code": direction_code,
                "direction_key": f"direction:bmstu:{direction_code}",
                "department_key": department_key,
                "department_code": department_code,
                "source_card_position": [chair_index, profile_index],
                "description": _plain_html(profile.get("description")),
                "study_plan_url": clean_text(profile.get("plan")) or None,
                "catalog_course_names": [item for item in disciplines if item],
                "campus_scope": "head_moscow" if campus is True else "out_of_scope" if campus is False else "unverified",
                "source_url": source_url,
            })

    description = _plain_html(root.get("description"))
    courses_node = _object(root.get("courses"))
    direction_summary = {
        "external_key": f"direction:bmstu:{direction_code}",
        "code": direction_code,
        "name": direction_name,
        "degree_label_catalog": None,
        "qualification_label": clean_text(additional.get("qualification")) or None,
        "duration_label_catalog": clean_text(additional.get("studyPeriod")) or None,
        "duration_months": None,
        "description": description,
        "catalog_course_names": [
            _plain_html(item) for item in _list(_object(courses_node).get("items")) if _plain_html(item)
        ],
        "source_url": source_url,
    }
    return {
        "direction": direction_summary,
        "departments": departments,
        "programs": programs,
        "duplicate_profile_code_groups": [
            {"code": code, "source_rows": positions}
            for code, positions in program_code_positions.items()
            if len(positions) > 1
        ],
        "campus_scope": "head_moscow" if any(item["campus_scope"] == "head_moscow" for item in departments) else "unverified",
        "raw_price_ignored": bool(root.get("price")),
        "raw_places_ignored": bool(root.get("places")),
        "raw_old_points_ignored": bool(additional.get("oldPoints") or _object(root.get("oldPoints"))),
    }
