"""Persist anonymous current UserProfile snapshots."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_user_profiles"
down_revision = "0004_admissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("profile_id", sa.String(length=96), nullable=False),
        sa.Column("session_key_hash", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=True),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(profile_id) > 0", name="ck_user_profiles_profile_id_non_empty"),
        sa.CheckConstraint("length(session_key_hash) = 64", name="ck_user_profiles_session_hash_length"),
        sa.CheckConstraint("revision >= 1", name="ck_user_profiles_revision_positive"),
        sa.CheckConstraint("expires_at > updated_at", name="ck_user_profiles_expiry_after_update"),
        sa.PrimaryKeyConstraint("profile_id"),
        sa.UniqueConstraint("session_key_hash", name="uq_user_profiles_session_key_hash"),
    )
    op.create_index("ix_user_profiles_session_key_hash", "user_profiles", ["session_key_hash"])


def downgrade() -> None:
    op.drop_index("ix_user_profiles_session_key_hash", table_name="user_profiles")
    op.drop_table("user_profiles")
