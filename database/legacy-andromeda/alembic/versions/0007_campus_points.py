"""Add typed campus point metadata and canonical link projections."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_campus_points"
down_revision = "0006_events"
branch_labels = None
depends_on = None

POINT_TYPE_CHECK = "point_type IN ('building', 'room_zone', 'event_venue', 'entrance', 'other')"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite cannot add a CHECK constraint in place. Batch recreation also
        # backfills all pre-existing event venues deterministically.
        with op.batch_alter_table("venues", recreate="always") as batch:
            batch.add_column(sa.Column("point_type", sa.String(length=32), nullable=False, server_default="event_venue"))
            batch.create_check_constraint("ck_venues_point_type", POINT_TYPE_CHECK)
    else:
        op.add_column("venues", sa.Column("point_type", sa.String(length=32), nullable=False, server_default="event_venue"))
        op.create_check_constraint("ck_venues_point_type", "venues", POINT_TYPE_CHECK)
        op.alter_column("venues", "point_type", existing_type=sa.String(length=32), server_default=None)

    op.create_table(
        "venue_university_links",
        sa.Column("venue_id", sa.String(length=128), nullable=False),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"]),
        sa.PrimaryKeyConstraint("venue_id", "university_id"),
    )
    op.create_index("ix_venue_university_links_university_id", "venue_university_links", ["university_id"])
    op.create_table(
        "venue_department_links",
        sa.Column("venue_id", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.CheckConstraint("department_id LIKE 'department:%:%'", name="ck_venue_departments_id_shape"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("venue_id", "department_id"),
    )
    op.create_index("ix_venue_department_links_department_id", "venue_department_links", ["department_id"])
    op.create_table(
        "venue_program_links",
        sa.Column("venue_id", sa.String(length=128), nullable=False),
        sa.Column("program_id", sa.String(length=96), nullable=False),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["educational_programs.id"]),
        sa.PrimaryKeyConstraint("venue_id", "program_id"),
    )
    op.create_index("ix_venue_program_links_program_id", "venue_program_links", ["program_id"])


def downgrade() -> None:
    op.drop_index("ix_venue_program_links_program_id", table_name="venue_program_links")
    op.drop_table("venue_program_links")
    op.drop_index("ix_venue_department_links_department_id", table_name="venue_department_links")
    op.drop_table("venue_department_links")
    op.drop_index("ix_venue_university_links_university_id", table_name="venue_university_links")
    op.drop_table("venue_university_links")
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("venues", recreate="always") as batch:
            batch.drop_constraint("ck_venues_point_type", type_="check")
            batch.drop_column("point_type")
    else:
        op.drop_constraint("ck_venues_point_type", "venues", type_="check")
        op.drop_column("venues", "point_type")
