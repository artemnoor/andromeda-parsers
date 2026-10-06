from __future__ import annotations

from pathlib import Path

DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "tracer" / "raw"
DEFAULT_EVENT_FIXTURE_DIR = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "events" / "raw"
DEFAULT_CAMPUS_FIXTURE_DIR = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "campus" / "raw"


def select_program_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    selected = values
    result = tuple(value.strip().removeprefix("program:") for value in selected)
    if not result or len(result) != len(set(result)) or any(not value for value in result):
        raise ValueError("program codes must be non-empty and unique")
    return result
