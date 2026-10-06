"""Persist pre-publication ingestion quality decisions."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_ingestion_quality_gate"
down_revision = "0016_ingestion_source_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        batch.add_column(sa.Column("quality_status", sa.String(length=32), nullable=False, server_default=sa.text("'not_checked'")))
        batch.add_column(sa.Column("quality_metrics_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("previous_good_run_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("program_ids_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))
        batch.create_check_constraint("ck_ingest_run_quality_status", "quality_status IN ('not_checked', 'passed', 'degraded', 'rejected')")
        batch.create_check_constraint("ck_ingest_run_quality_metrics_json", "length(quality_metrics_json) > 0")


def downgrade() -> None:
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        batch.drop_constraint("ck_ingest_run_quality_metrics_json", type_="check")
        batch.drop_constraint("ck_ingest_run_quality_status", type_="check")
        for name in ("program_ids_json", "previous_good_run_id", "quality_metrics_json", "quality_status"):
            batch.drop_column(name)
