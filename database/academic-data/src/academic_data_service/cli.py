"""Explicit operator commands for service database checks and migrations."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError

from academic_data_service import __version__
from academic_data_service.importer.bundle import BundleInputError, render_validation_report
from academic_data_service.importer.cli import (
    add_bundle_commands,
    execute_bundle_import,
    execute_bundle_validation,
)
from academic_data_service.importer.mapping import BundleMappingError
from academic_data_service.importer.persistence import BundleImportError
from academic_data_service.infrastructure.database.connection import (
    create_service_engine,
    verify_server_identity,
)
from academic_data_service.infrastructure.database.models import MigrationAuditModel
from academic_data_service.infrastructure.database.revisions import current_schema_revision
from academic_data_service.observability.logging import configure_logging
from academic_data_service.settings import SettingsError, load_settings

SERVICE_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("academic_data_service")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="academic-data")
    groups = parser.add_subparsers(dest="command_group", required=True)
    database = groups.add_parser("db", help="check or migrate the service database")
    actions = database.add_subparsers(dest="database_action", required=True)
    actions.add_parser("check", help="verify target database, PostgreSQL version and schema head")
    actions.add_parser("upgrade", help="apply this service's Alembic revisions to head")
    add_bundle_commands(groups)
    return parser


def build_alembic_config() -> Config:
    source_migrations = SERVICE_ROOT / "migrations"
    installed_migrations = Path(sys.prefix) / "share" / "andromeda-academic-data" / "migrations"
    migrations_path = source_migrations if source_migrations.is_dir() else installed_migrations
    if not migrations_path.is_dir():
        raise RuntimeError("The service Alembic migration package is missing")
    config = Config()
    config.set_main_option("script_location", str(migrations_path))
    config.set_main_option("version_path_separator", "os")
    return config


def run_database_check() -> dict[str, str | int | float | None]:
    settings = load_settings()
    started_at = time.perf_counter()
    engine = create_service_engine(settings)
    try:
        with engine.connect() as connection:
            identity = verify_server_identity(connection, settings)
        revision = current_schema_revision(engine)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        result: dict[str, str | int | float | None] = {
            "service": "andromeda-academic-data",
            "service_version": __version__,
            "database_name": str(identity["database_name"]),
            "database_host": str(identity["database_host"]),
            "postgres_major": int(identity["server_major"]),
            "schema_revision": revision,
            "elapsed_ms": elapsed_ms,
        }
        logger.info(
            "database check completed",
            extra={
                "event": "database.check.completed",
                "database_host": identity["database_host"],
                "database_name": identity["database_name"],
                "migration_revision": revision,
                "elapsed_ms": elapsed_ms,
                "outcome": "connected",
            },
        )
        return result
    finally:
        engine.dispose()


def run_database_upgrade() -> dict[str, str | int | float | None]:
    settings = load_settings()
    engine = create_service_engine(settings)
    started_at = time.perf_counter()
    try:
        with engine.connect() as connection:
            identity = verify_server_identity(connection, settings)
        logger.info(
            "database migration started",
            extra={
                "event": "database.migration.started",
                "database_host": identity["database_host"],
                "database_name": identity["database_name"],
                "outcome": "started",
            },
        )
        command.upgrade(build_alembic_config(), "head")
        revision = current_schema_revision(engine)
        if revision is None:
            raise RuntimeError("Alembic completed but the service revision table is empty")
        with engine.begin() as connection:
            connection.execute(
                insert(MigrationAuditModel).values(
                    migration_revision=revision,
                    operation="upgrade",
                )
            )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "database migration completed",
            extra={
                "event": "database.migration.completed",
                "database_host": identity["database_host"],
                "database_name": identity["database_name"],
                "migration_revision": revision,
                "elapsed_ms": elapsed_ms,
                "outcome": "succeeded",
            },
        )
        return {
            "service": "andromeda-academic-data",
            "database_name": str(identity["database_name"]),
            "schema_revision": revision,
            "elapsed_ms": elapsed_ms,
        }
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command_group == "bundle" and arguments.bundle_action == "validate":
            configure_logging(os.getenv("LOG_LEVEL"))
            report, report_path = execute_bundle_validation(arguments.input, arguments.output)
            if report_path is None:
                sys.stdout.buffer.write(render_validation_report(report))
            else:
                print(
                    json.dumps(
                        {
                            "valid": report["valid"],
                            "input_digest": report["input"]["digest"],
                            "error_count": len(report["errors"]),
                            "warning_count": len(report["warnings"]),
                            "report_path": str(report_path),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            return 0 if report["valid"] else 2
        if arguments.command_group == "bundle" and arguments.bundle_action == "import":
            configure_logging(os.getenv("LOG_LEVEL"))
            result = execute_bundle_import(
                arguments.input,
                commit=arguments.commit,
                output_path=arguments.output,
            )
            if arguments.output:
                mapping = result.get("mapping", {})
                print(
                    json.dumps(
                        {
                            "outcome": result["outcome"],
                            "input_digest": result["input_digest"],
                            "release_key": result["release_key"],
                            "database_connection_opened": result.get(
                                "database_connection_opened", True
                            ),
                            "row_counts": mapping.get("typed_row_counts", {}),
                            "report_path": result.get("report_path"),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            else:
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0

        settings = load_settings()
        configure_logging(settings.log_level)
        if arguments.command_group == "db" and arguments.database_action == "check":
            result = run_database_check()
        elif arguments.command_group == "db" and arguments.database_action == "upgrade":
            result = run_database_upgrade()
        else:
            parser.error("unsupported command")
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except SettingsError as error:
        configure_logging().error(
            "database configuration rejected",
            extra={"event": "database.configuration.rejected", "outcome": str(error)},
        )
        return 2
    except BundleInputError as error:
        configure_logging(os.getenv("LOG_LEVEL")).error(
            "bundle input rejected",
            extra={
                "event": "bundle.validation.input_rejected",
                "phase": "input",
                "outcome": str(error),
            },
        )
        return 2
    except BundleMappingError as error:
        configure_logging(os.getenv("LOG_LEVEL")).error(
            "bundle mapping rejected",
            extra={
                "event": "bundle.import.mapping_rejected",
                "phase": "mapping",
                "outcome": str(error),
            },
        )
        return 2
    except BundleImportError as error:
        configure_logging(os.getenv("LOG_LEVEL")).error(
            "bundle import failed",
            extra={
                "event": "bundle.import.failed",
                "phase": "import",
                "outcome": str(error),
            },
        )
        return 1
    except (SQLAlchemyError, RuntimeError) as error:
        configure_logging().error(
            "database command failed",
            extra={
                "event": "database.command.failed",
                "exception_type": type(error).__name__,
                "outcome": "failed",
            },
        )
        return 1
    except Exception as error:
        configure_logging().error(
            "database command failed",
            extra={
                "event": "database.command.failed",
                "exception_type": type(error).__name__,
                "outcome": "failed",
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
