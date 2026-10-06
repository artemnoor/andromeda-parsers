"""Persistence model for privacy-safe decision analytics events."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class DecisionAnalyticsEventModel(Base):
    """Owner-bound event row with a composite idempotency key.

    The payload is already validated by the decision contract.  It contains
    only allow-listed values; request bodies and arbitrary metadata are never
    persisted here.
    """

    __tablename__ = "decision_analytics_events"

    owner_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_decision_analytics_owner_type", "owner_key", "event_type"),
        Index("ix_decision_analytics_owner_occurred", "owner_key", "occurred_at"),
        Index("ix_decision_analytics_expiry", "expires_at"),
        CheckConstraint("length(owner_key) > 0", name="ck_decision_analytics_owner_non_empty"),
        CheckConstraint("length(event_id) > 0", name="ck_decision_analytics_event_id_non_empty"),
        CheckConstraint("length(event_type) > 0", name="ck_decision_analytics_type_non_empty"),
        CheckConstraint(
            "(account_id IS NOT NULL AND session_key_hash IS NULL) OR (account_id IS NULL AND session_key_hash IS NOT NULL)",
            name="ck_decision_analytics_owner_binding",
        ),
        CheckConstraint("expires_at > created_at", name="ck_decision_analytics_expiry_after_created"),
    )


__all__ = ["DecisionAnalyticsEventModel"]
