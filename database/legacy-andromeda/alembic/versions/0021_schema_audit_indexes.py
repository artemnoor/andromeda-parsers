"""Add measured lifecycle and reverse-lookup indexes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0021_schema_audit_indexes"
down_revision = "0020_admission_provenance_scope"
branch_labels = None
depends_on = None


_INDEXES = (
    ("auth_sessions", "ix_auth_sessions_expiry", ("expires_at", "revoked_at")),
    ("user_profiles", "ix_user_profiles_expiry", ("expires_at",)),
    ("proftest_answer_sessions", "ix_proftest_sessions_owner_status_updated", ("owner_key", "status", "updated_at")),
    ("event_university_links", "ix_event_university_links_university_id", ("university_id",)),
    ("event_department_links", "ix_event_department_links_department_id", ("department_id",)),
    ("ingest_runs", "ix_ingest_runs_status_started_at", ("status", "started_at")),
    ("source_snapshots", "ix_source_snapshots_ingest_run_id", ("ingest_run_id",)),
    ("raw_source_records", "ix_raw_source_records_snapshot_hash", ("snapshot_sha256",)),
)


def upgrade() -> None:
    for table, name, columns in _INDEXES:
        op.create_index(name, table, list(columns))


def downgrade() -> None:
    for table, name, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
