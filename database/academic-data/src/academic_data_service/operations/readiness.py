"""Fail-closed readiness checks for the API's database and active release."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from academic_data_service.contracts.v1.models import ReadinessRecord
from academic_data_service.infrastructure.database.revisions import SERVICE_SCHEMA_HEAD


def check_readiness(connection: Connection, expected_database: str) -> ReadinessRecord:
    """Check only safe readiness facts; never return connection or schema details."""

    if connection.dialect.name != "postgresql":
        return _not_ready("database_version_unsupported")

    database_name, version_number = connection.execute(
        text("SELECT current_database(), current_setting('server_version_num')::integer")
    ).one()
    if database_name != expected_database:
        return _not_ready("database_identity_mismatch")
    if int(str(version_number)) // 10000 != 16:
        return _not_ready("database_version_unsupported")

    version_table = connection.execute(
        text("SELECT to_regclass('academic_data_alembic_version')::text")
    ).scalar_one_or_none()
    if version_table is None:
        return _not_ready("schema_outdated")
    schema_revision = connection.execute(
        text("SELECT version_num FROM academic_data_alembic_version LIMIT 1")
    ).scalar_one_or_none()
    if schema_revision != SERVICE_SCHEMA_HEAD:
        return _not_ready("schema_outdated", schema_revision=schema_revision)

    release_tables = connection.execute(
        text("SELECT to_regclass('active_data_release')::text, to_regclass('data_releases')::text")
    ).one()
    if not all(release_tables):
        return _not_ready("schema_outdated", schema_revision=schema_revision)
    release = (
        connection.execute(
            text(
                "SELECT r.release_key, r.source_bundle_sha256, r.status, r.reconciliation_status "
                "FROM active_data_release AS a "
                "JOIN data_releases AS r ON r.id = a.release_id "
                "WHERE a.slot_key = 'active'"
            )
        )
        .mappings()
        .first()
    )
    if release is None:
        return _not_ready("active_release_unavailable", schema_revision=schema_revision)
    if release["status"] != "committed" or release["reconciliation_status"] not in {
        "passed",
        "passed_with_gaps",
    }:
        return _not_ready("release_not_reconciled", schema_revision=schema_revision)

    return ReadinessRecord(
        status="ready",
        reason_code="ready",
        required_schema_revision=SERVICE_SCHEMA_HEAD,
        schema_revision=schema_revision,
        release_key=release["release_key"],
        bundle_digest_prefix=release["source_bundle_sha256"][:12],
    )


def _not_ready(reason_code: str, *, schema_revision: str | None = None) -> ReadinessRecord:
    return ReadinessRecord(
        status="not_ready",
        reason_code=reason_code,  # type: ignore[arg-type]
        required_schema_revision=SERVICE_SCHEMA_HEAD,
        schema_revision=schema_revision,
    )
