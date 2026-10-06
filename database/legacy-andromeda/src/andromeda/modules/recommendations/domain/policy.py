"""Deterministic policy values used by recommendation scoring."""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel


RECOMMENDATION_POLICY_VERSION = "content-fit.v1"


class RecommendationWeights(ContractModel):
    """Weights for the explainable Content Fit components."""

    subject: Decimal = Field(default=Decimal("0.55"), strict=True, ge=0, le=1)
    activity: Decimal = Field(default=Decimal("0.25"), strict=True, ge=0, le=1)
    distinctive: Decimal = Field(default=Decimal("0.20"), strict=True, ge=0, le=1)
    anti_interest: Decimal = Field(default=Decimal("0.60"), strict=True, ge=0, le=1)


class RecommendationPolicy(ContractModel):
    """Bounded, versionable scoring policy for the recommendation use case."""

    weights: RecommendationWeights = Field(default_factory=RecommendationWeights)
    score_min: int = Field(default=0, strict=True, ge=0, le=100)
    score_max: int = Field(default=100, strict=True, ge=0, le=100)
    default_limit: int = Field(default=10, strict=True, ge=1, le=20)
    max_limit: int = Field(default=20, strict=True, ge=1, le=20)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.score_min > self.score_max:
            raise ValueError("score_min must not exceed score_max")
        if self.default_limit > self.max_limit:
            raise ValueError("default_limit must not exceed max_limit")
        return self


__all__ = ["RECOMMENDATION_POLICY_VERSION", "RecommendationPolicy", "RecommendationWeights"]
