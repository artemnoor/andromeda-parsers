"""Make ingestion retries bounded, traceable, and recoverable."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_ingestion_operations"
down_revision = "0017_ingestion_quality_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        batch.add_column(sa.Column("source_profile", sa.String(length=128), nullable=False, server_default=sa.text("'legacy'")))
        batch.add_column(sa.Column("source_revision", sa.String(length=64), nullable=False, server_default=sa.text("'legacy'")))
        batch.add_column(sa.Column("configuration_version", sa.String(length=64), nullable=False, server_default=sa.text("'legacy'")))
        batch.add_column(sa.Column("retry_of_run_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(length=96), nullable=True))
        batch.create_check_constraint("ck_ingest_run_source_profile", "length(source_profile) > 0")
        batch.create_check_constraint("ck_ingest_run_source_revision", "length(source_revision) > 0")
        batch.create_check_constraint("ck_ingest_run_configuration_version", "length(configuration_version) > 0")
    op.create_index("ix_ingest_runs_source_profile_started_at", "ingest_runs", ["source_profile", "started_at"])
    op.create_index(
        "uq_ingest_runs_single_running",
        "ingest_runs",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "uq_ingest_runs_idempotency_key",
        "ingest_runs",
        ["idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ingest_runs_idempotency_key", table_name="ingest_runs")
    op.drop_index("uq_ingest_runs_single_running", table_name="ingest_runs")
    op.drop_index("ix_ingest_runs_source_profile_started_at", table_name="ingest_runs")
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        for name in (
            "ck_ingest_run_configuration_version",
            "ck_ingest_run_source_revision",
            "ck_ingest_run_source_profile",
        ):
            batch.drop_constraint(name, type_="check")
        for name in ("idempotency_key", "retry_of_run_id", "configuration_version", "source_revision", "source_profile"):
            batch.drop_column(name)
