"""Add owner-bound DecisionContext persistence."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_decision_context"
down_revision = "0012_neutral_curriculum_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_contexts",
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("owner_key", sa.String(length=320), nullable=False),
        sa.Column("session_key_hash", sa.String(length=64), nullable=True),
        sa.Column("account_id", sa.String(length=128), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(decision_id) > 0", name="ck_decision_contexts_id_non_empty"),
        sa.CheckConstraint("length(owner_key) > 0", name="ck_decision_contexts_owner_key_non_empty"),
        sa.CheckConstraint(
            "account_id IS NOT NULL OR session_key_hash IS NOT NULL",
            name="ck_decision_contexts_owner_reference_present",
        ),
        sa.CheckConstraint(
            "session_key_hash IS NULL OR length(session_key_hash) = 64",
            name="ck_decision_contexts_session_hash_length",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_decision_contexts_revision_positive"),
        sa.CheckConstraint("expires_at > updated_at", name="ck_decision_contexts_expiry_after_update"),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint("owner_key", name="uq_decision_contexts_owner_key"),
    )
    op.create_index("uq_decision_contexts_account_id", "decision_contexts", ["account_id"], unique=True)
    op.create_index("ix_decision_contexts_session_key_hash", "decision_contexts", ["session_key_hash"], unique=False)
    op.create_index("ix_decision_contexts_expiry", "decision_contexts", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_decision_contexts_expiry", table_name="decision_contexts")
    op.drop_index("ix_decision_contexts_session_key_hash", table_name="decision_contexts")
    op.drop_index("uq_decision_contexts_account_id", table_name="decision_contexts")
    op.drop_table("decision_contexts")
