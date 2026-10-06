"""Helpers for checking this service's independent Alembic version table."""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text

VERSION_TABLE = "academic_data_alembic_version"
SERVICE_SCHEMA_HEAD = "de41afbb52c8"


def current_schema_revision(engine: Engine) -> str | None:
    inspector = inspect(engine)
    if not inspector.has_table(VERSION_TABLE):
        return None
    with engine.connect() as connection:
        return connection.execute(
            text(f"SELECT version_num FROM {VERSION_TABLE} LIMIT 1")
        ).scalar_one_or_none()
