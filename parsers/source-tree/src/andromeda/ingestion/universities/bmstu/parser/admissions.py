"""BMSTU detail-page admission parser.

The parser knows only the BMSTU ``__NEXT_DATA__`` shape. It emits raw typed
records; canonical identity and source provenance are resolved one layer up.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from bs4 import BeautifulSoup

from ....contracts.raw import (
    RawAdmissionExamRequirement,
    RawAdmissionPassingScore,
    RawAdmissionQuota,
    RawAdmissionRecord,
    RawAdmissionTuition,
    RawSourceSnapshot,
    SourceLocator,
)
from ..normalizers.codes import normalize_code


logger = logging.getLogger("andromeda.ingestion.bmstu.parser.admissions")


def parse_detail_admissions(snapshot: RawSourceSnapshot, program_codes: Sequence[str] | None = None) -> tuple[RawAdmissionRecord, ...]:
    root = _read_next_data(snapshot.body)
    data = _detail_data(root)
    additional = _object(data, "additional")
    direction_code = _text(additional.get("code"))
    if not direction_code:
        raise ValueError("BMSTU detail admission payload has no direction code")

    profiles = _profiles(data)
    selected = tuple(normalize_code(code) for code in program_codes) if program_codes is not None else tuple(normalize_code(code) for code, _ in profiles if code)
    profile_by_code = {normalize_code(code): name for code, name in profiles if code}
    missing = tuple(code for code in selected if code not in profile_by_code)
    if missing:
        raise ValueError(f"BMSTU detail admission payload misses selected programs: {missing}")

    year = _current_year(data, snapshot)
    points = _exam_requirements(data)
    prices = _tuition(data)
    form = next((item.study_form for item in prices if item.study_form), None)
    places = _places(data)
    quotas = _quotas(data)
    records: list[RawAdmissionRecord] = []

    for code in selected:
        program_name = profile_by_code[code]
        current_fundings = tuple(dict.fromkeys((*places.keys(), FundingFallback.PAID if prices else None)))
        current_fundings = tuple(value for value in current_fundings if value is not None)
        if not current_fundings and (points or quotas or prices):
            current_fundings = (None,)
        for funding in current_fundings:
            records.append(
                _record(
                    snapshot,
                    code=code,
                    program_name=program_name,
                    year=year,
                    study_form=form,
                    funding_type=funding,
                    places=places.get(funding) if funding is not None else None,
                    exams=points,
                    quotas=quotas if funding in ("budget", None) else (),
                    tuition=prices if funding == FundingFallback.PAID else (),
                    field="detail.admission",
                )
            )

        old_points = _object(additional, "oldPoints")
        for raw_year, values in old_points.items():
            if not str(raw_year).isdigit() or not isinstance(values, Mapping):
                continue
            for score_type in ("budget", "paid", "average"):
                score = _number(values.get(score_type))
                if score is None:
                    continue
                records.append(
                    _record(
                        snapshot,
                        code=code,
                        program_name=program_name,
                        year=int(raw_year),
                        study_form=None,
                        funding_type=score_type if score_type in {"budget", "paid"} else None,
                        passing_scores=(RawAdmissionPassingScore(score_type=score_type, score=score),),
                        field=f"detail.additional.oldPoints.{raw_year}.{score_type}",
                    )
                )

    logger.info(
        "bmstu_detail_admissions_parsed programs=%d records=%d exams=%d prices=%d quotas=%d",
        len(selected),
        len(records),
        len(points),
        len(prices),
        len(quotas),
    )
    return tuple(records)


class FundingFallback:
    PAID = "paid"


def _record(
    snapshot: RawSourceSnapshot,
    *,
    code: str,
    program_name: str,
    year: int,
    study_form: str | None = None,
    funding_type: str | None = None,
    places: int | None = None,
    exams: tuple[RawAdmissionExamRequirement, ...] = (),
    quotas: tuple[RawAdmissionQuota, ...] = (),
    passing_scores: tuple[RawAdmissionPassingScore, ...] = (),
    tuition: tuple[RawAdmissionTuition, ...] = (),
    field: str,
) -> RawAdmissionRecord:
    stable = ":".join((code, str(year), funding_type or "unknown", field))
    return RawAdmissionRecord(
        id=f"bmstu-admission:{sha256(stable.encode('utf-8')).hexdigest()[:24]}",
        program_code=code,
        program_name=program_name,
        admission_year=year,
        study_form=study_form,
        funding_type=funding_type,
        scope="direction",
        places=places,
        exams=exams,
        quotas=quotas,
        passing_scores=passing_scores,
        tuition=tuition,
        source_kind="bmstu_major_detail",
        source_url=snapshot.requested_url,
        locator=SourceLocator(source_url=snapshot.requested_url, field=field),
    )


def _exam_requirements(data: Mapping[str, object]) -> tuple[RawAdmissionExamRequirement, ...]:
    result: list[RawAdmissionExamRequirement] = []
    for value in _list(data.get("points")):
        item = _object_value(value)
        title = _text(item.get("title"))
        score = _number(item.get("point"))
        if not title or score is None:
            continue
        result.append(
            RawAdmissionExamRequirement(
                subject=title,
                source_name=title,
                minimum_score=score,
                is_choice=bool(item.get("isChoice")),
            )
        )
    return tuple(result)


def _places(data: Mapping[str, object]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in _list(data.get("places")):
        item = _object_value(value)
        title = (_text(item.get("title")) or "").casefold()
        count = _integer(item.get("count"))
        if count is None:
            continue
        if "бюдж" in title:
            result["budget"] = count
        elif "плат" in title:
            result["paid"] = count
    return result


def _quotas(data: Mapping[str, object]) -> tuple[RawAdmissionQuota, ...]:
    values = data.get("quotas")
    if values is None:
        values = _object(data, "additional").get("quotas")
    result: list[RawAdmissionQuota] = []
    for value in _list(values):
        item = _object_value(value)
        title = _text(item.get("title")) or _text(item.get("name"))
        count = _integer(item.get("count")) or _integer(item.get("places"))
        if title and count is not None:
            result.append(RawAdmissionQuota(quota_type=title, source_name=title, places=count))
    return tuple(result)


def _tuition(data: Mapping[str, object]) -> tuple[RawAdmissionTuition, ...]:
    result: list[RawAdmissionTuition] = []
    for value in _list(data.get("price")):
        item = _object_value(value)
        form = _text(item.get("studyForm"))
        academic_year = _text(item.get("academicYear"))
        period = _text(item.get("term"))
        for key, discounted in (("value", False), ("discountValue", True)):
            amount = _number(item.get(key))
            if amount is None:
                continue
            if not academic_year:
                logger.warning("[FIX:admission-year] tuition_year_missing; preserving source gap")
            result.append(
                RawAdmissionTuition(
                    amount=amount,
                    currency=_currency(_text(item.get("currency"))),
                    academic_year=academic_year or None,
                    period=period,
                    study_form=form,
                    is_discounted=discounted,
                )
            )
    return tuple(result)


def _profiles(data: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    chairs = _object(data, "chairs")
    for chair_value in _list(chairs.get("items")):
        chair = _object_value(chair_value)
        educational = _object(chair, "educationalProgram")
        for profile_value in _list(educational.get("items")):
            profile = _object_value(profile_value)
            code = _text(profile.get("code"))
            name = _text(profile.get("name"))
            if code and name:
                result.append((code, name))
    return tuple(result)


def _current_year(data: Mapping[str, object], snapshot: RawSourceSnapshot) -> int:
    description = _text(data.get("description")) or ""
    match = re.search(r"20\d{2}", description)
    return int(match.group(0)) if match else snapshot.captured_at.year


def _read_next_data(body: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(body.decode("utf-8-sig"))
        if isinstance(value, Mapping):
            return value
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    soup = BeautifulSoup(body, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise ValueError("BMSTU detail page has no __NEXT_DATA__")
    value = json.loads(script.string)
    if not isinstance(value, Mapping):
        raise ValueError("BMSTU detail __NEXT_DATA__ is not an object")
    return value


def _detail_data(root: Mapping[str, object]) -> dict[str, object]:
    if _object(root, "additional") or _object(root, "chairs"):
        return dict(root)
    direct = _object(root, "data")
    if _object(direct, "additional") or _object(direct, "chairs"):
        return direct
    return _object(_object(_object(_object(root, "props"), "initialState"), "bachelorMajorsDetails"), "data")


def _object(value: Mapping[str, object], key: str) -> dict[str, object]:
    candidate = value.get(key)
    return dict(candidate) if isinstance(candidate, Mapping) else {}


def _object_value(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _number(value: object) -> Decimal | None:
    text = _text(value)
    if text is None and isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        text = str(value)
    if text is None:
        return None
    cleaned = text.replace("\xa0", " ").replace(" ", "").replace(",", ".")
    if cleaned in {"", "—", "-"}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number == int(number) else None


def _currency(value: str | None) -> str:
    return "RUB" if value in {"₽", "руб", "руб.", "р"} else (value or "RUB").upper()


__all__ = ["parse_detail_admissions"]
