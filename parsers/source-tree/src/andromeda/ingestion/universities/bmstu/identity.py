"""Deterministic resolution of BMSTU source identities to public programs."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
import re
from typing import Iterable

from andromeda.ingestion.contracts.raw import RawProgramRecord
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.errors import ContractError, ErrorCode

from .mappings.admissions import normalize_code


_DIRECTION_RE = re.compile(r"\d{2}\.\d{2}\.\d{2}")
_EXPLICIT_PROFILE_RE = re.compile(r"(?P<direction>\d{2}\.\d{2}\.\d{2})[-/]?(?P<suffix>\d{2,3})(?:\s|\(|$)")


def source_identity_key(source_code: str, name: str, study_plan_url: str) -> str:
    return "|".join((normalize_source_code(source_code), normalize_text(name), study_plan_url.strip()))


def normalize_source_code(value: str) -> str:
    return " ".join(value.replace("–", "-").replace("—", "-").split())


def direction_codes(value: str) -> tuple[str, ...]:
    result: list[str] = []
    for match in _DIRECTION_RE.findall(value):
        if match not in result:
            result.append(match)
    return tuple(result)


def canonicalize_program_records(records: Iterable[RawProgramRecord]) -> tuple[RawProgramRecord, ...]:
    """Assign stable canonical profile codes while preserving source codes."""

    values = tuple(records)
    source_keys = [
        source_identity_key(program.source_code or program.code, program.name, str(program.study_plan_url))
        for program in values
    ]
    if len(source_keys) != len(set(source_keys)):
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU detail contains duplicate profile source identities")

    assigned: dict[str, set[str]] = {}
    canonical_by_key: dict[str, str] = {}
    sorted_values = sorted(zip(source_keys, values), key=lambda pair: pair[0])
    for key, program in sorted_values:
        source_code = normalize_source_code(program.source_code or program.code)
        matches = _EXPLICIT_PROFILE_RE.search(source_code)
        source_directions = direction_codes(program.direction_code) or direction_codes(source_code)
        if not source_directions:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Profile has no direction code: {source_code}")
        direction = source_directions[0]
        candidate = f"{direction}-{matches.group('suffix')}" if matches and matches.group("direction") == direction else None
        if candidate is None or candidate in canonical_by_key.values():
            digest = int(sha256(key.encode("utf-8")).hexdigest()[:12], 16)
            suffix = 100 + digest % 900
            candidate = f"{direction}-{suffix}"
            while candidate in assigned.setdefault(direction, set()):
                suffix = 100 + ((suffix - 99) % 900)
                candidate = f"{direction}-{suffix}"
        assigned.setdefault(direction, set()).add(candidate)
        canonical_by_key[key] = candidate

    return tuple(
        program.model_copy(update={"code": canonical_by_key[key], "source_code": program.source_code or program.code})
        for key, program in zip(source_keys, values)
    )


def map_source_program_code(
    source_code: str,
    source_name: str | None,
    programs: Iterable[RawProgramRecord],
) -> str:
    """Map an official BMSTU source identity to a canonical raw program code."""

    values = tuple(programs)
    normalized = normalize_source_code(source_code)
    named = tuple(
        program
        for program in values
        if normalize_source_code(program.source_code or program.code) == normalized
        and (source_name is None or normalize_text(program.name) == normalize_text(source_name))
    )
    if len(named) == 1:
        return named[0].code
    if len(named) > 1:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Ambiguous BMSTU source profile identity: {source_code}")
    directions = direction_codes(normalized)
    return directions[0] if directions else normalized.replace("/", "-").replace(" ", "")


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def resolve_programs(
    source_code: str,
    *,
    source_name: str | None,
    scope: str,
    programs: Sequence[Program],
) -> tuple[Program, ...]:
    """Resolve exact profile or explicit direction-level source identities.

    Direction-level source facts may be projected to every profile under that
    direction, but only when the source explicitly declares that scope. A
    program-level row with several possible names is rejected rather than
    guessed.
    """
    code = normalize_code(source_code)
    exact = tuple(program for program in programs if normalize_code(program.code) == code)
    if exact:
        return exact

    direction_matches = tuple(
        program for program in programs if normalize_code(program.code).startswith(f"{code}-")
    )
    if scope == "direction" and direction_matches:
        return direction_matches

    if scope == "program" and source_name:
        name = _normalize_name(source_name)
        named = tuple(program for program in direction_matches if _normalize_name(program.name) == name)
        if len(named) == 1:
            return named

    reason = "unknown program identity" if not direction_matches else "ambiguous program identity"
    raise ContractError(
        ErrorCode.SOURCE_CONTRACT_ERROR,
        f"BMSTU admission row has {reason}: {code}",
    )


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


__all__ = [
    "canonicalize_program_records",
    "direction_codes",
    "map_source_program_code",
    "normalize_source_code",
    "normalize_text",
    "resolve_programs",
    "source_identity_key",
]
