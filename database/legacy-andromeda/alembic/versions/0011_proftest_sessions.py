"""Add resumable proftest sessions and bounded analytics events."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0011_proftest_sessions"
down_revision = "0010_admission_passing_route"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proftest_answer_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("owner_key", sa.String(length=320), nullable=False),
        sa.Column("session_key_hash", sa.String(length=64), nullable=True),
        sa.Column("account_id", sa.String(length=128), nullable=True),
        sa.Column("question_set_version", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("interaction_count", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(session_id) > 0", name="ck_proftest_session_id_non_empty"),
        sa.CheckConstraint("length(owner_key) > 0", name="ck_proftest_owner_key_non_empty"),
        sa.CheckConstraint("revision >= 1", name="ck_proftest_session_revision_positive"),
        sa.CheckConstraint("cursor >= 0 AND cursor <= 38", name="ck_proftest_session_cursor_bounds"),
        sa.CheckConstraint("interaction_count >= 0 AND interaction_count <= 38", name="ck_proftest_session_interaction_bounds"),
        sa.CheckConstraint("status IN ('draft', 'completed', 'expired', 'abandoned')", name="ck_proftest_session_status"),
        sa.CheckConstraint("expires_at > updated_at", name="ck_proftest_session_expiry_after_update"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "uq_proftest_active_owner",
        "proftest_answer_sessions",
        ["owner_key"],
        unique=True,
        sqlite_where=sa.text("status = 'draft'"),
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_index("ix_proftest_sessions_owner_status", "proftest_answer_sessions", ["owner_key", "status"])
    op.create_index("ix_proftest_sessions_expiry", "proftest_answer_sessions", ["expires_at"])

    op.create_table(
        "proftest_analytics_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("owner_key", sa.String(length=320), nullable=False),
        sa.Column("question_set_version", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(owner_key) > 0", name="ck_proftest_analytics_owner_non_empty"),
        sa.CheckConstraint("length(event_type) > 0", name="ck_proftest_analytics_type_non_empty"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_proftest_analytics_version_type", "proftest_analytics_events", ["question_set_version", "event_type"])
    op.create_index("ix_proftest_analytics_expiry", "proftest_analytics_events", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_proftest_analytics_expiry", table_name="proftest_analytics_events")
    op.drop_index("ix_proftest_analytics_version_type", table_name="proftest_analytics_events")
    op.drop_table("proftest_analytics_events")
    op.drop_index("ix_proftest_sessions_expiry", table_name="proftest_answer_sessions")
    op.drop_index("ix_proftest_sessions_owner_status", table_name="proftest_answer_sessions")
    op.drop_index("uq_proftest_active_owner", table_name="proftest_answer_sessions")
    op.drop_table("proftest_answer_sessions")
