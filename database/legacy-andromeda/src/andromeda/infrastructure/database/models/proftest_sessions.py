from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class ProftestAnswerSessionModel(Base):
    """Durable resumable session state; the JSON is revalidated at the port."""

    __tablename__ = "proftest_answer_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_key: Mapped[str] = mapped_column(String(320), nullable=False)
    session_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    question_set_version: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    state_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    cursor: Mapped[int] = mapped_column(Integer, nullable=False)
    interaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_proftest_active_owner",
            "owner_key",
            unique=True,
            sqlite_where=text("status = 'draft'"),
            postgresql_where=text("status = 'draft'"),
        ),
        Index("ix_proftest_sessions_owner_status", "owner_key", "status"),
        Index("ix_proftest_sessions_owner_status_updated", "owner_key", "status", "updated_at"),
        Index("ix_proftest_sessions_expiry", "expires_at"),
        CheckConstraint("length(session_id) > 0", name="ck_proftest_session_id_non_empty"),
        CheckConstraint("length(owner_key) > 0", name="ck_proftest_owner_key_non_empty"),
        CheckConstraint("revision >= 1", name="ck_proftest_session_revision_positive"),
        CheckConstraint("cursor >= 0 AND cursor <= 38", name="ck_proftest_session_cursor_bounds"),
        CheckConstraint("interaction_count >= 0 AND interaction_count <= 38", name="ck_proftest_session_interaction_bounds"),
        CheckConstraint("status IN ('draft', 'completed', 'expired', 'abandoned')", name="ck_proftest_session_status"),
        CheckConstraint("expires_at > updated_at", name="ck_proftest_session_expiry_after_update"),
    )


class ProftestAnalyticsEventModel(Base):
    """Allow-listed event envelope; payload never becomes a public profile."""

    __tablename__ = "proftest_analytics_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_key: Mapped[str] = mapped_column(String(320), nullable=False)
    question_set_version: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_proftest_analytics_version_type", "question_set_version", "event_type"),
        Index("ix_proftest_analytics_expiry", "expires_at"),
        CheckConstraint("length(owner_key) > 0", name="ck_proftest_analytics_owner_non_empty"),
        CheckConstraint("length(event_type) > 0", name="ck_proftest_analytics_type_non_empty"),
    )


__all__ = ["ProftestAnalyticsEventModel", "ProftestAnswerSessionModel"]
