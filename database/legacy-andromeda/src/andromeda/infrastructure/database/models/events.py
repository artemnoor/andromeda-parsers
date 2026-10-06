from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class VenueModel(Base):
    __tablename__ = "venues"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    point_type: Mapped[str] = mapped_column(String(32), nullable=False, default="event_venue")
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        CheckConstraint("id LIKE 'venue:%:%'", name="ck_venues_id_shape"),
        CheckConstraint("point_type IN ('building', 'room_zone', 'event_venue', 'entrance', 'other')", name="ck_venues_point_type"),
        CheckConstraint("length(name) > 0", name="ck_venues_name_non_empty"),
        CheckConstraint("address IS NULL OR length(address) > 0", name="ck_venues_address_non_empty"),
        CheckConstraint("latitude IS NULL OR (latitude >= -90 AND latitude <= 90)", name="ck_venues_latitude_range"),
        CheckConstraint("longitude IS NULL OR (longitude >= -180 AND longitude <= 180)", name="ck_venues_longitude_range"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="ck_venues_coordinate_pair"),
        CheckConstraint("length(source_kind) > 0", name="ck_venues_source_kind_non_empty"),
        CheckConstraint("length(source_url) > 0", name="ck_venues_source_url_non_empty"),
        CheckConstraint("length(content_sha256) = 64", name="ck_venues_sha256_length"),
    )


class EventModel(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_id: Mapped[str | None] = mapped_column(ForeignKey("venues.id"), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        CheckConstraint("id LIKE 'event:%:%'", name="ck_events_id_shape"),
        CheckConstraint("length(title) > 0", name="ck_events_title_non_empty"),
        CheckConstraint("kind IN ('additional_education', 'open_day', 'lecture', 'competition', 'career', 'other')", name="ck_events_kind"),
        CheckConstraint("format IN ('offline', 'online', 'hybrid')", name="ck_events_format"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_events_time_window"),
        CheckConstraint("description IS NULL OR length(description) > 0", name="ck_events_description_non_empty"),
        CheckConstraint("registration_url IS NULL OR length(registration_url) > 0", name="ck_events_registration_url_non_empty"),
        CheckConstraint("length(source_kind) > 0", name="ck_events_source_kind_non_empty"),
        CheckConstraint("length(source_url) > 0", name="ck_events_source_url_non_empty"),
        CheckConstraint("length(content_sha256) = 64", name="ck_events_sha256_length"),
        Index("ix_events_starts_at", "starts_at"),
        Index("ix_events_kind_format", "kind", "format"),
        UniqueConstraint("source_kind", "source_url", "id", name="uq_events_source_identity"),
    )


class EventUniversityLinkModel(Base):
    __tablename__ = "event_university_links"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), primary_key=True)

    __table_args__ = (Index("ix_event_university_links_university_id", "university_id"),)


class EventDepartmentLinkModel(Base):
    __tablename__ = "event_department_links"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    department_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    __table_args__ = (
        CheckConstraint("department_id LIKE 'department:%:%'", name="ck_event_departments_id_shape"),
        Index("ix_event_department_links_department_id", "department_id"),
    )


class EventProgramLinkModel(Base):
    __tablename__ = "event_program_links"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    program_id: Mapped[str] = mapped_column(ForeignKey("educational_programs.id"), primary_key=True)

    __table_args__ = (
        Index("ix_event_program_links_program_id", "program_id"),
    )


class VenueUniversityLinkModel(Base):
    __tablename__ = "venue_university_links"

    venue_id: Mapped[str] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), primary_key=True)
    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), primary_key=True)

    __table_args__ = (Index("ix_venue_university_links_university_id", "university_id"),)


class VenueDepartmentLinkModel(Base):
    __tablename__ = "venue_department_links"

    venue_id: Mapped[str] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), primary_key=True)
    department_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    __table_args__ = (
        CheckConstraint("department_id LIKE 'department:%:%'", name="ck_venue_departments_id_shape"),
        Index("ix_venue_department_links_department_id", "department_id"),
    )


class VenueProgramLinkModel(Base):
    __tablename__ = "venue_program_links"

    venue_id: Mapped[str] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), primary_key=True)
    program_id: Mapped[str] = mapped_column(ForeignKey("educational_programs.id"), primary_key=True)

    __table_args__ = (Index("ix_venue_program_links_program_id", "program_id"),)


__all__ = [
    "EventDepartmentLinkModel",
    "EventModel",
    "EventProgramLinkModel",
    "EventUniversityLinkModel",
    "VenueModel",
    "VenueDepartmentLinkModel",
    "VenueProgramLinkModel",
    "VenueUniversityLinkModel",
]
