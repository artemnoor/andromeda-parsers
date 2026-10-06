from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class DecisionContextModel(Base):
    """Owner-bound explicit choice state; profile preferences are not duplicated."""

    __tablename__ = "decision_contexts"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_key: Mapped[str] = mapped_column(String(320), nullable=False)
    session_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_key", name="uq_decision_contexts_owner_key"),
        Index("uq_decision_contexts_account_id", "account_id", unique=True),
        Index("ix_decision_contexts_session_key_hash", "session_key_hash"),
        Index("ix_decision_contexts_expiry", "expires_at"),
        CheckConstraint("length(decision_id) > 0", name="ck_decision_contexts_id_non_empty"),
        CheckConstraint("length(owner_key) > 0", name="ck_decision_contexts_owner_key_non_empty"),
        CheckConstraint(
            "account_id IS NOT NULL OR session_key_hash IS NOT NULL",
            name="ck_decision_contexts_owner_reference_present",
        ),
        CheckConstraint(
            "session_key_hash IS NULL OR length(session_key_hash) = 64",
            name="ck_decision_contexts_session_hash_length",
        ),
        CheckConstraint("revision >= 1", name="ck_decision_contexts_revision_positive"),
        CheckConstraint("expires_at > updated_at", name="ck_decision_contexts_expiry_after_update"),
    )


__all__ = ["DecisionContextModel"]
