"""Transparent mapping from canonical subject areas to activity signals."""

from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode

from .entities import ActivityCode


def _weights(**values: str) -> dict[ActivityCode, Decimal]:
    parsed = {ActivityCode(key): Decimal(value) for key, value in values.items()}
    if sum(parsed.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("activity mapping must sum to one")
    return parsed


ACTIVITY_SIGNAL_WEIGHTS: dict[DisciplineAreaCode, dict[ActivityCode, Decimal]] = {
    DisciplineAreaCode.MATHEMATICS_STATISTICS: _weights(analytical="0.50", research="0.20", data="0.25", system_design="0.05"),
    DisciplineAreaCode.COMPUTER_SCIENCE_DATA: _weights(software_creation="0.35", system_design="0.25", analytical="0.15", data="0.25"),
    DisciplineAreaCode.PHYSICS_ASTRONOMY: _weights(analytical="0.25", research="0.20", physical_engineering="0.45", system_design="0.10"),
    DisciplineAreaCode.CHEMISTRY_MATERIALS: _weights(research="0.35", analytical="0.25", physical_engineering="0.30", system_design="0.10"),
    DisciplineAreaCode.BIOLOGY_BIOTECHNOLOGY: _weights(research="0.35", analytical="0.20", data="0.25", communication="0.10", creative="0.10"),
    DisciplineAreaCode.EARTH_ENVIRONMENT: _weights(research="0.25", analytical="0.20", physical_engineering="0.25", data="0.15", communication="0.10", system_design="0.05"),
    DisciplineAreaCode.ENGINEERING_TECHNOLOGY: _weights(physical_engineering="0.40", system_design="0.25", analytical="0.15", research="0.10", creative="0.05", software_creation="0.05"),
    DisciplineAreaCode.ARCHITECTURE_CONSTRUCTION: _weights(system_design="0.25", creative="0.35", physical_engineering="0.15", communication="0.10", analytical="0.10", research="0.05"),
    DisciplineAreaCode.AGRICULTURE_VETERINARY: _weights(research="0.25", physical_engineering="0.20", analytical="0.15", communication="0.15", creative="0.10", business="0.15"),
    DisciplineAreaCode.MEDICINE_HEALTH: _weights(research="0.25", analytical="0.25", communication="0.30", physical_engineering="0.10", data="0.10"),
    DisciplineAreaCode.PSYCHOLOGY_COGNITIVE: _weights(research="0.30", analytical="0.25", communication="0.30", data="0.10", creative="0.05"),
    DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES: _weights(research="0.20", analytical="0.20", communication="0.40", data="0.10", business="0.10"),
    DisciplineAreaCode.ECONOMICS_FINANCE: _weights(analytical="0.30", data="0.25", business="0.30", research="0.10", communication="0.05"),
    DisciplineAreaCode.BUSINESS_MANAGEMENT: _weights(business="0.45", communication="0.25", analytical="0.15", creative="0.10", data="0.05"),
    DisciplineAreaCode.LAW_POLICY_PUBLIC_ADMINISTRATION: _weights(communication="0.40", research="0.20", analytical="0.20", business="0.15", creative="0.05"),
    DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE: _weights(communication="0.50", creative="0.25", research="0.15", analytical="0.10"),
    DisciplineAreaCode.HISTORY_PHILOSOPHY_HUMANITIES: _weights(research="0.35", communication="0.30", analytical="0.20", creative="0.15"),
    DisciplineAreaCode.ART_DESIGN_MEDIA: _weights(creative="0.45", communication="0.25", system_design="0.10", research="0.05", business="0.10", software_creation="0.05"),
    DisciplineAreaCode.EDUCATION_PEDAGOGY: _weights(communication="0.45", research="0.20", creative="0.15", analytical="0.10", system_design="0.10"),
    DisciplineAreaCode.SPORT_TOURISM_HOSPITALITY: _weights(communication="0.35", physical_engineering="0.20", business="0.25", creative="0.10", analytical="0.10"),
    DisciplineAreaCode.SAFETY_DEFENSE_TRANSPORT: _weights(physical_engineering="0.35", system_design="0.25", analytical="0.20", communication="0.10", research="0.10"),
    DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY: _weights(analytical="0.15", communication="0.20", research="0.15", creative="0.15", system_design="0.15", business="0.10", data="0.10"),
}

__all__ = ["ACTIVITY_SIGNAL_WEIGHTS"]
