"""Pure domain entities for applicant admission data."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import NonEmptyText

from .subject_identity import normalize_subject_name


ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")


class ApplicantSubjectScore(ContractModel):
    """One applicant score; the original subject spelling is intentionally kept."""

    subject: NonEmptyText
    score: Decimal = Field(strict=True, ge=ZERO, le=ONE_HUNDRED, max_digits=5, decimal_places=2)


class ApplicantAdmissionProfile(ContractModel):
    """Subject scores used only by Admission Fit, not by Content Fit."""

    version: Literal[1] = 1
    scores: tuple[ApplicantSubjectScore, ...] = ()

    @model_validator(mode="after")
    def validate_unique_subjects(self) -> Self:
        normalized = tuple(normalize_subject_name(item.subject) for item in self.scores)
        if len(normalized) != len(set(normalized)):
            raise ValueError("applicant subject scores must be unique after normalization")
        return self


__all__ = ["ApplicantAdmissionProfile", "ApplicantSubjectScore"]
