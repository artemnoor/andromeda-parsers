"""Track bounded source-health and drift metadata for ingestion runs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0016_ingestion_source_health"
down_revision = "0015_university_scoped_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        batch.add_column(sa.Column("university_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("duration_ms", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_gap_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("critical_gap_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("drift_status", sa.String(length=32), nullable=False, server_default=sa.text("'not_checked'")))
        batch.create_check_constraint("ck_ingest_run_duration_ms", "duration_ms IS NULL OR duration_ms >= 0")
        batch.create_check_constraint("ck_ingest_run_source_gap_count", "source_gap_count >= 0")
        batch.create_check_constraint("ck_ingest_run_critical_gap_count", "critical_gap_count >= 0")
        batch.create_check_constraint("ck_ingest_run_drift_status", "drift_status IN ('not_checked', 'passed', 'rejected')")


def downgrade() -> None:
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        for name in (
            "ck_ingest_run_drift_status",
            "ck_ingest_run_critical_gap_count",
            "ck_ingest_run_source_gap_count",
            "ck_ingest_run_duration_ms",
        ):
            batch.drop_constraint(name, type_="check")
        for name in ("drift_status", "critical_gap_count", "source_gap_count", "duration_ms", "university_id"):
            batch.drop_column(name)
