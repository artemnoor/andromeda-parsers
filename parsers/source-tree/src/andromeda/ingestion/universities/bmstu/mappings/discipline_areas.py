"""Explicit BMSTU subject vectors for the Andromeda taxonomy.

These mappings are intentionally source-owned: the same discipline is still
identified by its canonical name, while its semantic vector can be refined for
the vocabulary used by a particular university. We keep every source name and
never collapse a multi-area subject to one label.
"""

from __future__ import annotations

from andromeda.modules.disciplines.domain.areas import AreaVector, DisciplineAreaCode, area_vector
from andromeda.modules.disciplines.domain.identity import normalize_discipline_name


MATH = area_vector((DisciplineAreaCode.MATHEMATICS_STATISTICS, "1.00"))
MATH_COMPUTER = area_vector((DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.75"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.25"))
COMPUTER = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "1.00"))
COMPUTER_MATH = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.75"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.25"))
COMPUTER_ENGINEERING = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.65"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.35"))
COMPUTER_BUSINESS = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.55"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.45"))
COMPUTER_BUSINESS_ENGINEERING = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.50"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.35"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.15"))
COMPUTER_MATH_BUSINESS = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.45"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.35"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.20"))
COMPUTER_MATH_ENGINEERING = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.55"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.25"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.20"))
COMPUTER_MATH_UNIVERSAL = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.60"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.25"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.15"))
COMPUTER_ART = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.85"), (DisciplineAreaCode.ART_DESIGN_MEDIA, "0.15"))
COMPUTER_LANGUAGE_MATH = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.65"), (DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE, "0.25"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.10"))
COMPUTER_SAFETY = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.70"), (DisciplineAreaCode.SAFETY_DEFENSE_TRANSPORT, "0.30"))
COMPUTER_SAFETY_BUSINESS = area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.55"), (DisciplineAreaCode.SAFETY_DEFENSE_TRANSPORT, "0.35"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.10"))
PHYSICS = area_vector((DisciplineAreaCode.PHYSICS_ASTRONOMY, "1.00"))
PHYSICS_ENGINEERING = area_vector((DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.55"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.45"))
ENGINEERING = area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "1.00"))
ENGINEERING_COMPUTER = area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.50"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.35"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.15"))
ENGINEERING_COMPUTER_UNIVERSAL = area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.75"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.10"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.15"))
ENGINEERING_MATH = area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.60"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.40"))
ENGINEERING_PHYSICS = area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.75"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.25"))
ENGINEERING_PHYSICS_COMPUTER = area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.85"), (DisciplineAreaCode.PHYSICS_ASTRONOMY, "0.10"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.05"))
ENGINEERING_COMPUTER_UNIVERSAL = area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.80"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.05"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.15"))
ECONOMICS_BUSINESS = area_vector((DisciplineAreaCode.ECONOMICS_FINANCE, "0.80"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.20"))
ECONOMICS_BUSINESS_ENGINEERING = area_vector((DisciplineAreaCode.ECONOMICS_FINANCE, "0.55"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.30"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.15"))
BUSINESS = area_vector((DisciplineAreaCode.BUSINESS_MANAGEMENT, "1.00"))
BUSINESS_ENGINEERING_UNIVERSAL = area_vector((DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.50"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.40"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.10"))
LAW = area_vector((DisciplineAreaCode.LAW_POLICY_PUBLIC_ADMINISTRATION, "1.00"))
LAW_BUSINESS_UNIVERSAL = area_vector((DisciplineAreaCode.LAW_POLICY_PUBLIC_ADMINISTRATION, "0.75"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.15"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.10"))
LAW_UNIVERSAL = area_vector((DisciplineAreaCode.LAW_POLICY_PUBLIC_ADMINISTRATION, "0.70"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.30"))
LAW_SOCIETY = area_vector((DisciplineAreaCode.LAW_POLICY_PUBLIC_ADMINISTRATION, "0.65"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.35"))
LANGUAGE_BUSINESS = area_vector((DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE, "0.75"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.25"))
HUMANITIES_ENGINEERING = area_vector((DisciplineAreaCode.HISTORY_PHILOSOPHY_HUMANITIES, "0.80"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.20"))
PSYCHOLOGY_ART_COMPUTER = area_vector((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.45"), (DisciplineAreaCode.ART_DESIGN_MEDIA, "0.30"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.25"))
PSYCHOLOGY_SOCIETY_UNIVERSAL = area_vector((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.60"), (DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES, "0.20"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.20"))
PSYCHOLOGY_EDUCATION_UNIVERSAL = area_vector((DisciplineAreaCode.PSYCHOLOGY_COGNITIVE, "0.55"), (DisciplineAreaCode.EDUCATION_PEDAGOGY, "0.35"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.10"))
SAFETY = area_vector((DisciplineAreaCode.SAFETY_DEFENSE_TRANSPORT, "1.00"))
SAFETY_EARTH = area_vector((DisciplineAreaCode.SAFETY_DEFENSE_TRANSPORT, "0.70"), (DisciplineAreaCode.EARTH_ENVIRONMENT, "0.30"))
SPORT = area_vector((DisciplineAreaCode.SPORT_TOURISM_HOSPITALITY, "1.00"))
UNIVERSAL = area_vector((DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "1.00"))


def _group(names: tuple[str, ...], vector: AreaVector) -> tuple[tuple[str, AreaVector], ...]:
    return tuple((normalize_discipline_name(name), vector) for name in names)


def _build_overrides() -> dict[str, AreaVector]:
    groups = (
        _group((
            "Аналитическая геометрия",
            "Интегралы и дифференциальные уравнения",
            "Исследование операций",
            "Линейная алгебра и функции нескольких переменных",
            "Математический анализ",
            "Теория вероятностей и математическая статистика",
        ), MATH),
        _group(("Дискретная математика",), MATH_COMPUTER),
        _group((
            "Имитационное моделирование дискретных процессов",
            "Нечеткие множества в СППР",
            "Оперативный анализ данных",
        ), COMPUTER_MATH),
        _group((
            "Анализ характеристик производительности КИС",
            "Аналитические модели АСОИУ",
            "Методы поддержки принятия решений",
        ), COMPUTER_MATH_BUSINESS),
        _group((
            "Методы машинного обучения в АСОИУ",
            "Основы машинного обучения (модуль 2 от VK)",
            "Технология машинного обучения",
            "Миварные технологии логического ИИ",
            "Разработка нейросетевых систем",
            "Технологии искусственного интеллекта",
        ), COMPUTER_MATH),
        _group((
            "Базы данных",
            "Модели данных и знаний",
            "Надежность информационных систем",
            "Операционные системы",
            "Постреляционные БД",
            "Сетевое программное обеспечение",
            "Системное программирование",
            "Технологии разработки информационных систем",
            "Хранилища данных",
            "Эксплуатация АСОИУ",
            "Элементы управления в АСОИУ",
        ), COMPUTER),
        _group(("Автоматизация развертывания и эксплуатации информационных систем",), COMPUTER_BUSINESS_ENGINEERING),
        _group(("Алгоритмизация и программирование",), COMPUTER_MATH),
        _group(("Вычислительные средства АСОИУ",), COMPUTER_MATH_ENGINEERING),
        _group(("Корпоративные сети, масштабирование и оптимизация",), COMPUTER_BUSINESS),
        _group(("Корпоративные системы управления",), COMPUTER_BUSINESS_ENGINEERING),
        _group(("Методологии проектирования ИС", "Методы проектирования информационных систем"), COMPUTER_MATH_UNIVERSAL),
        _group(("Мобильная разработка на Android (модуль 3 от VK)", "Мобильная разработка на IOS (модуль 4 от VK)"), COMPUTER),
        _group(("Описание процессов жизненного цикла АСОИУ",), COMPUTER_BUSINESS),
        _group(("Оперативный анализ данных",), COMPUTER_MATH),
        _group(("Проектирование систем и продуктовая веб-разработка",), area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.65"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.20"), (DisciplineAreaCode.ART_DESIGN_MEDIA, "0.15"))),
        _group(("Проектирование систем и продуктовая веб- разработка",), area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.65"), (DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.20"), (DisciplineAreaCode.ART_DESIGN_MEDIA, "0.15"))),
        _group(("Программа по веб-разработке (модуль 1 от VK)",), COMPUTER_ART),
        _group(("Разработка киберфизических систем",), area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.50"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.40"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.10"))),
        _group(("Сети и телекоммуникации",), COMPUTER_ENGINEERING),
        _group(("Технологии взаимодействия на естественном языке",), COMPUTER_LANGUAGE_MATH),
        _group(("Управление информационной безопасностью",), COMPUTER_SAFETY_BUSINESS),
        _group(("ВКР - Защита информации",), COMPUTER_SAFETY),
        _group(("Архитектура предприятия",), COMPUTER_BUSINESS),
        _group(("Объектно-ориентированное проектирование",), COMPUTER_BUSINESS),
        _group(("Эргономический анализ ИС",), PSYCHOLOGY_ART_COMPUTER),
        _group(("Теоретическая информатика",), area_vector((DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.60"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.40"))),
        _group(("Технология мультимедиа",), area_vector((DisciplineAreaCode.ART_DESIGN_MEDIA, "0.45"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.55"))),
        _group(("Теория систем и системный анализ",), area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.45"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.35"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.20"))),
        _group(("Физика",), PHYSICS),
        _group(("История науки и техники",), HUMANITIES_ENGINEERING),
        _group(("Начертательная геометрия",), ENGINEERING_MATH),
        _group(("Инженерная и компьютерная графика",), ENGINEERING_COMPUTER),
        _group(("Конструкторско-технологическая практика", "Проектно-конструкторская практика", "Проектно-технологическая практика"), ENGINEERING_COMPUTER_UNIVERSAL),
        _group(("Основы робототехники",), area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.60"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.30"), (DisciplineAreaCode.MATHEMATICS_STATISTICS, "0.10"))),
        _group(("Прикладная механика и основы конструирования",), ENGINEERING_PHYSICS),
        _group(("Схемотехника дискретных устройств",), area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.85"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.15"))),
        _group(("Теоретическая механика",), PHYSICS_ENGINEERING),
        _group(("Учебно-технологический практикум",), ENGINEERING_COMPUTER_UNIVERSAL),
        _group(("Электроника",), ENGINEERING),
        _group(("Электротехника",), ENGINEERING_PHYSICS),
        _group(("Эксплуатационная практика",), area_vector((DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.60"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.40"))),
        _group(("Управление техническими проектами",), BUSINESS_ENGINEERING_UNIVERSAL),
        _group(("Производственный менеджмент",), area_vector((DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.75"), (DisciplineAreaCode.ECONOMICS_FINANCE, "0.15"), (DisciplineAreaCode.ENGINEERING_TECHNOLOGY, "0.10"))),
        _group(("Экономическая теория и финансовая грамотность",), ECONOMICS_BUSINESS),
        _group(("ВКР - Организационно-экономическое обеспечение / Технико-экономическое обоснование",), ECONOMICS_BUSINESS_ENGINEERING),
        _group(("Управление проектами информационных систем",), area_vector((DisciplineAreaCode.BUSINESS_MANAGEMENT, "0.45"), (DisciplineAreaCode.COMPUTER_SCIENCE_DATA, "0.45"), (DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, "0.10"))),
        _group(("ВКР - Нормативно-правовое обоснование / Интеллектуальная собственность / Патентный поиск",), LAW_BUSINESS_UNIVERSAL),
        _group(("Основы антикоррупционной деятельности в Российской Федерации",), LAW_UNIVERSAL),
        _group(("Основы российской государственности",), LAW_SOCIETY),
        _group(("Основы современного права России",), LAW),
        _group(("Русский язык в деловой коммуникации",), LANGUAGE_BUSINESS),
        _group(("Иностранный язык",), area_vector((DisciplineAreaCode.LANGUAGES_LINGUISTICS_LITERATURE, "1.00"))),
        _group(("История России", "Философия"), area_vector((DisciplineAreaCode.HISTORY_PHILOSOPHY_HUMANITIES, "1.00"))),
        _group(("Основы эффективной коммуникации и конфликтологии",), PSYCHOLOGY_SOCIETY_UNIVERSAL),
        _group(("Психолого-педагогические аспекты профессиональной деятельности",), PSYCHOLOGY_EDUCATION_UNIVERSAL),
        _group(("Педагогическая практика",), area_vector((DisciplineAreaCode.EDUCATION_PEDAGOGY, "1.00"))),
        _group(("Безопасность жизнедеятельности",), SAFETY),
        _group(("Экологическая и производственная безопасность",), SAFETY_EARTH),
        _group(("Физическая культура и спорт", "Элективный курс по физической культуре и спорту"), SPORT),
        _group((
            "Введение в специальность",
            "Введение в профессию",
            "Дисциплина по выбору No1",
            "Дисциплина по выбору No2",
            "Дисциплина по выбору No3",
            "Дисциплина по выбору No4",
            "Дисциплина по выбору No5",
            "Дисциплина по выбору No6",
            "Дисциплина по выбору No7",
            "Дисциплина по выбору No8",
            "Дисциплина по выбору No9",
            "Междисциплинарные научные проблемы",
            "Методология НИР",
            "Методология научного познания",
            "Методы научных исследований",
            "Научно-исследовательская практика",
            "Научно-исследовательская работа",
            "Ознакомительная практика",
            "Ознакомительная практика Производственная",
            "Основы методологии научных исследований",
            "Основы научных исследований",
            "Основы проектной деятельности",
            "Основы публикационной активности по результатам НИР",
            "Подготовка и защита ВКР",
            "Подготовка научных публикаций",
            "Практика по профилю профессиональной деятельности",
            "Преддипломная практика",
            "Профилирующая практика",
            "Учебная практика",
            "Учебный практикум",
            "Формы и методы научно-исследовательской работы",
            "Экспериментально-исследовательская практика",
            "Экспертная практика",
        ), UNIVERSAL),
        _group((
            "Экспертные системы",
            "Учебный практикум на ЭВМ",
        ), COMPUTER_MATH_UNIVERSAL),
        _group((
            "ВКР - Исследовательская практика",
            "ВКР - Исследовательская часть",
            "ВКР - Научно-исследовательская часть",
            "ВКР-Научно-исследовательская часть",
        ), UNIVERSAL),
    )
    result: dict[str, AreaVector] = {}
    for entries in groups:
        for name, vector in entries:
            if name in result and result[name] != vector:
                raise ValueError(f"duplicate BMSTU discipline classification: {name}")
            result[name] = vector
    return result


BMSTU_DISCIPLINE_AREA_OVERRIDES = _build_overrides()


__all__ = ["BMSTU_DISCIPLINE_AREA_OVERRIDES"]
