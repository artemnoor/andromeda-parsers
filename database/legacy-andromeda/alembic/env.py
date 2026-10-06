from __future__ import annotations

import logging
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from andromeda.infrastructure.config import Settings, redact_database_url
from andromeda.infrastructure.database.base import Base
from andromeda.infrastructure.database import models as _models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _restore_application_loggers() -> None:
    """Alembic's fileConfig must not silently disable application diagnostics."""
    for name, candidate in logging.Logger.manager.loggerDict.items():
        if name == "andromeda" or name.startswith("andromeda."):
            if isinstance(candidate, logging.Logger):
                candidate.disabled = False


_restore_application_loggers()

target_metadata = Base.metadata
logger = logging.getLogger("andromeda.alembic")


def _configured_database_url() -> str:
    environment_url = os.environ.get("ANDROMEDA_DATABASE_URL") or os.environ.get("BMSTU_DATABASE_URL")
    configured_url = environment_url or config.get_main_option("sqlalchemy.url") or None
    settings = Settings.from_environment(configured_url)
    database_url = settings.database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    logger.info(
        "migration_target environment=%s dialect_target=%s",
        settings.environment,
        redact_database_url(database_url),
    )
    return database_url


def run_migrations_offline() -> None:
    url = _configured_database_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _configured_database_url()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
