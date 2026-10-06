"""Initial service metadata and import/release lifecycle tables.

Revision ID: 0001_initial_service_metadata
Revises:
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_service_metadata"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "service_metadata",
        sa.Column("metadata_key", sa.String(length=128), nullable=False),
        sa.Column("metadata_value", sa.String(length=512), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("metadata_key", name="pk_service_metadata"),
    )
    op.bulk_insert(
        sa.table(
            "service_metadata",
            sa.column("metadata_key", sa.String()),
            sa.column("metadata_value", sa.String()),
        ),
        [{"metadata_key": "schema_version", "metadata_value": "1"}],
    )

    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("mapper_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("row_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.CheckConstraint(
            "status IN ('validated', 'staging', 'committed', 'failed')",
            name="valid_status",
        ),
        sa.CheckConstraint(
            "source_bundle_sha256 ~ '^[0-9a-f]{64}$'",
            name="valid_source_bundle_sha256",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
    )
    op.create_index(
        "ix_import_batches_status_started_at",
        "import_batches",
        ["status", "started_at"],
    )

    op.create_table(
        "data_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_key", sa.String(length=320), nullable=False),
        sa.Column("source_bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("mapper_version", sa.String(length=80), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("schema_revision", sa.String(length=64), nullable=True),
        sa.Column("reconciliation_status", sa.String(length=32), nullable=True),
        sa.Column(
            "reconciliation_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('staging', 'committed', 'failed')",
            name="valid_status",
        ),
        sa.CheckConstraint(
            "source_bundle_sha256 ~ '^[0-9a-f]{64}$'",
            name="valid_source_bundle_sha256",
        ),
        sa.CheckConstraint(
            "reconciliation_status IS NULL OR "
            "reconciliation_status IN ('passed', 'passed_with_gaps')",
            name="valid_reconciliation_status",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.id"],
            ondelete="RESTRICT",
            name="fk_data_releases_batch_id_import_batches",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_data_releases"),
        sa.UniqueConstraint("release_key", name="uq_data_releases_release_key"),
        sa.UniqueConstraint(
            "source_bundle_sha256", "mapper_version", name="uq_data_releases_bundle_mapper"
        ),
    )

    op.create_table(
        "active_data_release",
        sa.Column(
            "slot_key", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("slot_key = 'active'", name="only_active_slot"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["data_releases.id"],
            ondelete="RESTRICT",
            name="fk_active_data_release_release_id_data_releases",
        ),
        sa.PrimaryKeyConstraint("slot_key", name="pk_active_data_release"),
        sa.UniqueConstraint("release_id", name="uq_active_data_release_release_id"),
    )

    op.create_table(
        "migration_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("migration_revision", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=24), nullable=False),
        sa.Column(
            "applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("operation IN ('upgrade')", name="valid_operation"),
        sa.PrimaryKeyConstraint("id", name="pk_migration_audit"),
    )
    op.create_index(
        "ix_migration_audit_revision_applied_at",
        "migration_audit",
        ["migration_revision", "applied_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    active_count = bind.execute(sa.text("SELECT count(*) FROM active_data_release")).scalar_one()
    release_count = bind.execute(sa.text("SELECT count(*) FROM data_releases")).scalar_one()
    batch_count = bind.execute(sa.text("SELECT count(*) FROM import_batches")).scalar_one()
    audit_count = bind.execute(sa.text("SELECT count(*) FROM migration_audit")).scalar_one()
    if active_count or release_count or batch_count or audit_count:
        raise RuntimeError(
            "Refusing to downgrade while import batch or release data exists, or migration audit "
            "data exists; "
            "take a backup and migrate forward."
        )

    op.drop_index("ix_migration_audit_revision_applied_at", table_name="migration_audit")
    op.drop_table("migration_audit")
    op.drop_table("active_data_release")
    op.drop_table("data_releases")
    op.drop_index("ix_import_batches_status_started_at", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_table("service_metadata")
