"""Prevent the active-release pointer from referencing unreconciled data.

Revision ID: a7d2c91e4f60
Revises: f3090f70ec32
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d2c91e4f60"
down_revision: str | None = "f3090f70ec32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION academic_data_guard_active_release_state()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_release_id uuid;
        BEGIN
            IF TG_TABLE_NAME = 'active_data_release' THEN
                target_release_id := NEW.release_id;
                IF NOT EXISTS (
                    SELECT 1
                    FROM data_releases AS release
                    WHERE release.id = target_release_id
                      AND release.status = 'committed'
                      AND release.reconciliation_status IN ('passed', 'passed_with_gaps')
                ) THEN
                    RAISE EXCEPTION 'Active data release must be committed and reconciled'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_active_data_release_reconciled';
                END IF;
            ELSIF TG_TABLE_NAME = 'data_releases' THEN
                IF EXISTS (
                    SELECT 1
                    FROM active_data_release AS active
                    WHERE active.release_id = OLD.id
                ) AND (
                    NEW.status IS DISTINCT FROM 'committed'
                    OR (
                        NEW.reconciliation_status IS DISTINCT FROM 'passed'
                        AND NEW.reconciliation_status IS DISTINCT FROM 'passed_with_gaps'
                    )
                ) THEN
                    RAISE EXCEPTION 'An active data release cannot become unreconciled'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_active_data_release_reconciled';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_active_release_must_be_reconciled
        BEFORE INSERT OR UPDATE OF release_id ON active_data_release
        FOR EACH ROW EXECUTE FUNCTION academic_data_guard_active_release_state()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_active_release_cannot_be_invalidated
        BEFORE UPDATE OF status, reconciliation_status ON data_releases
        FOR EACH ROW EXECUTE FUNCTION academic_data_guard_active_release_state()
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    release_count = connection.execute(sa.text("SELECT count(*) FROM data_releases")).scalar_one()
    batch_count = connection.execute(sa.text("SELECT count(*) FROM import_batches")).scalar_one()
    if release_count or batch_count:
        raise RuntimeError("Refusing to downgrade while import batch or release data exists")

    op.execute("DROP TRIGGER IF EXISTS trg_active_release_cannot_be_invalidated ON data_releases")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_active_release_must_be_reconciled ON active_data_release"
    )
    op.execute("DROP FUNCTION IF EXISTS academic_data_guard_active_release_state()")
