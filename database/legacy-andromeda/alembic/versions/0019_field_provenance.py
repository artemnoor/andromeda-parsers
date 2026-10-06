"""Persist compact program and curriculum provenance summaries."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0019_field_provenance"
down_revision = "0018_ingestion_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("educational_programs", recreate="auto") as batch:
        batch.add_column(sa.Column("provenance_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("source_gaps_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))
    with op.batch_alter_table("curricula", recreate="auto") as batch:
        batch.add_column(sa.Column("provenance_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("source_gaps_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    with op.batch_alter_table("curricula", recreate="auto") as batch:
        batch.drop_column("source_gaps_json")
        batch.drop_column("provenance_json")
    with op.batch_alter_table("educational_programs", recreate="auto") as batch:
        batch.drop_column("source_gaps_json")
        batch.drop_column("provenance_json")
