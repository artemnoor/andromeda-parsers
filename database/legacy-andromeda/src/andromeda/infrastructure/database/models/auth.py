from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class AccountModel(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("email", name="uq_accounts_email"),
        CheckConstraint("length(account_id) > 0", name="ck_accounts_id_non_empty"),
        CheckConstraint("length(email) > 2", name="ck_accounts_email_non_empty"),
        CheckConstraint("length(password_hash) > 0", name="ck_accounts_password_hash_non_empty"),
        Index("ix_accounts_email", "email"),
    )


class AuthSessionModel(Base):
    __tablename__ = "auth_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(128), ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        CheckConstraint("length(token_hash) = 64", name="ck_auth_sessions_token_hash_length"),
        CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry_after_creation"),
        Index("ix_auth_sessions_token_hash", "token_hash"),
        Index("ix_auth_sessions_account_id", "account_id"),
        Index("ix_auth_sessions_expiry", "expires_at", "revoked_at"),
    )


__all__ = ["AccountModel", "AuthSessionModel"]
