"""Add source-backed university events and venue projections."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_events"
down_revision = "0005_user_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "venues",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("source_kind", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.String(length=256), nullable=True),
        sa.CheckConstraint("id LIKE 'venue:%:%'", name="ck_venues_id_shape"),
        sa.CheckConstraint("length(name) > 0", name="ck_venues_name_non_empty"),
        sa.CheckConstraint("address IS NULL OR length(address) > 0", name="ck_venues_address_non_empty"),
        sa.CheckConstraint("latitude IS NULL OR (latitude >= -90 AND latitude <= 90)", name="ck_venues_latitude_range"),
        sa.CheckConstraint("longitude IS NULL OR (longitude >= -180 AND longitude <= 180)", name="ck_venues_longitude_range"),
        sa.CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="ck_venues_coordinate_pair"),
        sa.CheckConstraint("length(source_kind) > 0", name="ck_venues_source_kind_non_empty"),
        sa.CheckConstraint("length(source_url) > 0", name="ck_venues_source_url_non_empty"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_venues_sha256_length"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=256), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("registration_url", sa.Text(), nullable=True),
        sa.Column("venue_id", sa.String(length=128), nullable=True),
        sa.Column("source_kind", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.String(length=256), nullable=True),
        sa.CheckConstraint("id LIKE 'event:%:%'", name="ck_events_id_shape"),
        sa.CheckConstraint("length(title) > 0", name="ck_events_title_non_empty"),
        sa.CheckConstraint("kind IN ('additional_education', 'open_day', 'lecture', 'competition', 'career', 'other')", name="ck_events_kind"),
        sa.CheckConstraint("format IN ('offline', 'online', 'hybrid')", name="ck_events_format"),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_events_time_window"),
        sa.CheckConstraint("description IS NULL OR length(description) > 0", name="ck_events_description_non_empty"),
        sa.CheckConstraint("registration_url IS NULL OR length(registration_url) > 0", name="ck_events_registration_url_non_empty"),
        sa.CheckConstraint("length(source_kind) > 0", name="ck_events_source_kind_non_empty"),
        sa.CheckConstraint("length(source_url) > 0", name="ck_events_source_url_non_empty"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_events_sha256_length"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_kind", "source_url", "id", name="uq_events_source_identity"),
    )
    op.create_index("ix_events_starts_at", "events", ["starts_at"])
    op.create_index("ix_events_kind_format", "events", ["kind", "format"])
    op.create_table(
        "event_university_links",
        sa.Column("event_id", sa.String(length=256), nullable=False),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"]),
        sa.PrimaryKeyConstraint("event_id", "university_id"),
    )
    op.create_table(
        "event_department_links",
        sa.Column("event_id", sa.String(length=256), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.CheckConstraint("department_id LIKE 'department:%:%'", name="ck_event_departments_id_shape"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id", "department_id"),
    )
    op.create_table(
        "event_program_links",
        sa.Column("event_id", sa.String(length=256), nullable=False),
        sa.Column("program_id", sa.String(length=96), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["educational_programs.id"]),
        sa.PrimaryKeyConstraint("event_id", "program_id"),
    )
    op.create_index("ix_event_program_links_program_id", "event_program_links", ["program_id"])


def downgrade() -> None:
    op.drop_index("ix_event_program_links_program_id", table_name="event_program_links")
    op.drop_table("event_program_links")
    op.drop_table("event_department_links")
    op.drop_table("event_university_links")
    op.drop_index("ix_events_kind_format", table_name="events")
    op.drop_index("ix_events_starts_at", table_name="events")
    op.drop_table("events")
    op.drop_table("venues")
