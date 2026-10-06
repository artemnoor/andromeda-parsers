from __future__ import annotations

from collections.abc import Iterable, Sequence
from hashlib import sha256
import re

from andromeda.ingestion.contracts.raw import RawProgramRecord
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.errors import ContractError, ErrorCode


_DIRECTION_RE = re.compile(r"(?<!\d)(\d{2}\.\d{2}\.\d{2})(?!\d)")


def direction_codes(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_DIRECTION_RE.findall(value)))


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def normalize_name(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def source_identity_key(program: RawProgramRecord) -> str:
    return "|".join((str(program.source_url), normalize_name(program.name), program.direction_code))


def canonicalize_program_records(records: Iterable[RawProgramRecord]) -> tuple[RawProgramRecord, ...]:
    values = tuple(records)
    keys = [source_identity_key(value) for value in values]
    if len(keys) != len(set(keys)):
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "HSE catalog contains duplicate program identities")
    used: dict[str, set[str]] = {}
    assigned: dict[str, str] = {}
    for key, program in sorted(zip(keys, values), key=lambda item: item[0]):
        direction = direction_codes(program.direction_code)
        if len(direction) != 1:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"HSE program has invalid direction code: {program.direction_code}")
        direction_code = direction[0]
        digest = int(sha256(key.encode("utf-8")).hexdigest()[:12], 16)
        suffix = 100 + digest % 900
        candidate = f"{direction_code}-{suffix}"
        while candidate in used.setdefault(direction_code, set()):
            suffix = 100 + ((suffix - 99) % 900)
            candidate = f"{direction_code}-{suffix}"
        used[direction_code].add(candidate)
        assigned[key] = candidate
    return tuple(value.model_copy(update={"code": assigned[key], "source_code": value.source_code or str(value.source_url)}) for key, value in zip(keys, values))


def resolve_program(source_code: str | None, source_name: str | None, programs: Sequence[Program]) -> Program | None:
    if source_code:
        code_matches = tuple(program for program in programs if program.code == source_code)
        if len(code_matches) == 1:
            return code_matches[0]
    if not source_name:
        return None
    target = normalize_name(source_name)
    exact = tuple(program for program in programs if normalize_name(program.name) == target)
    if len(exact) == 1:
        return exact[0]
    candidates = tuple(program for program in programs if target in normalize_name(program.name) or normalize_name(program.name) in target)
    return candidates[0] if len(candidates) == 1 else None


__all__ = ["canonicalize_program_records", "direction_codes", "normalize_name", "normalize_text", "resolve_program"]
