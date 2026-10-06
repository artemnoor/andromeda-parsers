from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import logging
from typing import Self

from pydantic import Field, model_validator

from ....shared.contracts.base import ContractModel
from ....shared.contracts.ids import DisciplineId, ShortText
from .areas import DisciplineAreaCode, DisciplineAreaWeight, area_position, default_area_weights


logger = logging.getLogger("andromeda.contracts.validation")


class Discipline(ContractModel):
    id: DisciplineId
    name: str = Field(min_length=1, max_length=256)
    normalized_name: ShortText
    area_weights: tuple[DisciplineAreaWeight, ...] = Field(default_factory=default_area_weights, min_length=1)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = sha256(self.normalized_name.encode("utf-8")).hexdigest()[:16]
        if self.id != f"discipline:{expected}":
            logger.error("contract_semantic_violation model=Discipline field=id")
            raise ValueError("discipline id must derive from normalized_name")
        areas = tuple(weight.area for weight in self.area_weights)
        if len(areas) != len(set(areas)):
            logger.error("contract_semantic_violation model=Discipline field=area_weights")
            raise ValueError("discipline area weights must not contain duplicate areas")
        if sum((weight.weight for weight in self.area_weights), Decimal("0")) != Decimal("1"):
            logger.error("contract_semantic_violation model=Discipline field=area_weights")
            raise ValueError("discipline area weights must sum to one")
        return self

    @property
    def primary_area(self) -> DisciplineAreaCode:
        return max(self.area_weights, key=lambda value: (value.weight, -area_position(value.area))).area


__all__ = ["Discipline"]
