"""Active-release SQLAlchemy implementation of the academic data read port."""

from __future__ import annotations

import base64
import binascii
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Connection

from academic_data_service.application.ports import PageRows
from academic_data_service.infrastructure.database import admission_models as _admission_models
from academic_data_service.infrastructure.database import catalog_models as _catalog_models
from academic_data_service.infrastructure.database import evidence_models as _evidence_models
from academic_data_service.infrastructure.database import models as _lifecycle_models
from academic_data_service.infrastructure.database import source_models as _source_models
from academic_data_service.infrastructure.database import (
    subject_classification_models as _subject_classification_models,
)
from academic_data_service.infrastructure.database.base import Base

_REGISTERED_MODELS = (
    _admission_models,
    _catalog_models,
    _evidence_models,
    _lifecycle_models,
    _source_models,
    _subject_classification_models,
)
EVIDENCE_BRIDGES: dict[str, tuple[str, str]] = {
    "universities": ("university_evidence", "university_id"),
    "directions": ("direction_evidence", "direction_id"),
    "departments": ("department_evidence", "department_id"),
    "direction_departments": ("direction_department_evidence", "direction_department_id"),
    "educational_programs": ("program_evidence", "program_id"),
    "educational_program_departments": (
        "program_department_evidence",
        "program_department_id",
    ),
    "catalog_courses": ("catalog_course_evidence", "course_id"),
    "study_plans": ("study_plan_evidence", "study_plan_id"),
    "curriculum_items": ("curriculum_evidence", "curriculum_item_id"),
    "admission_campaigns": ("campaign_evidence", "campaign_id"),
    "campaign_calendar_events": ("calendar_event_evidence", "calendar_event_id"),
    "program_offerings": ("offering_evidence", "offering_id"),
    "competition_pools": ("competition_pool_evidence", "pool_id"),
    "competition_pool_offerings": ("pool_offering_evidence", "pool_offering_id"),
    "place_quota_assertions": ("place_quota_evidence", "assertion_id"),
    "admission_requirement_sets": ("requirement_set_evidence", "requirement_set_id"),
    "admission_requirement_nodes": ("requirement_node_evidence", "requirement_node_id"),
    "offering_requirement_links": ("offering_requirement_evidence", "link_id"),
    "tuition_assertions": ("tuition_evidence", "tuition_assertion_id"),
    "historical_admission_statistics": ("historical_statistic_evidence", "statistic_id"),
    "admission_statistics": ("admission_statistic_evidence", "statistic_id"),
    "individual_achievement_policies": ("achievement_evidence", "achievement_policy_id"),
    "admission_documents": ("admission_document_evidence", "document_id"),
    "admission_document_pages": ("admission_document_page_evidence", "page_id"),
    "admission_result_sources": ("admission_result_source_evidence", "result_source_id"),
    "source_relationships": ("source_relationship_evidence", "relationship_id"),
    "manual_review_items": ("manual_review_evidence", "manual_review_id"),
    "admission_exams": ("exam_evidence", "exam_id"),
    "funding_types": ("funding_type_evidence", "funding_type_id"),
    "quota_types": ("quota_type_evidence", "quota_type_id"),
}


class InvalidCursorError(ValueError):
    """A page cursor is not a valid encoded external key."""


class SQLAlchemyAcademicDataReadRepository:
    """Read canonical rows from one request-scoped, read-only connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._release_id: UUID | None = None
        self._release_key: str | None = None
        self._release: dict[str, Any] | None = None
        self._last_row_count: int | None = None

    @property
    def active_release_key(self) -> str:
        self._ensure_active_release()
        assert self._release_key is not None
        return self._release_key

    @property
    def release_key_if_loaded(self) -> str | None:
        return self._release_key

    @property
    def last_row_count(self) -> int | None:
        return self._last_row_count

    @property
    def active_release_id(self) -> UUID:
        self._ensure_active_release()
        assert self._release_id is not None
        return self._release_id

    def get(self, table_name: str, external_key: str) -> dict[str, Any] | None:
        table = self._table(table_name)
        row = (
            self._connection.execute(
                select(table).where(
                    table.c.release_id == self.active_release_id,
                    table.c.external_key == external_key,
                )
            )
            .mappings()
            .first()
        )
        self._last_row_count = 1 if row is not None else 0
        return dict(row) if row is not None else None

    def get_by_id(self, table_name: str, record_id: UUID) -> dict[str, Any] | None:
        table = self._table(table_name)
        row = (
            self._connection.execute(
                select(table).where(
                    table.c.release_id == self.active_release_id,
                    table.c.id == record_id,
                )
            )
            .mappings()
            .first()
        )
        self._last_row_count = 1 if row is not None else 0
        return dict(row) if row is not None else None

    def active_release(self) -> dict[str, Any]:
        self._ensure_active_release()
        assert self._release is not None
        return self._release

    def page(
        self,
        table_name: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> PageRows:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        table = self._table(table_name)
        base_filters = self._conditions(table, filters)
        count = self._connection.execute(
            select(func.count()).select_from(table).where(*base_filters)
        ).scalar_one()
        conditions = list(base_filters)
        if cursor is not None:
            conditions.append(table.c.external_key > decode_cursor(cursor))
        rows = (
            self._connection.execute(
                select(table).where(*conditions).order_by(table.c.external_key).limit(limit + 1)
            )
            .mappings()
            .all()
        )
        has_more = len(rows) > limit
        selected = rows[:limit]
        next_cursor = encode_cursor(str(selected[-1]["external_key"])) if has_more else None
        self._last_row_count = len(selected)
        return PageRows([dict(row) for row in selected], next_cursor, int(count))

    def related(
        self,
        table_name: str,
        foreign_key: str,
        parent_id: UUID,
        *,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        table = self._table(table_name)
        if foreign_key not in table.c:
            raise ValueError(f"unknown relation column {foreign_key}")
        conditions = [
            table.c.release_id == self.active_release_id,
            table.c[foreign_key] == parent_id,
            *self._conditions(table, filters),
        ]
        rows = (
            self._connection.execute(
                select(table).where(*conditions).order_by(table.c.external_key)
            )
            .mappings()
            .all()
        )
        self._last_row_count = len(rows)
        return [dict(row) for row in rows]

    def evidence_for(self, entity_table: str, entity_id: UUID) -> list[dict[str, Any]]:
        bridge_spec = EVIDENCE_BRIDGES.get(entity_table)
        if bridge_spec is None:
            return []
        bridge_name, target_field = bridge_spec
        bridge = self._table(bridge_name)
        evidence = self._table("source_evidence")
        artifacts = self._table("source_artifacts")
        joined = bridge.join(
            evidence,
            and_(
                bridge.c.release_id == evidence.c.release_id, bridge.c.evidence_id == evidence.c.id
            ),
        ).join(
            artifacts,
            and_(
                evidence.c.release_id == artifacts.c.release_id,
                evidence.c.source_artifact_id == artifacts.c.id,
            ),
        )
        rows = (
            self._connection.execute(
                select(
                    evidence.c.external_key.label("evidence_key"),
                    evidence.c.field_path,
                    evidence.c.locator,
                    evidence.c.claim,
                    evidence.c.quoted_fragment,
                    evidence.c.observed_at,
                    evidence.c.verification_status,
                    artifacts.c.external_key.label("source_artifact_key"),
                    artifacts.c.requested_url,
                    artifacts.c.final_url,
                    artifacts.c.fetched_at,
                    artifacts.c.sha256,
                )
                .select_from(joined)
                .where(
                    bridge.c.release_id == self.active_release_id,
                    bridge.c[target_field] == entity_id,
                )
                .order_by(evidence.c.external_key)
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    def manual_reviews_for(self, external_key: str) -> list[dict[str, Any]]:
        table = self._table("manual_review_items")
        rows = (
            self._connection.execute(
                select(table)
                .where(
                    table.c.release_id == self.active_release_id,
                    or_(
                        table.c.subject_key == external_key,
                        table.c.source_key == external_key,
                        table.c.target_key == external_key,
                    ),
                )
                .order_by(table.c.external_key)
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    def subject_classifications_for(
        self,
        subject_type: str,
        subject_ids: list[UUID],
        taxonomy_key: str,
        taxonomy_version: str,
    ) -> dict[UUID, dict[str, Any]]:
        """Return the latest immutable Jev result per typed subject row."""

        if subject_type == "catalog_course":
            target_column = "catalog_course_id"
        elif subject_type == "curriculum_item":
            target_column = "curriculum_item_id"
        else:
            raise ValueError("unsupported subject type")
        if not subject_ids:
            return {}

        classifications = self._table("subject_classifications")
        runs = self._table("subject_classification_runs")
        categories = self._table("subject_taxonomy_categories")
        subject_id_column = classifications.c[target_column]
        ranked = (
            select(
                subject_id_column.label("subject_id"),
                classifications.c.taxonomy_key,
                classifications.c.taxonomy_version,
                classifications.c.category_code,
                categories.c.name.label("category_name"),
                classifications.c.confidence,
                classifications.c.probabilities,
                classifications.c.jev_answer,
                classifications.c.review_reasons,
                classifications.c.review_status,
                runs.c.external_key.label("run_key"),
                runs.c.resolved_model_version,
                func.row_number()
                .over(
                    partition_by=subject_id_column,
                    order_by=(runs.c.completed_at.desc(), runs.c.id.desc()),
                )
                .label("result_rank"),
            )
            .select_from(
                classifications.join(
                    runs,
                    and_(
                        classifications.c.release_id == runs.c.release_id,
                        classifications.c.run_id == runs.c.id,
                    ),
                ).join(
                    categories,
                    and_(
                        classifications.c.taxonomy_key == categories.c.taxonomy_key,
                        classifications.c.taxonomy_version == categories.c.taxonomy_version,
                        classifications.c.category_code == categories.c.category_code,
                    ),
                )
            )
            .where(
                classifications.c.release_id == self.active_release_id,
                classifications.c.taxonomy_key == taxonomy_key,
                classifications.c.taxonomy_version == taxonomy_version,
                subject_id_column.in_(subject_ids),
            )
            .subquery()
        )
        rows = self._connection.execute(select(ranked).where(ranked.c.result_rank == 1)).mappings()
        results: dict[UUID, dict[str, Any]] = {}
        for row in rows:
            results[row["subject_id"]] = {
                "taxonomy_key": row["taxonomy_key"],
                "taxonomy_version": row["taxonomy_version"],
                "category_code": row["category_code"],
                "category_name": row["category_name"],
                "confidence": row["confidence"],
                "probabilities": row["probabilities"],
                "model": row["resolved_model_version"],
                "run_key": row["run_key"],
                "review_status": row["review_status"],
                "review_reasons": row["review_reasons"],
            }
        return results

    def subject_taxonomy(self, taxonomy_key: str, taxonomy_version: str) -> dict[str, Any] | None:
        taxonomies = self._table("subject_taxonomies")
        categories = self._table("subject_taxonomy_categories")
        taxonomy = (
            self._connection.execute(
                select(taxonomies).where(
                    taxonomies.c.taxonomy_key == taxonomy_key,
                    taxonomies.c.taxonomy_version == taxonomy_version,
                )
            )
            .mappings()
            .first()
        )
        if taxonomy is None:
            self._last_row_count = 0
            return None
        category_rows = self._connection.execute(
            select(categories)
            .where(
                categories.c.taxonomy_key == taxonomy_key,
                categories.c.taxonomy_version == taxonomy_version,
            )
            .order_by(categories.c.ordinal)
        ).mappings()
        self._last_row_count = 1
        return {
            **dict(taxonomy),
            "categories": [
                {
                    "category_code": row["category_code"],
                    "ordinal": row["ordinal"],
                    "name": row["name"],
                    "definition": row["definition"],
                }
                for row in category_rows
            ],
        }

    def _ensure_active_release(self) -> None:
        if self._release_id is not None:
            return
        active = self._table("active_data_release")
        releases = self._table("data_releases")
        row = (
            self._connection.execute(
                select(releases)
                .select_from(active.join(releases, active.c.release_id == releases.c.id))
                .where(
                    active.c.slot_key == "active",
                    releases.c.status == "committed",
                    releases.c.reconciliation_status.in_(("passed", "passed_with_gaps")),
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            from academic_data_service.application.queries import ApiReadError

            raise ApiReadError(
                503, "active_release_unavailable", "No committed data release is ready."
            )
        self._release_id = row["id"]
        self._release_key = row["release_key"]
        self._release = dict(row)

    def _conditions(self, table: Any, filters: dict[str, Any] | None) -> list[Any]:
        result: list[Any] = [table.c.release_id == self.active_release_id]
        for column_name, value in (filters or {}).items():
            if column_name not in table.c:
                raise ValueError(f"unsupported filter column {column_name}")
            result.append(table.c[column_name] == value)
        return result

    def _table(self, table_name: str) -> Any:
        table = Base.metadata.tables.get(table_name)
        if table is None:
            raise ValueError(f"unknown service table {table_name}")
        return table


def encode_cursor(external_key: str) -> str:
    return base64.urlsafe_b64encode(external_key.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> str:
    if not value or len(value) > 1024:
        raise InvalidCursorError("cursor is empty or too long")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise InvalidCursorError("cursor is not a valid encoded external key") from error
    if not decoded or len(decoded) > 512:
        raise InvalidCursorError("cursor does not contain a valid external key")
    return decoded
