"""add typed provenance bridges for admissions lookups

Revision ID: db957c691c30
Revises: c81b2907f4a1
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "db957c691c30"
down_revision: str | None = "c81b2907f4a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_bridge(name: str, target_field: str, target_table: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("external_key", sa.String(length=512), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column(target_field, sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id", "evidence_id"],
            ["source_evidence.release_id", "source_evidence.id"],
            name=f"fk_{name}_evidence_release",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_id", target_field],
            [f"{target_table}.release_id", f"{target_table}.id"],
            name=f"fk_{name}_target_release",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["data_releases.id"],
            name=f"fk_{name}_release_id_data_releases",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{name}"),
        sa.UniqueConstraint(
            "release_id", "evidence_id", target_field, name=f"uq_{name}_evidence_target"
        ),
        sa.UniqueConstraint("release_id", "external_key", name=f"uq_{name}_release_external_key"),
        sa.UniqueConstraint("release_id", "id", name=f"uq_{name}_release_id"),
    )
    op.create_index(f"ix_{name}_release_target", name, ["release_id", target_field])


def upgrade() -> None:
    _create_bridge("exam_evidence", "exam_id", "admission_exams")
    _create_bridge("funding_type_evidence", "funding_type_id", "funding_types")
    _create_bridge("quota_type_evidence", "quota_type_id", "quota_types")


def downgrade() -> None:
    for name in ("quota_type_evidence", "funding_type_evidence", "exam_evidence"):
        op.drop_index(f"ix_{name}_release_target", table_name=name)
        op.drop_table(name)
