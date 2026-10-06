"""Persist bounded ingestion quality metadata for Admin/Ops reads."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_admin_ops_ingest_audit"
down_revision = "0007_campus_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        batch.add_column(sa.Column("error_code", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("error_message", sa.String(length=512), nullable=True))
        for name in (
            "source_count",
            "program_count",
            "curriculum_item_count",
            "event_count",
            "campus_point_count",
            "inserted_count",
            "updated_count",
            "unchanged_count",
            "removed_count",
        ):
            batch.add_column(sa.Column(name, sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("source_hashes_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("source_kinds_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))
        batch.create_check_constraint("ck_ingest_run_status", "status IN ('running', 'completed', 'failed')")
        for name in (
            "source_count",
            "program_count",
            "curriculum_item_count",
            "event_count",
            "campus_point_count",
            "inserted_count",
            "updated_count",
            "unchanged_count",
            "removed_count",
        ):
            batch.create_check_constraint(f"ck_ingest_run_{name}", f"{name} >= 0")


def downgrade() -> None:
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        batch.drop_constraint("ck_ingest_run_status", type_="check")
        for name in (
            "source_count",
            "program_count",
            "curriculum_item_count",
            "event_count",
            "campus_point_count",
            "inserted_count",
            "updated_count",
            "unchanged_count",
            "removed_count",
        ):
            batch.drop_constraint(f"ck_ingest_run_{name}", type_="check")
        for name in (
            "source_kinds_json",
            "source_hashes_json",
            "removed_count",
            "unchanged_count",
            "updated_count",
            "inserted_count",
            "campus_point_count",
            "event_count",
            "curriculum_item_count",
            "program_count",
            "source_count",
            "error_message",
            "error_code",
        ):
            batch.drop_column(name)
