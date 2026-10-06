from __future__ import annotations

from ....contracts.raw import RawUniversityRecord


def validate_university_record(record: RawUniversityRecord) -> RawUniversityRecord:
    """Keep university parsing typed without exposing HTML parser details."""

    return record
