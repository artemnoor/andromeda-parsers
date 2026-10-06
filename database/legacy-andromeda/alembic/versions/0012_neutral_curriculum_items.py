"""Remove curriculum category labels from the canonical model."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0012_neutral_curriculum_items"
down_revision = "0011_proftest_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("curriculum_items")}
    if "subject_group" not in columns:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("curriculum_items", recreate="always") as batch:
            batch.drop_column("subject_group")
        return
    op.drop_column("curriculum_items", "subject_group")


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("curriculum_items")}
    if "subject_group" in columns:
        return
    op.add_column("curriculum_items", sa.Column("subject_group", sa.String(length=256), nullable=True))
