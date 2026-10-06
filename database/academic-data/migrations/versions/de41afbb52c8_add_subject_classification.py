"""Add immutable, typed subject-category classifications with Jev provenance.

Revision ID: de41afbb52c8
Revises: a7d2c91e4f60
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "de41afbb52c8"
down_revision: str | None = "a7d2c91e4f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TAXONOMY_KEY = "bmstu-subject-domain-16"
TAXONOMY_VERSION = "v1"

CATEGORIES = (
    (
        "01",
        "Математическая база",
        "Математические методы и фундаментальные математические дисциплины.",
    ),
    (
        "02",
        "Физика и естественно-научная база",
        "Физика, химия и фундаментальные естественные науки.",
    ),
    (
        "03",
        "Информатика, программирование и Computer Science",
        "Алгоритмы, программирование, разработка ПО и основы CS.",
    ),
    (
        "04",
        "Данные, ИИ и вычислительное моделирование",
        "Данные, искусственный интеллект и вычислительные модели.",
    ),
    (
        "05",
        "Информационные системы, сети и архитектура ИТ",
        "Информационные системы, сети, БД и ИТ-архитектура.",
    ),
    ("06", "Информационная безопасность", "Кибербезопасность, защита информации и криптография."),
    (
        "07",
        "Автоматика, управление, робототехника и мехатроника",
        "Автоматика, управление, робототехника и мехатроника.",
    ),
    (
        "08",
        "Конструирование, проектирование и CAD/CAE",
        "Инженерное проектирование, конструирование, CAD и CAE.",
    ),
    (
        "09",
        "Механика, прочность и инженерный расчёт",
        "Механика, прочность материалов и инженерные расчёты.",
    ),
    (
        "10",
        "Материалы и производственные технологии",
        "Материалы, обработка и производственные технологии.",
    ),
    (
        "11",
        "Отраслевые инженерные специализации",
        "Инженерные дисциплины отдельных отраслей и изделий.",
    ),
    ("12", "Дизайн и визуальные дисциплины", "Дизайн, графика и визуальные дисциплины."),
    (
        "13",
        "Экономика, менеджмент, логистика и предпринимательство",
        "Экономика, менеджмент, логистика и предпринимательство.",
    ),
    (
        "14",
        "Гуманитарные, коммуникационные и языковые дисциплины",
        "Языки, коммуникация и гуманитарные дисциплины.",
    ),
    (
        "15",
        "Право, безопасность труда и нормативка",
        "Право, охрана труда, стандарты и нормативные требования.",
    ),
    (
        "16",
        "Практики, НИР и итоговая аттестация",
        "Практики, НИР, выпускная работа и итоговая аттестация.",
    ),
)


def upgrade() -> None:
    op.create_table(
        "subject_taxonomies",
        sa.Column("taxonomy_key", sa.String(100), nullable=False),
        sa.Column("taxonomy_version", sa.String(40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("taxonomy_key", "taxonomy_version", name="pk_subject_taxonomies"),
    )
    op.create_table(
        "subject_taxonomy_categories",
        sa.Column("taxonomy_key", sa.String(100), nullable=False),
        sa.Column("taxonomy_version", sa.String(40), nullable=False),
        sa.Column("category_code", sa.String(8), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "ordinal BETWEEN 1 AND 16", name="ck_subject_taxonomy_categories_valid_ordinal"
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_key", "taxonomy_version"],
            ["subject_taxonomies.taxonomy_key", "subject_taxonomies.taxonomy_version"],
            name="fk_subject_taxonomy_categories_taxonomy",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "taxonomy_key",
            "taxonomy_version",
            "category_code",
            name="pk_subject_taxonomy_categories",
        ),
        sa.UniqueConstraint(
            "taxonomy_key", "taxonomy_version", "ordinal", name="uq_subject_taxonomy_ordinal"
        ),
    )
    op.create_table(
        "subject_classification_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_key", sa.String(200), nullable=False),
        sa.Column("taxonomy_key", sa.String(100), nullable=False),
        sa.Column("taxonomy_version", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("requested_model", sa.String(120), nullable=False),
        sa.Column("resolved_model_version", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("source_bundle_sha256", sa.String(64), nullable=False),
        sa.Column("source_input_sha256", sa.String(64), nullable=False),
        sa.Column("result_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.Column("classified_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_rub", sa.Numeric(14, 8), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status = 'complete'", name="ck_subject_classification_runs_complete_only"
        ),
        sa.CheckConstraint(
            "expected_count > 0 AND classified_count = expected_count",
            name="ck_subject_classification_runs_complete_counts",
        ),
        sa.CheckConstraint(
            "failed_count = 0", name="ck_subject_classification_runs_no_failed_classifications"
        ),
        sa.CheckConstraint(
            "source_bundle_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_subject_classification_runs_valid_source_digest",
        ),
        sa.CheckConstraint(
            "source_input_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_subject_classification_runs_valid_input_digest",
        ),
        sa.CheckConstraint(
            "result_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_subject_classification_runs_valid_result_digest",
        ),
        sa.CheckConstraint(
            "prompt_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_subject_classification_runs_valid_prompt_digest",
        ),
        sa.CheckConstraint(
            "cost_rub IS NULL OR cost_rub >= 0",
            name="ck_subject_classification_runs_nonnegative_cost",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["data_releases.id"],
            name="fk_subject_classification_run_release",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_key", "taxonomy_version"],
            ["subject_taxonomies.taxonomy_key", "subject_taxonomies.taxonomy_version"],
            name="fk_subject_classification_run_taxonomy",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subject_classification_runs"),
        sa.UniqueConstraint("release_id", "external_key", name="uq_subject_classification_run_key"),
        sa.UniqueConstraint("release_id", "id", name="uq_subject_classification_run_release_id"),
    )
    op.create_index(
        "ix_subject_classification_runs_release_created",
        "subject_classification_runs",
        ["release_id", "created_at"],
    )
    op.create_table(
        "subject_classifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_course_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("curriculum_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("taxonomy_key", sa.String(100), nullable=False),
        sa.Column("taxonomy_version", sa.String(40), nullable=False),
        sa.Column("category_code", sa.String(8), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=False),
        sa.Column("probabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("jev_answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(catalog_course_id, curriculum_item_id) = 1",
            name="ck_subject_classifications_exactly_one_typed_subject",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_subject_classifications_valid_confidence",
        ),
        sa.CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$'", name="ck_subject_classifications_valid_input_digest"
        ),
        sa.CheckConstraint(
            "review_status IN ('classified', 'needs_review')",
            name="ck_subject_classifications_valid_review_status",
        ),
        sa.ForeignKeyConstraint(
            ["release_id", "run_id"],
            ["subject_classification_runs.release_id", "subject_classification_runs.id"],
            name="fk_subject_classifications_run_release",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["release_id", "catalog_course_id"],
            ["catalog_courses.release_id", "catalog_courses.id"],
            name="fk_subject_classifications_catalog_course",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["release_id", "curriculum_item_id"],
            ["curriculum_items.release_id", "curriculum_items.id"],
            name="fk_subject_classifications_curriculum_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_key", "taxonomy_version", "category_code"],
            [
                "subject_taxonomy_categories.taxonomy_key",
                "subject_taxonomy_categories.taxonomy_version",
                "subject_taxonomy_categories.category_code",
            ],
            name="fk_subject_classifications_category",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subject_classifications"),
        sa.UniqueConstraint(
            "run_id", "catalog_course_id", name="uq_subject_classifications_run_course"
        ),
        sa.UniqueConstraint(
            "run_id", "curriculum_item_id", name="uq_subject_classifications_run_item"
        ),
    )
    op.create_index(
        "ix_subject_classifications_release_course",
        "subject_classifications",
        ["release_id", "catalog_course_id"],
    )
    op.create_index(
        "ix_subject_classifications_release_item",
        "subject_classifications",
        ["release_id", "curriculum_item_id"],
    )
    op.create_index(
        "ix_subject_classifications_run", "subject_classifications", ["run_id", "category_code"]
    )

    op.bulk_insert(
        sa.table(
            "subject_taxonomies",
            sa.column("taxonomy_key", sa.String),
            sa.column("taxonomy_version", sa.String),
            sa.column("name", sa.Text),
            sa.column("description", sa.Text),
        ),
        [
            {
                "taxonomy_key": TAXONOMY_KEY,
                "taxonomy_version": TAXONOMY_VERSION,
                "name": "Предметные категории МГТУ",
                "description": (
                    "Дополнительная предметная классификация по 16 категориям, "
                    "заданным пользователем; не заменяет taxonomy-22.v1 Andromeda."
                ),
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "subject_taxonomy_categories",
            sa.column("taxonomy_key", sa.String),
            sa.column("taxonomy_version", sa.String),
            sa.column("category_code", sa.String),
            sa.column("ordinal", sa.Integer),
            sa.column("name", sa.Text),
            sa.column("definition", sa.Text),
        ),
        [
            {
                "taxonomy_key": TAXONOMY_KEY,
                "taxonomy_version": TAXONOMY_VERSION,
                "category_code": code,
                "ordinal": index,
                "name": name,
                "definition": definition,
            }
            for index, (code, name, definition) in enumerate(CATEGORIES, 1)
        ],
    )

    op.execute(
        """
        CREATE FUNCTION academic_data_reject_subject_classification_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Subject classification facts are append-only'
                USING ERRCODE = '55000';
        END
        $$
        """
    )
    for table in (
        "subject_taxonomies",
        "subject_taxonomy_categories",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION academic_data_reject_subject_classification_mutation()"
        )
    for table in ("subject_classification_runs", "subject_classifications"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION academic_data_reject_subject_classification_mutation()"
        )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_subject_classifications_append_only ON subject_classifications"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_subject_classification_runs_append_only "
        "ON subject_classification_runs"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_subject_taxonomy_categories_append_only "
        "ON subject_taxonomy_categories"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_subject_taxonomies_append_only ON subject_taxonomies")
    op.execute("DROP FUNCTION IF EXISTS academic_data_reject_subject_classification_mutation()")
    op.drop_table("subject_classifications")
    op.drop_index(
        "ix_subject_classification_runs_release_created", table_name="subject_classification_runs"
    )
    op.drop_table("subject_classification_runs")
    op.drop_table("subject_taxonomy_categories")
    op.drop_table("subject_taxonomies")
