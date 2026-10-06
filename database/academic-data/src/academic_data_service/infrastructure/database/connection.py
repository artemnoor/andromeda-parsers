"""Database engine creation and PostgreSQL 16 identity checks."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from academic_data_service.settings import Settings, SettingsError


def create_service_engine(settings: Settings, **engine_options: Any) -> Engine:
    """Create a service-only engine without logging or exposing its DSN."""
    options: dict[str, Any] = {"pool_pre_ping": True}
    options.update(engine_options)
    return create_engine(settings.database_url, **options)


def verify_server_identity(connection: Connection, settings: Settings) -> dict[str, str | int]:
    """Verify the connected database and PG major version before migrations/writes."""
    if connection.dialect.name != "postgresql":
        if settings.environment == "test" and connection.dialect.name == "sqlite":
            return {
                "database_name": settings.database_name,
                "database_host": settings.database_host or "<local>",
                "server_major": 0,
            }
        raise SettingsError("The academic data database must be PostgreSQL")

    actual_database, version_number = connection.execute(
        text("SELECT current_database(), current_setting('server_version_num')::integer")
    ).one()
    if actual_database != settings.database_name:
        raise SettingsError("Connected database name does not match ACADEMIC_DATA_DATABASE_URL")
    server_major = int(str(version_number)) // 10000
    if server_major != 16:
        raise SettingsError("The academic data service requires PostgreSQL 16")
    return {
        "database_name": str(actual_database),
        "database_host": settings.database_host or "<local>",
        "server_major": server_major,
    }
