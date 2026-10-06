from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias

from pydantic import Field

from ....shared.contracts.base import ContractModel
from ....shared.contracts.ids import ShortText


class DisciplineAreaCode(StrEnum):
    MATHEMATICS_STATISTICS = "mathematics_statistics"
    COMPUTER_SCIENCE_DATA = "computer_science_data"
    PHYSICS_ASTRONOMY = "physics_astronomy"
    CHEMISTRY_MATERIALS = "chemistry_materials"
    BIOLOGY_BIOTECHNOLOGY = "biology_biotechnology"
    EARTH_ENVIRONMENT = "earth_environment"
    ENGINEERING_TECHNOLOGY = "engineering_technology"
    ARCHITECTURE_CONSTRUCTION = "architecture_construction"
    AGRICULTURE_VETERINARY = "agriculture_veterinary"
    MEDICINE_HEALTH = "medicine_health"
    PSYCHOLOGY_COGNITIVE = "psychology_cognitive"
    SOCIETY_SOCIAL_SCIENCES = "society_social_sciences"
    ECONOMICS_FINANCE = "economics_finance"
    BUSINESS_MANAGEMENT = "business_management"
    LAW_POLICY_PUBLIC_ADMINISTRATION = "law_policy_public_administration"
    LANGUAGES_LINGUISTICS_LITERATURE = "languages_linguistics_literature"
    HISTORY_PHILOSOPHY_HUMANITIES = "history_philosophy_humanities"
    ART_DESIGN_MEDIA = "art_design_media"
    EDUCATION_PEDAGOGY = "education_pedagogy"
    SPORT_TOURISM_HOSPITALITY = "sport_tourism_hospitality"
    SAFETY_DEFENSE_TRANSPORT = "safety_defense_transport"
    UNIVERSAL_INTERDISCIPLINARY = "universal_interdisciplinary"


class DisciplineAreaDefinition(ContractModel):
    code: DisciplineAreaCode
    name: ShortText
    description: ShortText
    position: int = Field(strict=True, ge=1, le=22)


class DisciplineAreaWeight(ContractModel):
    area: DisciplineAreaCode
    weight: Decimal = Field(strict=True, gt=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)


class DisciplineAreaSummary(ContractModel):
    area: DisciplineAreaCode
    share: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)


AreaVector: TypeAlias = tuple[tuple[DisciplineAreaCode, Decimal], ...]


_AREA_DEFINITIONS: tuple[DisciplineAreaDefinition, ...] = (
    DisciplineAreaDefinition(code=DisciplineAreaCode.MATHEMATICS_STATISTICS, name="Математика и статистика", description="Математический аппарат, статистика, оптимизация и исследование операций", position=1),
    DisciplineAreaDefinition(code=DisciplineAreaCode.COMPUTER_SCIENCE_DATA, name="Компьютерные науки и данные", description="Программирование, данные, информационные системы, AI и кибербезопасность", position=2),
    DisciplineAreaDefinition(code=DisciplineAreaCode.PHYSICS_ASTRONOMY, name="Физика и астрономия", description="Физические законы, механика, оптика, электричество и астрофизика", position=3),
    DisciplineAreaDefinition(code=DisciplineAreaCode.CHEMISTRY_MATERIALS, name="Химия и материаловедение", description="Химические процессы, полимеры и материалы", position=4),
    DisciplineAreaDefinition(code=DisciplineAreaCode.BIOLOGY_BIOTECHNOLOGY, name="Биология и биотехнологии", description="Живые системы, генетика, биохимия и биотехнологии", position=5),
    DisciplineAreaDefinition(code=DisciplineAreaCode.EARTH_ENVIRONMENT, name="Земля, экология и окружающая среда", description="Земные системы, экология, климат и природопользование", position=6),
    DisciplineAreaDefinition(code=DisciplineAreaCode.ENGINEERING_TECHNOLOGY, name="Инженерия и технологии", description="Инженерные методы, электроника, механика, робототехника и производство", position=7),
    DisciplineAreaDefinition(code=DisciplineAreaCode.ARCHITECTURE_CONSTRUCTION, name="Архитектура, строительство и урбанистика", description="Архитектура, здания, конструкции, BIM и городская среда", position=8),
    DisciplineAreaDefinition(code=DisciplineAreaCode.AGRICULTURE_VETERINARY, name="Сельское хозяйство и ветеринария", description="Агрономия, лесное хозяйство, животные и ветеринария", position=9),
    DisciplineAreaDefinition(code=DisciplineAreaCode.MEDICINE_HEALTH, name="Медицина и здоровье", description="Медицина, фармация, диагностика и общественное здоровье", position=10),
    DisciplineAreaDefinition(code=DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, name="Психология и когнитивные науки", description="Психология, когнитивистика, психодиагностика и поведение", position=11),
    DisciplineAreaDefinition(code=DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, name="Общество и социальные науки", description="Социология, антропология, демография и социальные процессы", position=12),
    DisciplineAreaDefinition(code=DisciplineAreaCode.ECONOMICS_FINANCE, name="Экономика и финансы", description="Экономика, эконометрика, финансы и инвестиции", position=13),
    DisciplineAreaDefinition(code=DisciplineAreaCode.BUSINESS_MANAGEMENT, name="Бизнес, управление и предпринимательство", description="Менеджмент, маркетинг, бизнес-процессы и предпринимательство", position=14),
    DisciplineAreaDefinition(code=DisciplineAreaCode.LAW_POLICY_PUBLIC_ADMINISTRATION, name="Право, политика и государственное управление", description="Право, политика, государственное управление и дипломатия", position=15),
    DisciplineAreaDefinition(code=DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE, name="Языки, лингвистика и литература", description="Языки, перевод, лингвистика, филология и литература", position=16),
    DisciplineAreaDefinition(code=DisciplineAreaCode.HISTORY_PHILOSOPHY_HUMANITIES, name="История, философия и гуманитарные науки", description="История, философия, этика, культура и религиоведение", position=17),
    DisciplineAreaDefinition(code=DisciplineAreaCode.ART_DESIGN_MEDIA, name="Искусство, дизайн, медиа и коммуникации", description="Искусство, дизайн, мультимедиа, журналистика и реклама", position=18),
    DisciplineAreaDefinition(code=DisciplineAreaCode.EDUCATION_PEDAGOGY, name="Образование и педагогика", description="Педагогика, методики обучения и образовательные технологии", position=19),
    DisciplineAreaDefinition(code=DisciplineAreaCode.SPORT_TOURISM_HOSPITALITY, name="Спорт, туризм и индустрия гостеприимства", description="Физкультура, спорт, туризм, гостиничное и ресторанное дело", position=20),
    DisciplineAreaDefinition(code=DisciplineAreaCode.SAFETY_DEFENSE_TRANSPORT, name="Безопасность, оборона и транспортные системы", description="Безопасность, защита населения, оборона, транспорт и навигация", position=21),
    DisciplineAreaDefinition(code=DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, name="Универсальные и междисциплинарные дисциплины", description="Проектная деятельность, практики, вводные и исследовательские дисциплины без одного домена", position=22),
)


def area_catalog() -> tuple[DisciplineAreaDefinition, ...]:
    return tuple(definition.model_copy(deep=True) for definition in _AREA_DEFINITIONS)


def area_definition(code: DisciplineAreaCode) -> DisciplineAreaDefinition:
    for definition in _AREA_DEFINITIONS:
        if definition.code is code:
            return definition.model_copy(deep=True)
    raise KeyError(code)


def area_position(code: DisciplineAreaCode) -> int:
    return area_definition(code).position


def area_vector(*entries: tuple[DisciplineAreaCode, str | Decimal]) -> AreaVector:
    vector = tuple((code, value if isinstance(value, Decimal) else Decimal(value)) for code, value in entries)
    if not vector or len({code for code, _ in vector}) != len(vector) or sum((weight for _, weight in vector), Decimal("0")) != Decimal("1"):
        raise ValueError("discipline area vector must contain unique areas whose weights sum to one")
    return vector


def default_area_weights() -> tuple[DisciplineAreaWeight, ...]:
    return (DisciplineAreaWeight(area=DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, weight=Decimal("1.0000")),)


__all__ = [
    "AreaVector",
    "DisciplineAreaCode",
    "DisciplineAreaDefinition",
    "DisciplineAreaSummary",
    "DisciplineAreaWeight",
    "area_catalog",
    "area_definition",
    "area_position",
    "area_vector",
    "default_area_weights",
]
