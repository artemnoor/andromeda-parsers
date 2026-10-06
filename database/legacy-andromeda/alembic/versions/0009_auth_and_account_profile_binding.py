"""Add accounts, server-side sessions, and account-owned profiles."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_auth_profile_binding"
down_revision = "0008_admin_ops_ingest_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(account_id) > 0", name="ck_accounts_id_non_empty"),
        sa.CheckConstraint("length(email) > 2", name="ck_accounts_email_non_empty"),
        sa.CheckConstraint("length(password_hash) > 0", name="ck_accounts_password_hash_non_empty"),
        sa.PrimaryKeyConstraint("account_id"),
        sa.UniqueConstraint("email", name="uq_accounts_email"),
    )
    op.create_index("ix_accounts_email", "accounts", ["email"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_auth_sessions_token_hash_length"),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry_after_creation"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=False)
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"], unique=False)
    with op.batch_alter_table("user_profiles", recreate="always") as batch:
        batch.alter_column("session_key_hash", existing_type=sa.String(length=64), nullable=True)
    op.create_index("uq_user_profiles_account_id", "user_profiles", ["account_id"], unique=True)


def downgrade() -> None:
    user_profiles = sa.table("user_profiles", sa.column("account_id"))
    bound_count = op.get_bind().execute(
        sa.select(sa.func.count()).select_from(user_profiles).where(user_profiles.c.account_id.is_not(None))
    ).scalar_one()
    if bound_count:
        raise RuntimeError("Cannot downgrade auth profile binding while account-owned profiles exist")
    op.drop_index("uq_user_profiles_account_id", table_name="user_profiles")
    with op.batch_alter_table("user_profiles", recreate="always") as batch:
        batch.alter_column("session_key_hash", existing_type=sa.String(length=64), nullable=False)
    op.drop_index("ix_auth_sessions_account_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_accounts_email", table_name="accounts")
    op.drop_table("accounts")
