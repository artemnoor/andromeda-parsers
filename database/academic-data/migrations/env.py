"""Alembic environment isolated from backend/alembic and core ORM metadata."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

import academic_data_service.infrastructure.database.admission_models as _admission_models  # noqa: F401
import academic_data_service.infrastructure.database.catalog_models as _catalog_models  # noqa: F401
import academic_data_service.infrastructure.database.evidence_models as _evidence_models  # noqa: F401
import academic_data_service.infrastructure.database.models as _models  # noqa: F401
import academic_data_service.infrastructure.database.source_models as _source_models  # noqa: F401
from academic_data_service.infrastructure.database.base import Base
from academic_data_service.infrastructure.database.connection import verify_server_identity
from academic_data_service.settings import load_settings

config = context.config

target_metadata = Base.metadata
VERSION_TABLE = "academic_data_alembic_version"


def run_migrations_offline() -> None:
    settings = load_settings()
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = load_settings()
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = settings.database_url
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        verify_server_identity(connection, settings)
        # The identity query autobegins a SQLAlchemy transaction. End it before
        # Alembic configures and owns the migration transaction on this connection.
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            version_table=VERSION_TABLE,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
