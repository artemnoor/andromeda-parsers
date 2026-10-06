"""Questionnaire-level domain contract."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel

from .entities import Question


class Questionnaire(ContractModel):
    version: Literal[1] = 1
    question_set_version: str = "proftest-v2"
    questions: tuple[Question, ...] = Field(min_length=1)

    @classmethod
    def from_questions(cls, questions: tuple[Question, ...], *, question_set_version: str = "proftest-v2") -> "Questionnaire":
        if not question_set_version.strip():
            raise ValueError("question_set_version must not be empty")
        return cls(questions=questions, question_set_version=question_set_version)


__all__ = ["Questionnaire"]
