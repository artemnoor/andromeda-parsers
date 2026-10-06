"""Parsers for official BMSTU undergraduate admission documents."""

from .parser import (
    parse_achievements_pdf,
    parse_exam_requirements_pdf,
    parse_intake_plan_pdf,
    parse_targeted_quota_pdf,
)
from .authority import build_authoritative_intake_records

__all__ = [
    "parse_achievements_pdf",
    "parse_exam_requirements_pdf",
    "parse_intake_plan_pdf",
    "parse_targeted_quota_pdf",
    "build_authoritative_intake_records",
]
