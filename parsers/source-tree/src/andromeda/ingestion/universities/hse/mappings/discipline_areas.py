from __future__ import annotations

from andromeda.modules.disciplines.domain.areas import AreaVector, DisciplineAreaCode, area_vector


MATH = area_vector((DisciplineAreaCode.MATHEMATICS_STATISTICS, "1.00"))
COMPUTER = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1.00"))
COMPUTER_MATH = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.60"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.40"))
ECONOMICS = area_vector((DisciplineAreaCode.ECONOMICS_FINANCE, "0.70"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.30"))
BUSINESS = area_vector((DisciplineAreaCode.BUSINESS_MANAGEMENT, "1.00"))
LANGUAGE = area_vector((DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE, "1.00"))
HUMANITIES = area_vector((DisciplineAreaCode.HISTORY_PHILOSOPHY_HUMANITIES, "1.00"))
SOCIAL = area_vector((DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "1.00"))
LAW = area_vector((DisciplineAreaCode.LAW_POLICY_PUBLIC_ADMINISTRATION, "1.00"))
ART = area_vector((DisciplineAreaCode.ART_DESIGN_MEDIA, "1.00"))
UNIVERSAL = area_vector((DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "1.00"))


# Exact source-name overrides for recurring HSE curriculum labels. The generic
# classifier remains the fallback for new HSE subjects, and all vectors are
# deterministic, explicit and sum to 1.0000.
HSE_DISCIPLINE_AREA_OVERRIDES: dict[str, AreaVector] = {
    "математический анализ": MATH,
    "линейная алгебра": MATH,
    "теория вероятностей и математическая статистика": MATH,
    "дискретная математика": MATH,
    "программирование": COMPUTER,
    "структуры и алгоритмы компьютерной обработки данных": COMPUTER_MATH,
    "машинное обучение": COMPUTER_MATH,
    "введение в анализ данных": COMPUTER_MATH,
    "базы данных": COMPUTER,
    "операционные системы": COMPUTER,
    "эконометрика": ECONOMICS,
    "микроэкономика": ECONOMICS,
    "макроэкономика": ECONOMICS,
    "основы предпринимательства": BUSINESS,
    "менеджмент": BUSINESS,
    "академическое письмо": LANGUAGE,
    "английский язык": LANGUAGE,
    "иностранный язык": LANGUAGE,
    "философия": HUMANITIES,
    "социология": SOCIAL,
    "правоведение": LAW,
    "дизайн-мышление": ART,
    "проектный семинар": UNIVERSAL,
    "учебная практика": UNIVERSAL,
    "производственная практика": UNIVERSAL,
    "научно-исследовательский семинар": UNIVERSAL,
}


__all__ = ["HSE_DISCIPLINE_AREA_OVERRIDES"]
