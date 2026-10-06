"""Persist admission provenance scope metadata."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0020_admission_provenance_scope"
down_revision = "0019_field_provenance"
branch_labels = None
depends_on = None


_TABLES = (
    "admission_offerings",
    "admission_exam_requirements",
    "admission_quotas",
    "admission_passing_scores",
    "admission_tuition",
)


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table, recreate="auto") as batch:
            batch.add_column(sa.Column("university_id", sa.String(length=96), nullable=True))
            batch.add_column(sa.Column("run_id", sa.String(length=96), nullable=True))
            batch.add_column(sa.Column("field", sa.String(length=256), nullable=True))
            batch.add_column(sa.Column("record_key", sa.String(length=256), nullable=True))
            batch.add_column(sa.Column("inferred", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    for table in reversed(_TABLES):
        with op.batch_alter_table(table, recreate="auto") as batch:
            batch.drop_column("inferred")
            batch.drop_column("record_key")
            batch.drop_column("field")
            batch.drop_column("run_id")
            batch.drop_column("university_id")
