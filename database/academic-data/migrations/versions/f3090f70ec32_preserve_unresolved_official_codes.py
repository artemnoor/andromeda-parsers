"""preserve source codes when canonical catalog links are unresolved

Revision ID: f3090f70ec32
Revises: db957c691c30
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3090f70ec32"
down_revision: str | None = "db957c691c30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in (
        "program_offerings",
        "competition_pools",
        "admission_requirement_sets",
        "historical_admission_statistics",
        "admission_statistics",
    ):
        op.add_column(table, sa.Column("direction_code", sa.String(length=32), nullable=True))

    for table in ("program_offerings", "competition_pools", "historical_admission_statistics"):
        op.add_column(table, sa.Column("department_code", sa.String(length=80), nullable=True))


def downgrade() -> None:
    for table in ("historical_admission_statistics", "competition_pools", "program_offerings"):
        op.drop_column(table, "department_code")

    for table in (
        "admission_statistics",
        "historical_admission_statistics",
        "admission_requirement_sets",
        "competition_pools",
        "program_offerings",
    ):
        op.drop_column(table, "direction_code")
