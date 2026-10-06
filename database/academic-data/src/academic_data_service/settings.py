"""Fail-closed service configuration and database-target validation."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy.engine import URL, make_url

SERVICE_DATABASE_NAME = "academic_data_2026"
FORBIDDEN_DATABASE_NAMES = frozenset(
    {
        "andromeda_dev",
        "andromeda_staging",
        "andromeda_prod",
        "bmstu_archive_2026",
    }
)
ALLOWED_ENVIRONMENTS = frozenset({"development", "test", "staging", "production"})


class SettingsError(ValueError):
    """Raised when service configuration is missing or unsafe."""


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = field(repr=False)
    environment: str
    database_name: str
    database_host: str | None
    log_level: str = "INFO"
    root_path: str = ""
    db_pool_size: int = 2
    db_max_overflow: int = 1
    db_pool_timeout_seconds: int = 3
    db_connect_timeout_seconds: int = 3
    db_statement_timeout_ms: int = 5000
    request_timeout_seconds: int = 15

    @property
    def parsed_database_url(self) -> URL:
        return make_url(self.database_url)


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load settings without consulting core database variables as fallbacks."""
    source = os.environ if environ is None else environ
    raw_url = source.get("ACADEMIC_DATA_DATABASE_URL", "").strip()
    if not raw_url:
        raise SettingsError("ACADEMIC_DATA_DATABASE_URL is required")

    environment = source.get("ACADEMIC_DATA_ENV", "development").strip().lower()
    if environment not in ALLOWED_ENVIRONMENTS:
        raise SettingsError("ACADEMIC_DATA_ENV must be development, test, staging, or production")

    try:
        parsed_url = make_url(raw_url)
    except Exception as error:
        raise SettingsError("ACADEMIC_DATA_DATABASE_URL is not a valid SQLAlchemy URL") from error

    database_name = parsed_url.database or ""
    if not database_name:
        raise SettingsError("ACADEMIC_DATA_DATABASE_URL must name a database")
    validate_database_target(parsed_url, database_name, environment)

    configured_level = source.get("LOG_LEVEL", "INFO").strip().upper()
    if configured_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise SettingsError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

    root_path = source.get("ACADEMIC_DATA_ROOT_PATH", "").strip().rstrip("/")
    if root_path and (
        not root_path.startswith("/")
        or "//" in root_path
        or ".." in root_path.split("/")
        or not re.fullmatch(r"/[A-Za-z0-9._/-]+", root_path)
    ):
        raise SettingsError("ACADEMIC_DATA_ROOT_PATH must be an absolute URL path prefix")

    return Settings(
        database_url=raw_url,
        environment=environment,
        database_name=database_name,
        database_host=parsed_url.host,
        log_level=configured_level,
        root_path=root_path,
        db_pool_size=_bounded_integer(source, "ACADEMIC_DATA_DB_POOL_SIZE", 2, 1, 5),
        db_max_overflow=_bounded_integer(source, "ACADEMIC_DATA_DB_MAX_OVERFLOW", 1, 0, 5),
        db_pool_timeout_seconds=_bounded_integer(
            source, "ACADEMIC_DATA_DB_POOL_TIMEOUT_SECONDS", 3, 1, 15
        ),
        db_connect_timeout_seconds=_bounded_integer(
            source, "ACADEMIC_DATA_DB_CONNECT_TIMEOUT_SECONDS", 3, 1, 10
        ),
        db_statement_timeout_ms=_bounded_integer(
            source, "ACADEMIC_DATA_DB_STATEMENT_TIMEOUT_MS", 5000, 500, 30000
        ),
        request_timeout_seconds=_bounded_integer(
            source, "ACADEMIC_DATA_REQUEST_TIMEOUT_SECONDS", 15, 1, 60
        ),
    )


def _bounded_integer(
    source: Mapping[str, str], key: str, default: int, minimum: int, maximum: int
) -> int:
    raw_value = source.get(key, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise SettingsError(f"{key} must be an integer between {minimum} and {maximum}") from error
    if not minimum <= value <= maximum:
        raise SettingsError(f"{key} must be an integer between {minimum} and {maximum}")
    return value


def validate_database_target(url: URL, database_name: str, environment: str) -> None:
    """Reject core/archive targets and require the canonical persistent DB in live envs."""
    normalized_name = database_name.casefold()
    if normalized_name in FORBIDDEN_DATABASE_NAMES or normalized_name.startswith("andromeda_"):
        raise SettingsError(
            "The academic data service cannot use an Andromeda core or archive database"
        )

    if environment in {"staging", "production"} and database_name != SERVICE_DATABASE_NAME:
        raise SettingsError(
            f"{environment} must use the dedicated {SERVICE_DATABASE_NAME} database"
        )

    if environment == "test" and url.drivername in {"postgresql", "postgresql+psycopg"}:
        if database_name != "academic_data_test" or url.host not in {"localhost", "127.0.0.1"}:
            raise SettingsError(
                "PostgreSQL tests may target only localhost database academic_data_test"
            )

    if environment == "development" and url.drivername in {
        "postgresql",
        "postgresql+psycopg",
    }:
        if not database_name.endswith("_dev") or url.host not in {"localhost", "127.0.0.1"}:
            raise SettingsError(
                "Development PostgreSQL must be a localhost database with a _dev suffix"
            )

    if url.drivername.startswith("sqlite"):
        if environment != "test":
            raise SettingsError("SQLite is permitted only for explicit service unit tests")
        return

    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise SettingsError("The service requires PostgreSQL with the psycopg driver")
