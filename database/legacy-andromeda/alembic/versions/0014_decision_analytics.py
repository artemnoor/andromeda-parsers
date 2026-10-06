"""Add owner-bound decision analytics events."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0014_decision_analytics"
down_revision = "0013_decision_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_analytics_events",
        sa.Column("owner_key", sa.String(length=320), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("session_key_hash", sa.String(length=64), nullable=True),
        sa.Column("account_id", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(owner_key) > 0", name="ck_decision_analytics_owner_non_empty"),
        sa.CheckConstraint("length(event_id) > 0", name="ck_decision_analytics_event_id_non_empty"),
        sa.CheckConstraint("length(event_type) > 0", name="ck_decision_analytics_type_non_empty"),
        sa.CheckConstraint(
            "(account_id IS NOT NULL AND session_key_hash IS NULL) OR (account_id IS NULL AND session_key_hash IS NOT NULL)",
            name="ck_decision_analytics_owner_binding",
        ),
        sa.CheckConstraint(
            "session_key_hash IS NULL OR length(session_key_hash) = 64",
            name="ck_decision_analytics_session_hash_length",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_decision_analytics_expiry_after_created"),
        sa.PrimaryKeyConstraint("owner_key", "event_id"),
    )
    op.create_index(
        "ix_decision_analytics_owner_type",
        "decision_analytics_events",
        ["owner_key", "event_type"],
        unique=False,
    )
    op.create_index(
        "ix_decision_analytics_owner_occurred",
        "decision_analytics_events",
        ["owner_key", "occurred_at"],
        unique=False,
    )
    op.create_index("ix_decision_analytics_expiry", "decision_analytics_events", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_decision_analytics_expiry", table_name="decision_analytics_events")
    op.drop_index("ix_decision_analytics_owner_occurred", table_name="decision_analytics_events")
    op.drop_index("ix_decision_analytics_owner_type", table_name="decision_analytics_events")
    op.drop_table("decision_analytics_events")
