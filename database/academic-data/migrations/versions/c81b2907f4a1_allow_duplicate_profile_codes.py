"""allow distinct source profiles to share an official code

Revision ID: c81b2907f4a1
Revises: a0337fe46f54
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c81b2907f4a1"
down_revision: str | None = "a0337fe46f54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_programs_direction_code", "educational_programs", type_="unique")


def downgrade() -> None:
    connection = op.get_bind()
    has_duplicates = connection.execute(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM educational_programs "
            "GROUP BY release_id, direction_id, code HAVING COUNT(*) > 1"
            ")"
        )
    ).scalar_one()
    if has_duplicates:
        raise RuntimeError(
            "Cannot restore uq_programs_direction_code: imported releases contain "
            "distinct profiles sharing a source code"
        )
    op.create_unique_constraint(
        "uq_programs_direction_code",
        "educational_programs",
        ["release_id", "direction_id", "code"],
    )
