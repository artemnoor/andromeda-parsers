"""Add the Andromeda discipline-area taxonomy and weighted vectors."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_discipline_taxonomy"
down_revision = "0002_comparison_identity"
branch_labels = None
depends_on = None


AREA_ROWS = (
    ("mathematics_statistics", "Математика и статистика", "Математический аппарат, статистика, оптимизация и исследование операций", 1),
    ("computer_science_data", "Компьютерные науки и данные", "Программирование, данные, информационные системы, AI и кибербезопасность", 2),
    ("physics_astronomy", "Физика и астрономия", "Физические законы, механика, оптика, электричество и астрофизика", 3),
    ("chemistry_materials", "Химия и материаловедение", "Химические процессы, полимеры и материалы", 4),
    ("biology_biotechnology", "Биология и биотехнологии", "Живые системы, генетика, биохимия и биотехнологии", 5),
    ("earth_environment", "Земля, экология и окружающая среда", "Земные системы, экология, климат и природопользование", 6),
    ("engineering_technology", "Инженерия и технологии", "Инженерные методы, электроника, механика, робототехника и производство", 7),
    ("architecture_construction", "Архитектура, строительство и урбанистика", "Архитектура, здания, конструкции, BIM и городская среда", 8),
    ("agriculture_veterinary", "Сельское хозяйство и ветеринария", "Агрономия, лесное хозяйство, животные и ветеринария", 9),
    ("medicine_health", "Медицина и здоровье", "Медицина, фармация, диагностика и общественное здоровье", 10),
    ("psychology_cognitive", "Психология и когнитивные науки", "Психология, когнитивистика, психодиагностика и поведение", 11),
    ("society_social_sciences", "Общество и социальные науки", "Социология, антропология, демография и социальные процессы", 12),
    ("economics_finance", "Экономика и финансы", "Экономика, эконометрика, финансы и инвестиции", 13),
    ("business_management", "Бизнес, управление и предпринимательство", "Менеджмент, маркетинг, бизнес-процессы и предпринимательство", 14),
    ("law_policy_public_administration", "Право, политика и государственное управление", "Право, политика, государственное управление и дипломатия", 15),
    ("languages_linguistics_literature", "Языки, лингвистика и литература", "Языки, перевод, лингвистика, филология и литература", 16),
    ("history_philosophy_humanities", "История, философия и гуманитарные науки", "История, философия, этика, культура и религиоведение", 17),
    ("art_design_media", "Искусство, дизайн, медиа и коммуникации", "Искусство, дизайн, мультимедиа, журналистика и реклама", 18),
    ("education_pedagogy", "Образование и педагогика", "Педагогика, методики обучения и образовательные технологии", 19),
    ("sport_tourism_hospitality", "Спорт, туризм и индустрия гостеприимства", "Физкультура, спорт, туризм, гостиничное и ресторанное дело", 20),
    ("safety_defense_transport", "Безопасность, оборона и транспортные системы", "Безопасность, защита населения, оборона, транспорт и навигация", 21),
    ("universal_interdisciplinary", "Универсальные и междисциплинарные дисциплины", "Проектная деятельность, практики, вводные и исследовательские дисциплины без одного домена", 22),
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "discipline_areas" not in tables:
        op.create_table(
            "discipline_areas",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=256), nullable=False),
            sa.Column("description", sa.String(length=512), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.CheckConstraint("length(id) > 0", name="ck_discipline_area_id_non_empty"),
            sa.CheckConstraint("length(name) > 0", name="ck_discipline_area_name_non_empty"),
            sa.CheckConstraint("position >= 1 AND position <= 22", name="ck_discipline_area_position"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("position", name="uq_discipline_area_position"),
        )
    if "discipline_area_weights" not in tables:
        op.create_table(
            "discipline_area_weights",
            sa.Column("discipline_id", sa.String(length=64), nullable=False),
            sa.Column("area_id", sa.String(length=64), nullable=False),
            sa.Column("weight", sa.Numeric(precision=5, scale=4), nullable=False),
            sa.CheckConstraint("weight > 0 AND weight <= 1", name="ck_discipline_area_weight_range"),
            sa.ForeignKeyConstraint(["area_id"], ["discipline_areas.id"]),
            sa.ForeignKeyConstraint(["discipline_id"], ["disciplines.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("discipline_id", "area_id"),
        )
    area_table = sa.table(
        "discipline_areas",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("position", sa.Integer),
    )
    existing_count = bind.execute(sa.text("SELECT COUNT(*) FROM discipline_areas")).scalar_one()
    if existing_count == 0:
        op.bulk_insert(
            area_table,
            [
                {"id": code, "name": name, "description": description, "position": position}
                for code, name, description, position in AREA_ROWS
            ],
        )


def downgrade() -> None:
    op.drop_table("discipline_area_weights")
    op.drop_table("discipline_areas")
