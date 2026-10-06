"""Persist route-aware admission passing scores and BVI facts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_admission_passing_route"
down_revision = "0009_auth_profile_binding"
branch_labels = None
depends_on = None


_TABLE = "admission_passing_scores"
_OLD_UNIQUE = "uq_admission_passing_score_identity"
_NEW_UNIQUE = "uq_admission_passing_score_identity"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        # SQLite's recreate path does not apply a server default when the
        # default is removed in the same batch. Add nullable columns first so
        # historical rows can be copied safely on both supported dialects.
        batch.add_column(sa.Column("competition_type", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=16), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE admission_passing_scores SET competition_type = 'general', status = 'numeric' "
            "WHERE competition_type IS NULL OR status IS NULL"
        )
    )

    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        batch.alter_column("competition_type", existing_type=sa.String(length=32), nullable=False)
        batch.alter_column("status", existing_type=sa.String(length=16), nullable=False)
        batch.alter_column("score", existing_type=sa.Numeric(precision=6, scale=2), nullable=True)
        batch.drop_constraint(_OLD_UNIQUE, type_="unique")
        batch.create_unique_constraint(
            _NEW_UNIQUE,
            ["offering_id", "competition_type", "status", "score_type"],
        )
        batch.create_check_constraint(
            "ck_admission_passing_score_competition_type",
            "competition_type IN ('general', 'special_quota', 'separate_quota', 'targeted', 'bvi', 'other')",
        )
        batch.create_check_constraint(
            "ck_admission_passing_score_status",
            "status IN ('numeric', 'bvi')",
        )
        batch.create_check_constraint(
            "ck_admission_passing_score_status_value",
            "(status = 'numeric' AND score IS NOT NULL) OR "
            "(status = 'bvi' AND score IS NULL AND competition_type IN "
            "('bvi', 'special_quota', 'separate_quota', 'targeted'))",
        )


def downgrade() -> None:
    bind = op.get_bind()
    bvi_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM admission_passing_scores WHERE status = 'bvi'")
    ).scalar_one()
    if bvi_count:
        raise RuntimeError("Cannot downgrade route-aware passing scores while BVI facts exist")
    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        batch.drop_constraint("ck_admission_passing_score_status_value", type_="check")
        batch.drop_constraint("ck_admission_passing_score_status", type_="check")
        batch.drop_constraint("ck_admission_passing_score_competition_type", type_="check")
        batch.drop_constraint(_NEW_UNIQUE, type_="unique")
        batch.alter_column("score", existing_type=sa.Numeric(precision=6, scale=2), nullable=False)
        batch.drop_column("status")
        batch.drop_column("competition_type")
        batch.create_unique_constraint(_OLD_UNIQUE, ["offering_id", "score_type"])
