from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class UserProfileModel(Base):
    """Anonymous current profile snapshot; ORM details stay in infrastructure."""

    __tablename__ = "user_profiles"

    profile_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    session_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    profile_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("session_key_hash", name="uq_user_profiles_session_key_hash"),
        Index("uq_user_profiles_account_id", "account_id", unique=True),
        Index("ix_user_profiles_session_key_hash", "session_key_hash"),
        Index("ix_user_profiles_expiry", "expires_at"),
        CheckConstraint("length(profile_id) > 0", name="ck_user_profiles_profile_id_non_empty"),
        CheckConstraint("length(session_key_hash) = 64", name="ck_user_profiles_session_hash_length"),
        CheckConstraint("revision >= 1", name="ck_user_profiles_revision_positive"),
        CheckConstraint("expires_at > updated_at", name="ck_user_profiles_expiry_after_update"),
    )


__all__ = ["UserProfileModel"]
