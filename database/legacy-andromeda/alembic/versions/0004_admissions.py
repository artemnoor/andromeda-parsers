"""Add source-backed admissions data linked to canonical programs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_admissions"
down_revision = "0003_discipline_taxonomy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admission_offerings",
        sa.Column("id", sa.String(length=320), nullable=False),
        sa.Column("program_id", sa.String(length=96), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("study_form", sa.String(length=32), nullable=False),
        sa.Column("funding_type", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("places", sa.Integer(), nullable=True),
        sa.Column("source_kind", sa.String(length=256), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.String(length=256), nullable=True),
        sa.Column("source_name", sa.String(length=512), nullable=True),
        sa.CheckConstraint("admission_year >= 2000 AND admission_year <= 2100", name="ck_admission_offering_year"),
        sa.CheckConstraint("places IS NULL OR (places >= 0 AND places <= 100000)", name="ck_admission_offering_places"),
        sa.CheckConstraint("length(id) > 0", name="ck_admission_offering_id_non_empty"),
        sa.CheckConstraint("length(source_kind) > 0", name="ck_admission_offering_source_kind"),
        sa.CheckConstraint("length(source_url) > 0", name="ck_admission_offering_source_url"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_admission_offering_sha256"),
        sa.ForeignKeyConstraint(["program_id"], ["educational_programs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "admission_year", "study_form", "funding_type", "scope", name="uq_admission_offering_identity"),
    )
    op.create_index("ix_admission_offerings_program_year", "admission_offerings", ["program_id", "admission_year"])

    op.create_table(
        "admission_exam_requirements",
        sa.Column("id", sa.String(length=384), nullable=False),
        sa.Column("offering_id", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("source_name", sa.String(length=256), nullable=False),
        sa.Column("minimum_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("is_choice", sa.Boolean(), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("source_kind", sa.String(length=256), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.String(length=256), nullable=True),
        sa.CheckConstraint("length(subject) > 0", name="ck_admission_exam_subject"),
        sa.CheckConstraint("minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 100)", name="ck_admission_exam_minimum"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_admission_exam_sha256"),
        sa.ForeignKeyConstraint(["offering_id"], ["admission_offerings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offering_id", "subject", "source_name", name="uq_admission_exam_identity"),
    )
    op.create_index("ix_admission_exams_offering", "admission_exam_requirements", ["offering_id"])

    op.create_table(
        "admission_quotas",
        sa.Column("id", sa.String(length=384), nullable=False),
        sa.Column("offering_id", sa.String(length=320), nullable=False),
        sa.Column("quota_type", sa.String(length=32), nullable=False),
        sa.Column("source_name", sa.String(length=256), nullable=False),
        sa.Column("places", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=256), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.String(length=256), nullable=True),
        sa.CheckConstraint("places >= 0 AND places <= 100000", name="ck_admission_quota_places"),
        sa.CheckConstraint("length(quota_type) > 0", name="ck_admission_quota_type"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_admission_quota_sha256"),
        sa.ForeignKeyConstraint(["offering_id"], ["admission_offerings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offering_id", "quota_type", "source_name", name="uq_admission_quota_identity"),
    )
    op.create_index("ix_admission_quotas_offering", "admission_quotas", ["offering_id"])

    op.create_table(
        "admission_passing_scores",
        sa.Column("id", sa.String(length=384), nullable=False),
        sa.Column("offering_id", sa.String(length=320), nullable=False),
        sa.Column("score_type", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("source_kind", sa.String(length=256), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.String(length=256), nullable=True),
        sa.CheckConstraint("length(score_type) > 0", name="ck_admission_passing_score_type"),
        sa.CheckConstraint("score >= 0 AND score <= 400", name="ck_admission_passing_score_range"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_admission_passing_score_sha256"),
        sa.ForeignKeyConstraint(["offering_id"], ["admission_offerings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offering_id", "score_type", name="uq_admission_passing_score_identity"),
    )
    op.create_index("ix_admission_passing_scores_offering", "admission_passing_scores", ["offering_id"])

    op.create_table(
        "admission_tuition",
        sa.Column("id", sa.String(length=384), nullable=False),
        sa.Column("offering_id", sa.String(length=320), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("academic_year", sa.String(length=32), nullable=True),
        sa.Column("period", sa.String(length=512), nullable=True),
        sa.Column("study_form", sa.String(length=32), nullable=True),
        sa.Column("is_discounted", sa.Boolean(), nullable=False),
        sa.Column("source_kind", sa.String(length=256), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.String(length=256), nullable=True),
        sa.CheckConstraint("amount >= 0", name="ck_admission_tuition_amount"),
        sa.CheckConstraint("length(currency) > 0", name="ck_admission_tuition_currency"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_admission_tuition_sha256"),
        sa.ForeignKeyConstraint(["offering_id"], ["admission_offerings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offering_id", "amount", "is_discounted", "study_form", name="uq_admission_tuition_identity"),
    )
    op.create_index("ix_admission_tuition_offering", "admission_tuition", ["offering_id"])


def downgrade() -> None:
    op.drop_index("ix_admission_tuition_offering", table_name="admission_tuition")
    op.drop_table("admission_tuition")
    op.drop_index("ix_admission_passing_scores_offering", table_name="admission_passing_scores")
    op.drop_table("admission_passing_scores")
    op.drop_index("ix_admission_quotas_offering", table_name="admission_quotas")
    op.drop_table("admission_quotas")
    op.drop_index("ix_admission_exams_offering", table_name="admission_exam_requirements")
    op.drop_table("admission_exam_requirements")
    op.drop_index("ix_admission_offerings_program_year", table_name="admission_offerings")
    op.drop_table("admission_offerings")
