"""Create the stable pre-comparison tracer-bullet schema."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_tracer_bullet"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create only the tables owned by the initial revision.

    The old implementation delegated to the current ORM metadata.  That made
    a historical revision change whenever a new model was added and caused a
    fresh database to start with columns from later revisions.  Explicit
    operations keep the migration chain stable on both SQLite and PostgreSQL.
    """
    op.create_table(
        "education_levels",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "universities",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("city", sa.String(length=256), nullable=False),
        sa.Column("official_site", sa.Text(), nullable=False),
        sa.Column("address", sa.String(length=512), nullable=False),
        sa.CheckConstraint("length(name) > 0", name="ck_university_name_non_empty"),
        sa.CheckConstraint("length(city) > 0", name="ck_university_city_non_empty"),
        sa.CheckConstraint("length(address) > 0", name="ck_university_address_non_empty"),
        sa.CheckConstraint("id LIKE 'university:%'", name="ck_university_id_shape"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "directions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("education_level", sa.String(length=32), nullable=False),
        sa.CheckConstraint("length(code) = 8 AND substr(code, 3, 1) = '.' AND substr(code, 6, 1) = '.'", name="ck_direction_code_shape"),
        sa.CheckConstraint("id = 'direction:' || code", name="ck_direction_id_matches_code"),
        sa.CheckConstraint("length(name) > 0", name="ck_direction_name_non_empty"),
        sa.ForeignKeyConstraint(["education_level"], ["education_levels.id"]),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("university_id", "code", name="uq_direction_university_code"),
    )
    op.create_table(
        "assessment_types",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "disciplines",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("normalized_name", sa.String(length=256), nullable=False),
        sa.CheckConstraint("length(name) > 0", name="ck_discipline_name_non_empty"),
        sa.CheckConstraint("length(normalized_name) > 0", name="ck_discipline_normalized_non_empty"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_table(
        "educational_programs",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("direction_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("education_year", sa.Integer(), nullable=False),
        sa.Column("study_plan_url", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.CheckConstraint("id = 'program:' || code", name="ck_program_id_matches_code"),
        sa.CheckConstraint("code LIKE '__.__.__-%'", name="ck_program_code_shape"),
        sa.CheckConstraint("education_year >= 2000 AND education_year <= 2100", name="ck_program_education_year"),
        sa.CheckConstraint("length(name) > 0", name="ck_program_name_non_empty"),
        sa.ForeignKeyConstraint(["direction_id"], ["directions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("direction_id", "code", name="uq_program_direction_code"),
    )
    op.create_table(
        "curricula",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("program_id", sa.String(length=96), nullable=False),
        sa.Column("education_year", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("education_year >= 2000 AND education_year <= 2100", name="ck_curriculum_education_year"),
        sa.CheckConstraint("id LIKE 'curriculum:%'", name="ck_curriculum_id_shape"),
        sa.ForeignKeyConstraint(["program_id"], ["educational_programs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "education_year", name="uq_curriculum_program_year"),
    )
    op.create_table(
        "curriculum_items",
        sa.Column("id", sa.String(length=256), nullable=False),
        sa.Column("curriculum_id", sa.String(length=128), nullable=False),
        sa.Column("discipline_id", sa.String(length=64), nullable=False),
        sa.Column("semester", sa.Integer(), nullable=True),
        sa.Column("hours", sa.Integer(), nullable=False),
        sa.Column("credits", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("subject_group", sa.String(length=256), nullable=True),
        sa.Column("source_position", sa.Integer(), nullable=True),
        sa.CheckConstraint("semester IS NULL OR (semester >= 1 AND semester <= 12)", name="ck_item_semester"),
        sa.CheckConstraint("hours >= 0 AND hours <= 2000", name="ck_item_hours"),
        sa.CheckConstraint("credits IS NULL OR (credits >= 0 AND credits <= 60)", name="ck_item_credits"),
        sa.CheckConstraint("source_position IS NULL OR source_position >= 1", name="ck_item_source_position"),
        sa.ForeignKeyConstraint(["curriculum_id"], ["curricula.id"]),
        sa.ForeignKeyConstraint(["discipline_id"], ["disciplines.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("curriculum_id", "discipline_id", "semester", name="uq_curriculum_item_identity"),
    )
    op.create_table(
        "curriculum_item_assessments",
        sa.Column("curriculum_item_id", sa.String(length=256), nullable=False),
        sa.Column("assessment_type_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["assessment_type_id"], ["assessment_types.id"]),
        sa.ForeignKeyConstraint(["curriculum_item_id"], ["curriculum_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("curriculum_item_id", "assessment_type_id"),
    )
    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source_snapshots",
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("ingest_run_id", sa.String(length=64), nullable=False),
        sa.Column("source_kind", sa.String(length=128), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=256), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_source_snapshot_sha256_length"),
        sa.CheckConstraint("status_code >= 200 AND status_code <= 599", name="ck_source_snapshot_status"),
        sa.ForeignKeyConstraint(["ingest_run_id"], ["ingest_runs.id"]),
        sa.PrimaryKeyConstraint("content_sha256"),
    )
    op.create_table(
        "raw_source_records",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("record_type", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_sha256"], ["source_snapshots.content_sha256"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("raw_source_records")
    op.drop_table("source_snapshots")
    op.drop_table("ingest_runs")
    op.drop_table("curriculum_item_assessments")
    op.drop_table("curriculum_items")
    op.drop_table("curricula")
    op.drop_table("educational_programs")
    op.drop_table("disciplines")
    op.drop_table("assessment_types")
    op.drop_table("directions")
    op.drop_table("universities")
    op.drop_table("education_levels")
