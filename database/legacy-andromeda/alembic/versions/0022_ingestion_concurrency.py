"""Scope ingestion concurrency and persist recoverable run state."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0022_ingestion_concurrency"
down_revision = "0021_schema_audit_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0018 introduced a global running-run index. It is intentionally replaced
    # by a scoped identity index below; changing an applied migration would
    # leave existing deployments with a different schema history.
    op.drop_index("uq_ingest_runs_single_running", table_name="ingest_runs")
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        batch.add_column(
            sa.Column("projection_target", sa.String(length=64), nullable=False, server_default=sa.text("'canonical'"))
        )
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("projection_status", sa.String(length=32), nullable=False, server_default=sa.text("'not_started'"))
        )
        batch.add_column(sa.Column("recovery_reason", sa.String(length=128), nullable=True))
        batch.create_check_constraint("ck_ingest_run_university_id", "length(university_id) > 0")
        batch.create_check_constraint("ck_ingest_run_projection_target", "length(projection_target) > 0")
        batch.create_check_constraint(
            "ck_ingest_run_projection_status",
            "projection_status IN ('not_started', 'running', 'committed', 'reconciled', 'failed')",
        )

    op.execute(
        sa.text("UPDATE ingest_runs SET university_id = 'university:legacy' WHERE university_id IS NULL")
    )
    op.execute(sa.text("UPDATE ingest_runs SET heartbeat_at = started_at WHERE heartbeat_at IS NULL"))
    op.execute(
        sa.text(
            "UPDATE ingest_runs "
            "SET projection_status = CASE "
            "WHEN status = 'completed' THEN 'reconciled' "
            "WHEN status = 'failed' THEN 'failed' "
            "ELSE 'not_started' END"
        )
    )

    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        batch.alter_column("university_id", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("heartbeat_at", existing_type=sa.DateTime(timezone=True), nullable=False)

    op.create_index(
        "uq_ingest_runs_active_identity",
        "ingest_runs",
        ["university_id", "source_profile", "projection_target"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    active_count = int(
        bind.execute(sa.text("SELECT COUNT(*) FROM ingest_runs WHERE status = 'running'")).scalar_one()
    )
    if active_count > 1:
        raise RuntimeError("cannot downgrade ingestion concurrency while multiple runs are active")

    op.drop_index("uq_ingest_runs_active_identity", table_name="ingest_runs")
    op.create_index(
        "uq_ingest_runs_single_running",
        "ingest_runs",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )
    with op.batch_alter_table("ingest_runs", recreate="auto") as batch:
        batch.drop_constraint("ck_ingest_run_projection_status", type_="check")
        batch.drop_constraint("ck_ingest_run_projection_target", type_="check")
        batch.drop_constraint("ck_ingest_run_university_id", type_="check")
        batch.alter_column("university_id", existing_type=sa.String(length=64), nullable=True)
        batch.drop_column("recovery_reason")
        batch.drop_column("projection_status")
        batch.drop_column("heartbeat_at")
        batch.drop_column("projection_target")
