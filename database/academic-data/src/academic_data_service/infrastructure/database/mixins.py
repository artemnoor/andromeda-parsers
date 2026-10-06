"""Common release-scoped identity columns for imported source records."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class ReleaseScopedMixin:
    """Internal UUID plus stable source key, always owned by one release."""

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("data_releases.id", ondelete="CASCADE"), nullable=False
    )
    external_key: Mapped[str] = mapped_column(String(512), nullable=False)


class TemporalAssertionMixin:
    """Independent source-valid, observed, and database-ingested times."""

    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def release_scoped_constraints(
    table_name: str, *additional_constraints: object
) -> tuple[object, ...]:
    """Return reusable uniqueness constraints and table-specific constraints."""

    return (
        UniqueConstraint(
            "release_id",
            "external_key",
            name=f"uq_{table_name}_release_external_key",
        ),
        UniqueConstraint("release_id", "id", name=f"uq_{table_name}_release_id"),
        *additional_constraints,
    )
