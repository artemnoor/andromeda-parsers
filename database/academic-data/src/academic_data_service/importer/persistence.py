"""Atomic, idempotent persistence of validated bundle projections."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Engine, Table, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

import academic_data_service.infrastructure.database.admission_models as _admission_models  # noqa: F401
import academic_data_service.infrastructure.database.catalog_models as _catalog_models  # noqa: F401
import academic_data_service.infrastructure.database.evidence_models as _evidence_models  # noqa: F401
import academic_data_service.infrastructure.database.source_models as _source_models  # noqa: F401
from academic_data_service.importer.bundle import BundleInputError, BundleReader
from academic_data_service.importer.mapping import (
    BundleMappingError,
    MappingResult,
    project_bundle,
)
from academic_data_service.infrastructure.database.base import Base
from academic_data_service.infrastructure.database.connection import (
    create_service_engine,
    verify_server_identity,
)
from academic_data_service.infrastructure.database.models import (
    ActiveDataReleaseModel,
    DataReleaseModel,
    ImportBatchModel,
)
from academic_data_service.infrastructure.database.revisions import (
    SERVICE_SCHEMA_HEAD,
    current_schema_revision,
)
from academic_data_service.settings import Settings, SettingsError, load_settings

logger = logging.getLogger("academic_data_service.importer")
BATCH_SIZE = 500
REQUIRED_IMPORT_SCHEMA_REVISION = SERVICE_SCHEMA_HEAD

TABLE_INSERT_ORDER = (
    "source_artifacts",
    "universities",
    "directions",
    "departments",
    "admission_campaigns",
    "funding_types",
    "quota_types",
    "admission_exams",
    "educational_programs",
    "direction_departments",
    "educational_program_departments",
    "catalog_courses",
    "study_plans",
    "curriculum_items",
    "campaign_calendar_events",
    "program_offerings",
    "competition_pools",
    "competition_pool_offerings",
    "admission_requirement_sets",
    "admission_requirement_nodes",
    "offering_requirement_links",
    "tuition_assertions",
    "historical_admission_statistics",
    "admission_statistics",
    "individual_achievement_policies",
    "admission_documents",
    "admission_document_pages",
    "admission_result_sources",
    "source_relationships",
    "manual_review_items",
    "source_observations",
    "source_evidence",
    "university_evidence",
    "direction_evidence",
    "department_evidence",
    "direction_department_evidence",
    "program_evidence",
    "program_department_evidence",
    "catalog_course_evidence",
    "study_plan_evidence",
    "curriculum_evidence",
    "campaign_evidence",
    "calendar_event_evidence",
    "offering_evidence",
    "competition_pool_evidence",
    "pool_offering_evidence",
    "place_quota_evidence",
    "requirement_set_evidence",
    "requirement_node_evidence",
    "offering_requirement_evidence",
    "tuition_evidence",
    "historical_statistic_evidence",
    "admission_statistic_evidence",
    "achievement_evidence",
    "admission_document_evidence",
    "admission_document_page_evidence",
    "admission_result_source_evidence",
    "source_relationship_evidence",
    "manual_review_evidence",
    "exam_evidence",
    "funding_type_evidence",
    "quota_type_evidence",
)


class BundleImportError(RuntimeError):
    """A bundle import was rejected or its transaction could not be committed."""


def _safe_failure_code(error: Exception) -> str:
    if isinstance(error, BundleImportError):
        return "BUNDLE_RECONCILIATION_FAILED"
    if isinstance(error, IntegrityError):
        return "DATABASE_CONSTRAINT_FAILED"
    if isinstance(error, OperationalError):
        return "DATABASE_OPERATION_FAILED"
    if isinstance(error, BundleInputError):
        return "BUNDLE_VALIDATION_FAILED"
    if isinstance(error, BundleMappingError):
        return "BUNDLE_MAPPING_FAILED"
    if isinstance(error, SettingsError):
        return "DATABASE_TARGET_REJECTED"
    return "IMPORT_TRANSACTION_FAILED"


def _validate_projection(projection: MappingResult) -> None:
    if projection.validator_report.get("valid") is not True:
        raise BundleImportError("only a successfully validated bundle can be imported")
    expected_observations = projection.report.get("source_observations_expected")
    actual_observations = len(projection.table_rows.get("source_observations", []))
    if expected_observations != actual_observations:
        raise BundleImportError("source observation count does not reconcile with input rows")
    unknown_tables = set(projection.table_rows) - set(Base.metadata.tables)
    if unknown_tables:
        raise BundleImportError("mapping contains a table not present in the service schema")
    missing_order = set(projection.table_rows) - set(TABLE_INSERT_ORDER)
    if missing_order:
        raise BundleImportError(
            "mapping contains a table with no declared foreign-key insert order"
        )
    for table_name, rows in projection.table_rows.items():
        seen_keys: set[str] = set()
        for row in rows:
            if row.get("release_id") != projection.release_id:
                raise BundleImportError(f"{table_name} contains a row for another release")
            key = row.get("external_key")
            if not isinstance(key, str) or not key:
                raise BundleImportError(f"{table_name} contains a row without an external key")
            if key in seen_keys:
                raise BundleImportError(f"{table_name} contains duplicate external keys")
            seen_keys.add(key)


def _insert_projection_rows(connection: Any, projection: MappingResult) -> dict[str, int]:
    inserted: dict[str, int] = {}
    for table_name in TABLE_INSERT_ORDER:
        rows = projection.table_rows.get(table_name, [])
        if not rows:
            continue
        table = Base.metadata.tables[table_name]
        chunk_count = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE
        for ordinal, offset in enumerate(range(0, len(rows), BATCH_SIZE), start=1):
            chunk = rows[offset : offset + BATCH_SIZE]
            try:
                connection.execute(insert(table), chunk)
            except SQLAlchemyError as error:
                original_error = getattr(error, "orig", None)
                diagnostic = getattr(original_error, "diag", None)
                logger.error(
                    "bundle import table chunk rejected",
                    extra={
                        "event": "bundle.import.chunk_rejected",
                        "phase": "database_write",
                        "input_digest": projection.input_digest,
                        "release_key": projection.release_key,
                        "table": table_name,
                        "chunk_ordinal": ordinal,
                        "chunk_count": chunk_count,
                        "chunk_size": len(chunk),
                        "source_key": (
                            str(chunk[0].get("external_key", ""))[:160] if chunk else None
                        ),
                        "sqlstate": getattr(original_error, "sqlstate", None),
                        "constraint_name": getattr(diagnostic, "constraint_name", None),
                        "database_table": getattr(diagnostic, "table_name", None),
                        "database_column": getattr(diagnostic, "column_name", None),
                        "database_exception_type": (
                            type(original_error).__name__ if original_error is not None else None
                        ),
                        "outcome": "rejected",
                    },
                )
                raise
            logger.info(
                "bundle import chunk written",
                extra={
                    "event": "bundle.import.chunk_written",
                    "phase": "database_write",
                    "input_digest": projection.input_digest,
                    "release_key": projection.release_key,
                    "table": table_name,
                    "chunk_ordinal": ordinal,
                    "chunk_count": chunk_count,
                    "chunk_size": len(chunk),
                    "outcome": "inserted",
                },
            )
        inserted[table_name] = len(rows)
    return inserted


def _reconcile_database(connection: Any, projection: MappingResult) -> dict[str, Any]:
    actual_table_counts: dict[str, int] = {}
    for table_name, expected_count in sorted(
        (name, len(rows)) for name, rows in projection.table_rows.items()
    ):
        table = Base.metadata.tables[table_name]
        actual_count = connection.execute(
            select(func.count())
            .select_from(table)
            .where(table.c.release_id == projection.release_id)
        ).scalar_one()
        actual_table_counts[table_name] = int(actual_count)
        if int(actual_count) != expected_count:
            raise BundleImportError(f"row count did not reconcile for {table_name}")

    observed_dataset_counts = {
        str(dataset_name): int(count)
        for dataset_name, count in connection.execute(
            select(
                Base.metadata.tables["source_observations"].c.dataset_name,
                func.count(),
            )
            .where(
                Base.metadata.tables["source_observations"].c.release_id == projection.release_id
            )
            .group_by(Base.metadata.tables["source_observations"].c.dataset_name)
        ).all()
    }
    expected_dataset_counts = {
        name.removesuffix(".jsonl"): count
        for name, count in projection.report["source_dataset_counts"].items()
    }
    expected_dataset_counts.update(
        {
            "source_artifacts": projection.report["source_manifest_count"],
            "manual_review.csv": projection.report["manual_review_count"],
            "user_confirmed_study_plan_links": projection.report[
                "confirmed_study_plan_link_observations"
            ],
            "user_confirmed_study_plan_links_manifest": projection.report.get(
                "confirmed_study_plan_link_manifest_observations", 0
            ),
        }
    )
    expected_dataset_counts = {
        name: count for name, count in expected_dataset_counts.items() if count > 0
    }
    if observed_dataset_counts != expected_dataset_counts:
        raise BundleImportError("source observation datasets do not reconcile with input files")

    operator_counts = {
        str(operator): int(count)
        for operator, count in connection.execute(
            select(
                Base.metadata.tables["admission_requirement_nodes"].c.operator,
                func.count(),
            )
            .where(
                Base.metadata.tables["admission_requirement_nodes"].c.release_id
                == projection.release_id,
                Base.metadata.tables["admission_requirement_nodes"].c.node_kind == "operator",
            )
            .group_by(Base.metadata.tables["admission_requirement_nodes"].c.operator)
        ).all()
        if operator is not None
    }
    if operator_counts != projection.report["requirement_operator_counts"]:
        raise BundleImportError("AND/OR/AT_LEAST operator counts changed during import")
    if projection.report["excluded_olympiad_rows"] != 0:
        raise BundleImportError("forbidden olympiad rows are present in the mapping")
    if projection.report["excluded_personal_applicant_rows"] != 0:
        raise BundleImportError("forbidden personal applicant rows are present in the mapping")
    return {
        "table_counts": actual_table_counts,
        "source_observation_counts": observed_dataset_counts,
        "requirement_operator_counts": operator_counts,
        "explicit_relationship_count": actual_table_counts.get("source_relationships", 0),
        "manual_review_count": actual_table_counts.get("manual_review_items", 0),
        "reconciled": True,
    }


def _record_failed_batch(
    engine: Engine,
    projection: MappingResult,
    failure_code: str,
) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(ImportBatchModel).values(
                    id=uuid4(),
                    source_bundle_sha256=projection.input_digest,
                    mapper_version=projection.report["mapper_version"],
                    status="failed",
                    finished_at=datetime.now(UTC),
                    validation_report=projection.validator_report,
                    row_counts=projection.report,
                    failure_code=failure_code,
                )
            )
    except Exception:
        logger.exception(
            "failed import batch metadata could not be recorded",
            extra={
                "event": "bundle.import.failure_audit_failed",
                "input_digest": projection.input_digest,
                "outcome": failure_code,
            },
        )


def commit_projection(
    engine: Engine,
    settings: Settings,
    projection: MappingResult,
    *,
    before_activation: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Write one release transactionally and update the active pointer last."""

    _validate_projection(projection)
    with engine.connect() as connection:
        identity = verify_server_identity(connection, settings)
    revision = current_schema_revision(engine)
    if revision != REQUIRED_IMPORT_SCHEMA_REVISION:
        raise BundleImportError(
            f"service schema must be at {REQUIRED_IMPORT_SCHEMA_REVISION} before import"
        )

    lock_bytes = hashlib.sha256(
        f"{projection.input_digest}:{projection.report['mapper_version']}".encode("ascii")
    ).digest()[:8]
    lock_key = int.from_bytes(lock_bytes, byteorder="big", signed=True)
    batch_id = uuid4()
    now = datetime.now(UTC)
    active_table = cast(Table, ActiveDataReleaseModel.__table__)
    release_table = cast(Table, DataReleaseModel.__table__)
    batch_table = cast(Table, ImportBatchModel.__table__)

    try:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
            )
            existing = connection.execute(
                select(release_table.c.id, release_table.c.status).where(
                    release_table.c.source_bundle_sha256 == projection.input_digest,
                    release_table.c.mapper_version == projection.report["mapper_version"],
                )
            ).one_or_none()
            if existing is not None and existing.status == "committed":
                active = connection.execute(
                    select(active_table.c.release_id).where(active_table.c.slot_key == "active")
                ).scalar_one_or_none()
                return {
                    "outcome": "no_op",
                    "reason": "bundle_digest_and_mapper_version_already_committed",
                    "input_digest": projection.input_digest,
                    "release_id": str(existing.id),
                    "release_key": projection.release_key,
                    "active_release_id": str(active) if active else None,
                    "database_name": identity["database_name"],
                    "schema_revision": revision,
                    "mapping": projection.report,
                }

            connection.execute(
                insert(batch_table).values(
                    id=batch_id,
                    source_bundle_sha256=projection.input_digest,
                    mapper_version=projection.report["mapper_version"],
                    status="staging",
                    started_at=now,
                    validation_report=projection.validator_report,
                    row_counts=projection.report,
                )
            )
            connection.execute(
                insert(release_table).values(
                    id=projection.release_id,
                    release_key=projection.release_key,
                    source_bundle_sha256=projection.input_digest,
                    mapper_version=projection.report["mapper_version"],
                    batch_id=batch_id,
                    status="staging",
                    schema_revision=revision,
                    reconciliation_status=None,
                    reconciliation_summary=None,
                    created_at=now,
                    committed_at=None,
                )
            )
            inserted_counts = _insert_projection_rows(connection, projection)
            reconciliation = _reconcile_database(connection, projection)
            report_payload = {
                **projection.report,
                "source_file_sha256": projection.raw_file_hashes,
                "database_reconciliation": reconciliation,
                "database_name": identity["database_name"],
                "schema_revision": revision,
                "committed_at": now.isoformat(),
            }
            if before_activation is not None:
                before_activation()

            previous_active = connection.execute(
                select(active_table.c.release_id).where(active_table.c.slot_key == "active")
            ).scalar_one_or_none()
            connection.execute(
                update(release_table)
                .where(release_table.c.id == projection.release_id)
                .values(
                    status="committed",
                    reconciliation_status=(
                        "passed_with_gaps"
                        if projection.report["warnings"]
                        or projection.report["unresolved_exact_references"]
                        or projection.validator_report.get("warnings")
                        else "passed"
                    ),
                    reconciliation_summary=report_payload,
                    committed_at=now,
                )
            )
            connection.execute(
                update(batch_table)
                .where(batch_table.c.id == batch_id)
                .values(status="committed", finished_at=now, row_counts=report_payload)
            )
            connection.execute(
                pg_insert(active_table)
                .values(slot_key="active", release_id=projection.release_id, changed_at=now)
                .on_conflict_do_update(
                    index_elements=[active_table.c.slot_key],
                    set_={"release_id": projection.release_id, "changed_at": now},
                )
            )
        result = {
            "outcome": "committed",
            "input_digest": projection.input_digest,
            "release_id": str(projection.release_id),
            "release_key": projection.release_key,
            "batch_id": str(batch_id),
            "previous_active_release_id": str(previous_active) if previous_active else None,
            "active_release_id": str(projection.release_id),
            "database_name": identity["database_name"],
            "schema_revision": revision,
            "inserted_counts": inserted_counts,
            "reconciliation": reconciliation,
            "mapping": projection.report,
        }
        logger.info(
            "bundle release committed and activated",
            extra={
                "event": "bundle.import.activated",
                "phase": "activation",
                "input_digest": projection.input_digest,
                "release_key": projection.release_key,
                "batch_id": str(batch_id),
                "database_name": identity["database_name"],
                "outcome": "committed",
            },
        )
        return result
    except Exception as error:
        failure_code = _safe_failure_code(error)
        _record_failed_batch(engine, projection, failure_code)
        original_error = getattr(error, "orig", None)
        diagnostic = getattr(original_error, "diag", None)
        logger.error(
            "bundle import transaction rolled back",
            extra={
                "event": "bundle.import.rolled_back",
                "phase": "database_write",
                "input_digest": projection.input_digest,
                "release_key": projection.release_key,
                "batch_id": str(batch_id),
                "failure_code": failure_code,
                "failure_reason": (
                    str(error)[:200] if isinstance(error, BundleImportError) else None
                ),
                "exception_type": type(error).__name__,
                "sqlstate": getattr(original_error, "sqlstate", None),
                "constraint_name": getattr(diagnostic, "constraint_name", None),
                "database_table": getattr(diagnostic, "table_name", None),
                "database_column": getattr(diagnostic, "column_name", None),
                "outcome": "rolled_back",
            },
        )
        safe_detail = str(error) if isinstance(error, BundleImportError) else failure_code
        raise BundleImportError(
            f"bundle import rolled back: {failure_code}: {safe_detail}"
        ) from None


def run_bundle_import(
    input_path: str,
    *,
    commit: bool,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Validate and map offline, then optionally commit to the dedicated DB."""

    projection = project_bundle(input_path)
    if not commit:
        result: dict[str, Any] = {
            "outcome": "dry_run",
            "database_connection_opened": False,
            "network_requests": 0,
            "input_digest": projection.input_digest,
            "release_key": projection.release_key,
            "mapping": projection.report,
        }
    else:
        settings = load_settings()
        with BundleReader(input_path) as reader:
            if reader.input_digest != projection.input_digest:
                raise BundleInputError(
                    "bundle changed after mapping; no database write was started"
                )
        engine = create_service_engine(settings)
        try:
            result = commit_projection(engine, settings, projection)
        finally:
            engine.dispose()
    if output_path:
        output = Path(output_path)
        if output.is_dir():
            output = output / "import-report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json_dumps(result),
            encoding="utf-8",
        )
        logger.info(
            "bundle import report written",
            extra={
                "event": "bundle.import.report_written",
                "phase": "output",
                "input_digest": projection.input_digest,
                "relative_file": str(output),
                "outcome": result["outcome"],
            },
        )
        result["report_path"] = str(output)
    return result


def json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
