"""Deterministic projections from the sanitized source bundle to service tables."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from academic_data_service.importer.bundle import (
    BundleFile,
    BundleInputError,
    BundleReader,
    validate_bundle,
)

MAPPER_VERSION = "bmstu-2026-bundle-v3"

# Every normalized dataset is either projected to typed rows or deliberately kept
# as an exact source observation. Unknown files fail closed in project_bundle().
DATASET_MAPPING_REGISTRY: dict[str, str] = {
    "admission_campaigns.jsonl": "admission_campaigns + source_observations",
    "admission_document_pages.jsonl": "admission_document_pages + source_observations",
    "admission_documents.jsonl": "admission_documents + source_observations",
    "admission_exam_requirements.jsonl": "admission_requirement_sets/nodes + source_observations",
    "admission_exam_source_rows.jsonl": "source_observations (source table retained verbatim)",
    "admission_information_page_facts.jsonl": "source_observations (page facts retained verbatim)",
    "admission_information_source_tables.jsonl": "source_observations (tables retained verbatim)",
    "admission_plan_source_rows.jsonl": "source_observations (Appendix 8.1 rows retained verbatim)",
    "admission_result_sources.jsonl": "admission_result_sources + source_observations",
    "admission_statistics.jsonl": "admission_statistics + source_observations",
    "campaign_dates.jsonl": "campaign_calendar_events + source_observations",
    "competition_pools.jsonl": "competition_pools + source_observations",
    "courses.jsonl": "catalog_courses + source_observations",
    "curriculum_items.jsonl": "curriculum_items + source_observations",
    "departments.jsonl": "departments + source_observations",
    "directions.jsonl": "directions + source_observations",
    "educational_programs.jsonl": "educational_programs + source_observations",
    "exams.jsonl": "admission_exams + source_observations",
    "funding_types.jsonl": "funding_types + source_observations",
    "historical_admission_statistics.jsonl": "historical_admission_statistics + observations",
    "individual_achievement_policies.jsonl": "individual_achievement_policies + observations",
    "program_offerings.jsonl": "program_offerings + source_observations",
    "quota_types.jsonl": "quota_types + source_observations",
    "relationships.jsonl": "source_relationships + exact typed associations + observations",
    "study_plans.jsonl": "study_plans + source_observations",
    "tuition.jsonl": "tuition_assertions + source_observations",
    "tuition_source_tables.jsonl": "source_observations (source tables retained verbatim)",
    "universities.jsonl": "universities + source_observations",
}

BRIDGE_TARGETS: dict[str, tuple[str, str]] = {
    "universities": ("university_evidence", "university_id"),
    "directions": ("direction_evidence", "direction_id"),
    "departments": ("department_evidence", "department_id"),
    "direction_departments": ("direction_department_evidence", "direction_department_id"),
    "educational_programs": ("program_evidence", "program_id"),
    "educational_program_departments": ("program_department_evidence", "program_department_id"),
    "catalog_courses": ("catalog_course_evidence", "course_id"),
    "study_plans": ("study_plan_evidence", "study_plan_id"),
    "curriculum_items": ("curriculum_evidence", "curriculum_item_id"),
    "admission_campaigns": ("campaign_evidence", "campaign_id"),
    "campaign_calendar_events": ("calendar_event_evidence", "calendar_event_id"),
    "funding_types": ("funding_type_evidence", "funding_type_id"),
    "quota_types": ("quota_type_evidence", "quota_type_id"),
    "admission_exams": ("exam_evidence", "exam_id"),
    "program_offerings": ("offering_evidence", "offering_id"),
    "competition_pools": ("competition_pool_evidence", "pool_id"),
    "competition_pool_offerings": ("pool_offering_evidence", "pool_offering_id"),
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
}


class BundleMappingError(ValueError):
    """The validated source rows cannot be represented safely in service tables."""


@dataclass(slots=True)
class MappingResult:
    release_id: UUID
    release_key: str
    input_digest: str
    validator_report: dict[str, Any]
    report: dict[str, Any]
    table_rows: dict[str, list[dict[str, Any]]]
    ids_by_table: dict[str, dict[str, UUID]]
    raw_file_hashes: dict[str, str]


def stable_uuid(release_id: UUID, table_name: str, external_key: str) -> UUID:
    """Create an internal repeatable ID; source identity remains the external key."""

    return uuid5(NAMESPACE_URL, f"academic-data:{release_id}:{table_name}:{external_key}")


def _short_external_key(prefix: str, value: str, limit: int = 512) -> str:
    combined = f"{prefix}:{value}"
    if len(combined) <= limit:
        return combined
    suffix = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return f"{combined[: limit - len(suffix) - 1]}:{suffix}"


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    raise BundleMappingError("expected a text-compatible value")


def _as_int(value: Any, field_name: str, *, required: bool = False) -> int | None:
    if value is None:
        if required:
            raise BundleMappingError(f"{field_name} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BundleMappingError(f"{field_name} must be an integer or null")
    return int(value)


def _as_bool(value: Any, field_name: str, *, required: bool = False) -> bool | None:
    if value is None:
        if required:
            raise BundleMappingError(f"{field_name} is required")
        return None
    if not isinstance(value, bool):
        raise BundleMappingError(f"{field_name} must be a boolean or null")
    return value


def _as_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise BundleMappingError(f"{field_name} must be numeric or null")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise BundleMappingError(f"{field_name} is not a valid decimal") from error
    if not result.is_finite():
        raise BundleMappingError(f"{field_name} must be finite")
    return result


def _as_date(value: Any, field_name: str) -> date | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise BundleMappingError(f"{field_name} must be an ISO date or null")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise BundleMappingError(f"{field_name} is not an ISO date") from error


def _as_time(value: Any, field_name: str) -> time | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise BundleMappingError(f"{field_name} must be an ISO time or null")
    try:
        return time.fromisoformat(value)
    except ValueError as error:
        raise BundleMappingError(f"{field_name} is not an ISO time") from error


def _as_datetime(value: Any, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise BundleMappingError(f"{field_name} must be an ISO datetime or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BundleMappingError(f"{field_name} is not an ISO datetime") from error
    if parsed.tzinfo is None:
        raise BundleMappingError(f"{field_name} must include its source timezone")
    return parsed


def _json_list(value: Any, field_name: str) -> list[Any] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise BundleMappingError(f"{field_name} must be a JSON array or null")
    return value


class _Projection:
    def __init__(
        self,
        release_id: UUID,
        release_key: str,
        input_digest: str,
        datasets: dict[str, list[tuple[int, dict[str, Any]]]],
        manifest: list[dict[str, Any]],
        manual_rows: list[dict[str, str]],
        confirmed_plan_links: list[dict[str, Any]],
        confirmed_plan_manifest: dict[str, Any] | None,
        validator_report: dict[str, Any],
        mapper_version: str,
    ) -> None:
        self.release_id = release_id
        self.release_key = release_key
        self.input_digest = input_digest
        self.datasets = datasets
        self.manifest = manifest
        self.manual_rows = manual_rows
        self.confirmed_plan_links = confirmed_plan_links
        self.confirmed_plan_manifest = confirmed_plan_manifest or {}
        self.validator_report = validator_report
        self.mapper_version = mapper_version
        self.reader_files: tuple[BundleFile, ...] = ()
        self.rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.ids: dict[str, dict[str, UUID]] = defaultdict(dict)
        self.aliases: dict[str, dict[str, UUID]] = defaultdict(dict)
        self.codes: dict[str, dict[str, list[UUID]]] = defaultdict(lambda: defaultdict(list))
        self.source_artifact_ids: dict[str, UUID] = {}
        self.dataset_target_ids: dict[str, dict[str, tuple[str, UUID]]] = defaultdict(dict)
        self.dataset_extra_target_ids: dict[str, dict[str, list[tuple[str, UUID]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self.relationship_association_targets: dict[str, list[tuple[str, UUID]]] = defaultdict(list)
        self.warnings: list[dict[str, Any]] = []
        self.unresolved: Counter[str] = Counter()
        self.typed_relation_counts: Counter[str] = Counter()
        self.requirement_operator_counts: Counter[str] = Counter()
        self.row_lookup: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.manual_review_records: dict[str, dict[str, str]] = {}

    def add(
        self,
        table_name: str,
        external_key: str,
        values: dict[str, Any],
        *,
        source_dataset: str | None = None,
        source_record_key: str | None = None,
    ) -> UUID:
        if external_key in self.ids[table_name]:
            raise BundleMappingError(
                f"duplicate projected key in {table_name}: {external_key[:120]}"
            )
        row_id = stable_uuid(self.release_id, table_name, external_key)
        row = {
            "id": row_id,
            "release_id": self.release_id,
            "external_key": external_key,
            **values,
        }
        self.rows[table_name].append(row)
        self.ids[table_name][external_key] = row_id
        if source_dataset is not None and source_record_key is not None:
            target = (table_name, row_id)
            original_target = self.dataset_target_ids[source_dataset].get(source_record_key)
            if original_target is None:
                self.dataset_target_ids[source_dataset][source_record_key] = target
            elif original_target != target:
                self.dataset_extra_target_ids[source_dataset][source_record_key].append(target)
            original_record = next(
                (
                    record
                    for _, record in self.datasets.get(source_dataset, [])
                    if record.get("external_key") == source_record_key
                ),
                None,
            )
            if original_record is not None:
                self.row_lookup[source_dataset][source_record_key] = original_record
        return row_id

    def alias(self, table_name: str, alias_key: str | None, row_id: UUID) -> None:
        if not alias_key:
            return
        current = self.aliases[table_name].get(alias_key)
        if current is not None and current != row_id:
            raise BundleMappingError(f"ambiguous exact source key alias for {table_name}")
        self.aliases[table_name][alias_key] = row_id

    def resolve(self, table_name: str, key: Any, *, required: bool = False) -> UUID | None:
        if key is None:
            if required:
                raise BundleMappingError(f"required {table_name} source key is null")
            return None
        if not isinstance(key, str):
            raise BundleMappingError(f"{table_name} source key must be text")
        found = self.ids[table_name].get(key) or self.aliases[table_name].get(key)
        if found is None and required:
            raise BundleMappingError(
                f"required exact {table_name} source key was not found: {key[:120]}"
            )
        return found

    def resolve_code(self, table_name: str, code: Any, *, field_name: str) -> UUID | None:
        if code is None:
            return None
        code_text = _as_text(code)
        assert code_text is not None
        matches = self.codes[table_name].get(code_text, [])
        if len(matches) == 1:
            return matches[0]
        self.unresolved[field_name] += 1
        if len(matches) > 1:
            self.warnings.append(
                {"code": "AMBIGUOUS_OFFICIAL_CODE", "field": field_name, "value": code_text}
            )
        return None

    def add_source_artifacts(self) -> None:
        for item in self.manifest:
            external_key = item["source_key"]
            raw_path = _as_text(item.get("raw_path"))
            if raw_path:
                path = PurePosixPath(raw_path)
                if path.is_absolute() or ".." in path.parts or "\\" in raw_path:
                    raise BundleMappingError("source manifest raw_path must be relative and safe")
            artifact_id = self.add(
                "source_artifacts",
                external_key,
                {
                    "source_type": _as_text(item.get("source_type")),
                    "requested_url": _as_text(item.get("requested_url")),
                    "final_url": _as_text(item.get("final_url")),
                    "fetched_at": _as_datetime(item.get("retrieved_at"), "retrieved_at"),
                    "sha256": _as_text(item.get("sha256")),
                    "content_type": _as_text(item.get("content_type")),
                    "byte_size": _as_int(item.get("byte_size"), "byte_size"),
                    "status_code": _as_int(item.get("status_code"), "status_code"),
                    "raw_path": raw_path,
                    "storage_status": _as_text(item.get("storage_status")) or "unavailable",
                    "note": _as_text(item.get("note")),
                },
                source_dataset="source_artifacts.jsonl",
                source_record_key=external_key,
            )
            self.source_artifact_ids[external_key] = artifact_id

    def add_row_observations(
        self, dataset_name: str, rows: list[tuple[int, dict[str, Any]]]
    ) -> None:
        for _, record in rows:
            source_key = record.get("external_key") or record.get("source_key")
            if not isinstance(source_key, str):
                raise BundleMappingError(f"{dataset_name} has no stable external_key")
            artifact_key = record.get("source_artifact_key")
            artifact_id = self.resolve("source_artifacts", artifact_key)
            observation_key = _short_external_key("observation", f"{dataset_name}:{source_key}")
            observation_id = self.add(
                "source_observations",
                observation_key,
                {
                    "dataset_name": dataset_name.removesuffix(".jsonl"),
                    "payload": record,
                    "source_artifact_id": artifact_id,
                },
            )
            self.dataset_target_ids[f"source:{dataset_name}"][source_key] = (
                "source_observations",
                observation_id,
            )

    def _source_datetime(self, record: dict[str, Any]) -> datetime | None:
        return _as_datetime(
            record.get("source_retrieved_at") or record.get("retrieved_at"),
            "source_retrieved_at",
        )

    def add_university_and_catalog(self) -> None:
        for _, record in self.datasets.get("universities.jsonl", []):
            row_id = self.add(
                "universities",
                record["external_key"],
                {
                    "official_code": _as_text(record.get("code")),
                    "name": record["name"],
                    "city": _as_text(record.get("city")),
                    "official_site": _as_text(record.get("official_site")),
                    "identity_source_note": _as_text(record.get("identity_source_note")),
                },
                source_dataset="universities.jsonl",
                source_record_key=record["external_key"],
            )
            self.codes["universities"][_as_text(record.get("code")) or ""].append(row_id)

        for dataset, table_name, mapper in (
            ("directions.jsonl", "directions", self._direction_values),
            ("departments.jsonl", "departments", self._department_values),
        ):
            for _, record in self.datasets.get(dataset, []):
                row_id = self.add(
                    table_name,
                    record["external_key"],
                    mapper(record),
                    source_dataset=dataset,
                    source_record_key=record["external_key"],
                )
                code = _as_text(record.get("code"))
                if code:
                    self.codes[table_name][code].append(row_id)

        for _, record in self.datasets.get("educational_programs.jsonl", []):
            direction_id = self.resolve("directions", record.get("direction_key"), required=True)
            source_campus = _as_text(record.get("campus_scope"))
            campus = (
                source_campus if source_campus in {"head_moscow", "other", "unknown"} else "unknown"
            )
            row_id = self.add(
                "educational_programs",
                record["external_key"],
                {
                    "direction_id": direction_id,
                    "code": record["code"],
                    "source_code": _as_text(record.get("source_code")),
                    "name": record["name"],
                    "description": _as_text(record.get("description")),
                    "campus_scope": campus,
                    "catalog_course_names": _json_list(
                        record.get("catalog_course_names"), "catalog_course_names"
                    ),
                    "catalog_page_url": _as_text(record.get("catalog_page_url")),
                    "study_plan_url": _as_text(record.get("study_plan_url")),
                    "source_card_position": _json_list(
                        record.get("source_card_position"), "source_card_position"
                    ),
                },
                source_dataset="educational_programs.jsonl",
                source_record_key=record["external_key"],
            )
            self.codes["educational_programs"][record["code"]].append(row_id)
            if source_campus == "unverified":
                self.warnings.append(
                    {
                        "code": "PROGRAM_CAMPUS_UNVERIFIED",
                        "external_key": record["external_key"],
                        "typed_scope": "unknown",
                    }
                )

    def _direction_values(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "university_id": self.resolve(
                "universities", record.get("university_key"), required=True
            ),
            "code": record["code"],
            "name": record["name"],
            "description": _as_text(record.get("description")),
            "degree_label": _as_text(record.get("degree_label_catalog")),
            "duration_label": _as_text(record.get("duration_label_catalog")),
            "duration_months": _as_int(record.get("duration_months"), "duration_months"),
            "qualification_label": _as_text(record.get("qualification_label")),
            "catalog_course_names": _json_list(
                record.get("catalog_course_names"), "catalog_course_names"
            ),
            "catalog_page_url": _as_text(record.get("catalog_page_url")),
        }

    def _department_values(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "university_id": self.resolve(
                "universities", record.get("university_key"), required=True
            ),
            "official_code": _as_text(record.get("code")),
            "name": record["name"],
            "description": _as_text(record.get("description")),
            "faculty_name": _as_text(record.get("faculty_name")),
            "address": _as_text(record.get("address")),
            "campus_scope": _as_text(record.get("campus_scope")),
        }

    def add_admission_dimensions(self) -> None:
        for dataset, table_name in (
            ("funding_types.jsonl", "funding_types"),
            ("quota_types.jsonl", "quota_types"),
            ("exams.jsonl", "admission_exams"),
        ):
            for _, record in self.datasets.get(dataset, []):
                code = _as_text(record.get("code"))
                row_id = self.add(
                    table_name,
                    record["external_key"],
                    {"code": code, "name": record["name"]},
                    source_dataset=dataset,
                    source_record_key=record["external_key"],
                )
                if code:
                    self.codes[table_name][code].append(row_id)

    def add_campaigns_and_catalog_details(self) -> None:
        for _, record in self.datasets.get("admission_campaigns.jsonl", []):
            campaign_id = self.add(
                "admission_campaigns",
                record["external_key"],
                {
                    "university_id": self.resolve(
                        "universities", record.get("university_key"), required=True
                    ),
                    "year": _as_int(record.get("year"), "year", required=True),
                    "education_level": None,
                    "campaign_kind": "admission",
                    "title": _as_text(record.get("title")) or "",
                    "date_note": _as_text(record.get("date_note")),
                },
                source_dataset="admission_campaigns.jsonl",
                source_record_key=record["external_key"],
            )
            self.alias("admission_campaigns", f"campaign:bmstu:{record.get('year')}", campaign_id)

        for _, record in self.datasets.get("courses.jsonl", []):
            program_id = self.resolve(
                "educational_programs", record.get("profile_key"), required=True
            )
            self.add(
                "catalog_courses",
                record["external_key"],
                {
                    "program_id": program_id,
                    "name": record["name"],
                    "description": _as_text(record.get("description")),
                    "description_status": _as_text(record.get("description_status")),
                },
                source_dataset="courses.jsonl",
                source_record_key=record["external_key"],
            )

        confirmed_plan_pairs = {
            (item.get("program_external_key"), item.get("study_plan_url"))
            for item in self.confirmed_plan_links
        }
        explicit_plan_links = {
            (record.get("source_key"), record.get("target_key"))
            for _, record in self.datasets.get("relationships.jsonl", [])
            if record.get("relation_type") == "profile_has_profile_specific_curriculum"
        }
        for _, record in self.datasets.get("study_plans.jsonl", []):
            program_key = _as_text(record.get("program_key"))
            program_id = self.resolve("educational_programs", program_key)
            status_in_source = _as_text(record.get("status")) or ""
            if status_in_source in {
                "parsed_and_profile_identity_verified",
                "parsed_via_user_confirmed_catalog_link",
            }:
                status = "parsed"
            elif status_in_source in {
                "linked_public_resource_has_no_file",
                "public_plan_metadata_unavailable",
            }:
                status = "unavailable"
            else:
                status = "unverified"
            is_confirmed = (program_key, record.get("study_plan_url")) in confirmed_plan_pairs or (
                program_key,
                record["external_key"],
            ) in explicit_plan_links
            if program_id is None:
                profile_link_status = "unresolved"
                self.unresolved["study_plan_program"] += 1
            elif is_confirmed:
                profile_link_status = "verified"
            elif status == "unverified":
                profile_link_status = "manual_review"
            else:
                profile_link_status = "unverified"
            totals = record.get("overall_academic")
            if not isinstance(totals, dict):
                totals = {}
            astronomy = record.get("overall_astronomical")
            if not isinstance(astronomy, dict):
                astronomy = {}
            self.add(
                "study_plans",
                record["external_key"],
                {
                    "program_id": program_id,
                    "profile_link_status": profile_link_status,
                    "status": status,
                    "education_year": _as_int(record.get("education_year"), "education_year"),
                    "start_year": _as_int(record.get("start_year"), "start_year"),
                    "version_label": _as_text(record.get("source_version")),
                    "source_version": _as_text(record.get("source_version")),
                    "profile_code": _as_text(record.get("profile_code")),
                    "header_profile_code": _as_text(record.get("header_profile_code")),
                    "profile_name_in_plan": _as_text(record.get("profile_name_in_plan")),
                    "study_form": _as_text(record.get("study_form")),
                    "duration_label": _as_text(record.get("duration")),
                    "semester_count": _as_int(record.get("semester_count"), "semester_count"),
                    "total_academic_hours": _as_int(totals.get("total_hours"), "total_hours"),
                    "total_astronomical_hours": _as_int(
                        astronomy.get("total_hours"), "total_astronomical_hours"
                    ),
                    "semester_totals": _json_list(record.get("semester_totals"), "semester_totals"),
                    "document_url": _as_text(record.get("document_url")),
                    "download_url": _as_text(record.get("download_url")),
                    "study_plan_url": _as_text(record.get("study_plan_url")),
                    "unavailable_reason": _as_text(record.get("error")),
                },
                source_dataset="study_plans.jsonl",
                source_record_key=record["external_key"],
            )

        curriculum_ordinals: Counter[str] = Counter()
        for _, record in self.datasets.get("curriculum_items.jsonl", []):
            plan_key = _as_text(record.get("curriculum_key"))
            plan_id = self.resolve("study_plans", plan_key, required=True)
            curriculum_ordinals[plan_key or ""] += 1
            self.add(
                "curriculum_items",
                record["external_key"],
                {
                    "study_plan_id": plan_id,
                    "ordinal": curriculum_ordinals[plan_key or ""],
                    "record_type": _as_text(record.get("record_type")),
                    "is_data_row": _as_bool(record.get("is_data_row"), "is_data_row"),
                    "source_record_id": _as_text(record.get("record_id")),
                    "discipline_name": _as_text(record.get("discipline")),
                    "course_number": _as_int(record.get("course"), "course"),
                    "semester": _as_int(record.get("semester"), "semester"),
                    "credits": _as_decimal(record.get("credits"), "credits"),
                    "hours": _as_int(record.get("hours"), "hours"),
                    "lecture_hours": _as_int(record.get("lectures"), "lectures"),
                    "practice_hours": _as_int(record.get("practices"), "practices"),
                    "lab_hours": _as_int(record.get("labs"), "labs"),
                    "self_study_hours": _as_int(record.get("self_study"), "self_study"),
                    "total_hours": _as_int(record.get("total_hours"), "total_hours"),
                    "total_lecture_hours": _as_int(record.get("total_lectures"), "total_lectures"),
                    "total_practice_hours": _as_int(
                        record.get("total_practices"), "total_practices"
                    ),
                    "total_lab_hours": _as_int(record.get("total_labs"), "total_labs"),
                    "total_self_study_hours": _as_int(
                        record.get("total_self_study"), "total_self_study"
                    ),
                    "audited_hours": _as_int(record.get("audited_hours"), "audited_hours"),
                    "audited_hours_semester": _as_int(
                        record.get("audited_hours_semester"), "audited_hours_semester"
                    ),
                    "semester_weeks": _as_int(record.get("semester_weeks"), "semester_weeks"),
                    "assessment_type": _as_text(record.get("assessment_type")),
                    "education_form": _as_text(record.get("form")),
                    "duration_label": _as_text(record.get("duration")),
                    "qualification_label": _as_text(record.get("qualification")),
                    "department_name": _as_text(record.get("department")),
                    "faculty_name": _as_text(record.get("faculty")),
                    "chair_name": _as_text(record.get("chair")),
                    "source_row": None,
                    "source_document_url": _as_text(record.get("source_document_url")),
                    "study_plan_url": _as_text(record.get("study_plan_url")),
                    "download_url": _as_text(record.get("download_url")),
                    "source_observed_at": _as_datetime(record.get("observed_at"), "observed_at"),
                },
                source_dataset="curriculum_items.jsonl",
                source_record_key=record["external_key"],
            )

    def add_admission_facts(self) -> None:
        for _, record in self.datasets.get("campaign_dates.jsonl", []):
            year = _as_int(record.get("campaign_year"), "campaign_year", required=True)
            campaign_id = self.resolve(
                "admission_campaigns", f"campaign:bmstu:{year}", required=True
            )
            date_text = _as_text(record.get("date_text"))
            label = (
                date_text or _as_text(record.get("date")) or _as_text(record.get("context")) or ""
            )
            self.add(
                "campaign_calendar_events",
                record["external_key"],
                {
                    "campaign_id": campaign_id,
                    "event_code": None,
                    "label": label,
                    "context": _as_text(record.get("context")),
                    "date_value": _as_date(record.get("date"), "date"),
                    "time_value": _as_time(record.get("time"), "time"),
                    "starts_at": None,
                    "ends_at": None,
                    "date_text": date_text,
                },
                source_dataset="campaign_dates.jsonl",
                source_record_key=record["external_key"],
            )

        for _, record in self.datasets.get("program_offerings.jsonl", []):
            campaign_id = self.resolve(
                "admission_campaigns", record.get("campaign_key"), required=True
            )
            direction_id = self.resolve("directions", record.get("direction_key"))
            program_key = _as_text(record.get("educational_program_key"))
            program_id = self.resolve("educational_programs", program_key)
            department_id = self.resolve("departments", record.get("department_key"))
            if program_key and program_id is None:
                self.unresolved["program_offerings_program"] += 1
            if record.get("department_key") and department_id is None:
                self.unresolved["program_offerings_department"] += 1
            self.add(
                "program_offerings",
                record["external_key"],
                {
                    "campaign_id": campaign_id,
                    "direction_id": direction_id,
                    "direction_code": _as_text(record.get("direction_code")),
                    "program_id": program_id,
                    "department_id": department_id,
                    "department_code": _as_text(record.get("department_code")),
                    "year": _as_int(record.get("campaign_year"), "campaign_year", required=True),
                    "study_form": _as_text(record.get("study_form")),
                    "language": _as_text(record.get("language")),
                    "study_duration_label": _as_text(record.get("study_duration_label")),
                    "program_name_in_document": _as_text(record.get("program_name_in_document")),
                    "campus_scope": _as_text(record.get("campus_scope")),
                    "catalog_join_status": _as_text(record.get("catalog_join_status")),
                    "source_locator": record.get("source_locator"),
                    "source_row": record.get("source_row"),
                },
                source_dataset="program_offerings.jsonl",
                source_record_key=record["external_key"],
            )

        for _, record in self.datasets.get("competition_pools.jsonl", []):
            year = _as_int(record.get("campaign_year"), "campaign_year", required=True)
            campaign_id = self.resolve(
                "admission_campaigns",
                record.get("linked_campaign_key") or f"campaign:bmstu:{year}",
                required=True,
            )
            direction_id = self.resolve_code(
                "directions", record.get("direction_code"), field_name="competition_pool_direction"
            )
            department_id = self.resolve_code(
                "departments",
                record.get("department_code"),
                field_name="competition_pool_department",
            )
            funding_code = _as_text(record.get("funding_type"))
            quota_code = _as_text(record.get("quota_type"))
            self.add(
                "competition_pools",
                record["external_key"],
                {
                    "campaign_id": campaign_id,
                    "direction_id": direction_id,
                    "department_id": department_id,
                    "direction_code": _as_text(record.get("direction_code")),
                    "department_code": _as_text(record.get("department_code")),
                    "funding_type_id": self.resolve_code(
                        "funding_types", funding_code, field_name="competition_pool_funding_type"
                    ),
                    "quota_type_id": self.resolve_code(
                        "quota_types", quota_code, field_name="competition_pool_quota_type"
                    ),
                    "year": year,
                    "funding_type_code": funding_code,
                    "quota_type_code": quota_code,
                    "scope_level": _as_text(record.get("scope_level")),
                    "places": _as_int(record.get("places"), "places"),
                    "places_by_source_row": _json_list(
                        record.get("places_by_source_row"), "places_by_source_row"
                    ),
                    "source_locators": _json_list(record.get("source_locators"), "source_locators"),
                    "valid_from": None,
                    "valid_to": None,
                    "observed_at": self._source_datetime(record),
                },
                source_dataset="competition_pools.jsonl",
                source_record_key=record["external_key"],
            )

        for _, record in self.datasets.get("admission_exam_requirements.jsonl", []):
            campaign_id = self.resolve(
                "admission_campaigns", record.get("campaign_key"), required=True
            )
            direction_id = self.resolve("directions", record.get("direction_key"))
            requirement_id = self.add(
                "admission_requirement_sets",
                record["external_key"],
                {
                    "campaign_id": campaign_id,
                    "direction_id": direction_id,
                    "direction_code": _as_text(record.get("direction_code")),
                    "applicant_category_text": _as_text(record.get("applicant_category_text")),
                    "validation": record.get("validation"),
                    "raw_requirement_tree": record.get("requirement_tree"),
                    "source_locator": record.get("source_locator"),
                    "valid_from": None,
                    "valid_to": None,
                    "observed_at": self._source_datetime(record),
                },
                source_dataset="admission_exam_requirements.jsonl",
                source_record_key=record["external_key"],
            )
            self.alias(
                "admission_requirement_sets",
                _as_text(record.get("requirement_set_key")),
                requirement_id,
            )
            self._add_requirement_tree(record, requirement_id)

        for _, record in self.datasets.get("tuition.jsonl", []):
            amount = record.get("annual_amount_rub")
            self.add(
                "tuition_assertions",
                record["external_key"],
                {
                    "direction_id": self.resolve("directions", record.get("direction_key")),
                    "direction_code": _as_text(record.get("direction_code")),
                    "direction_name": _as_text(record.get("direction_name")),
                    "amount": _as_decimal(amount, "annual_amount_rub"),
                    "currency": _as_text(record.get("currency")),
                    "academic_year_label": _as_text(record.get("study_year_label")),
                    "table_category": _as_text(record.get("study_level_or_table_category")),
                    "campus_scope": _as_text(record.get("campus_scope")),
                    "raw_cells": _json_list(record.get("raw_cells"), "raw_cells"),
                    "source_locator": record.get("source_locator"),
                    "valid_from": None,
                    "valid_to": None,
                    "observed_at": self._source_datetime(record),
                },
                source_dataset="tuition.jsonl",
                source_record_key=record["external_key"],
            )

        for _, record in self.datasets.get("historical_admission_statistics.jsonl", []):
            funding_code = _as_text(record.get("funding_type"))
            self.add(
                "historical_admission_statistics",
                record["external_key"],
                {
                    "direction_id": self.resolve("directions", record.get("direction_key")),
                    "department_id": self.resolve("departments", record.get("department_key")),
                    "direction_code": _as_text(record.get("direction_code")),
                    "department_code": _as_text(record.get("department_code")),
                    "funding_type_id": self.resolve_code(
                        "funding_types",
                        funding_code,
                        field_name="historical_statistic_funding_type",
                    ),
                    "admission_year": _as_int(
                        record.get("admission_year"), "admission_year", required=True
                    ),
                    "outcome_type": record["outcome_type"],
                    "scope_type": _as_text(record.get("scope_type")),
                    "scope_label": _as_text(record.get("scope_label")),
                    "funding_type_code": funding_code,
                    "study_form": _as_text(record.get("study_form")),
                    "admitted_count": _as_int(record.get("admitted_count"), "admitted_count"),
                    "minimum_score": _as_decimal(record.get("minimum_score"), "minimum_score"),
                    "maximum_score": _as_decimal(record.get("maximum_score"), "maximum_score"),
                    "average_score": _as_decimal(record.get("average_score"), "average_score"),
                    "campus_scope": _as_text(record.get("campus_scope")),
                    "snapshot_date": _as_date(record.get("snapshot_date"), "snapshot_date"),
                    "finality_note": _as_text(record.get("finality_note")),
                    "source_locator": record.get("source_locator"),
                    "valid_from": None,
                    "valid_to": None,
                    "observed_at": self._source_datetime(record),
                },
                source_dataset="historical_admission_statistics.jsonl",
                source_record_key=record["external_key"],
            )

        for _, record in self.datasets.get("admission_statistics.jsonl", []):
            funding_code = _as_text(record.get("funding_type"))
            self.add(
                "admission_statistics",
                record["external_key"],
                {
                    "direction_id": self.resolve_code(
                        "directions",
                        record.get("direction_code"),
                        field_name="admission_statistic_direction",
                    ),
                    "direction_code": _as_text(record.get("direction_code")),
                    "funding_type_id": self.resolve_code(
                        "funding_types", funding_code, field_name="admission_statistic_funding_type"
                    ),
                    "admission_year": _as_int(
                        record.get("admission_year"), "admission_year", required=True
                    ),
                    "admission_stage": _as_text(record.get("admission_stage")),
                    "competition_type": _as_text(record.get("competition_type")),
                    "funding_type_code": funding_code,
                    "score": _as_decimal(record.get("score"), "score"),
                    "status": _as_text(record.get("status")),
                    "study_form": _as_text(record.get("study_form")),
                    "snapshot_date": _as_date(record.get("snapshot_date"), "snapshot_date"),
                    "source_locator": record.get("source_locator"),
                    "valid_from": None,
                    "valid_to": None,
                    "observed_at": self._source_datetime(record),
                },
                source_dataset="admission_statistics.jsonl",
                source_record_key=record["external_key"],
            )

        for _, record in self.datasets.get("individual_achievement_policies.jsonl", []):
            campaign_key = _as_text(record.get("campaign_key"))
            self.add(
                "individual_achievement_policies",
                record["external_key"],
                {
                    "campaign_id": self.resolve("admission_campaigns", campaign_key),
                    "campaign_year": _as_int(record.get("campaign_year"), "campaign_year"),
                    "achievement_name": record["achievement_name"],
                    "additional_points": _as_decimal(
                        record.get("additional_points"), "additional_points"
                    ),
                    "required_document": _as_text(record.get("required_document")),
                    "row_number": _as_int(record.get("row_number"), "row_number"),
                    "source_locator": record.get("source_locator"),
                    "valid_from": None,
                    "valid_to": None,
                    "observed_at": self._source_datetime(record),
                },
                source_dataset="individual_achievement_policies.jsonl",
                source_record_key=record["external_key"],
            )

        self.add_documents_and_result_sources()

    def _add_requirement_tree(self, record: dict[str, Any], requirement_id: UUID) -> None:
        tree = record.get("requirement_tree")
        if not isinstance(tree, dict):
            raise BundleMappingError("requirement_tree must be an object")

        def add_node(node: dict[str, Any], path: str, ordinal: int, parent_id: UUID | None) -> None:
            node_key = _short_external_key("requirement-node", f"{record['external_key']}:{path}")
            children = node.get("children")
            if isinstance(children, list):
                operator = node.get("operator")
                if operator not in {"AND", "OR", "AT_LEAST"}:
                    raise BundleMappingError("requirement tree contains an unsupported operator")
                min_count = _as_int(node.get("min_count"), "min_count")
                if operator == "AT_LEAST" and min_count is None:
                    raise BundleMappingError("AT_LEAST requirement node has no min_count")
                self.requirement_operator_counts[operator] += 1
                node_id = self.add(
                    "admission_requirement_nodes",
                    node_key,
                    {
                        "requirement_set_id": requirement_id,
                        "parent_id": parent_id,
                        "ordinal": ordinal,
                        "path_key": path,
                        "node_kind": "operator",
                        "operator": operator,
                        "min_count": min_count,
                        "exam_id": None,
                        "subject_code": None,
                        "minimum_score": None,
                        "is_choice": None,
                        "tiebreak_rank": None,
                    },
                    source_dataset="admission_exam_requirements.jsonl",
                    source_record_key=record["external_key"],
                )
                for child_index, child in enumerate(children):
                    if not isinstance(child, dict):
                        raise BundleMappingError("requirement child must be an object")
                    add_node(child, f"{path}.children[{child_index}]", child_index, node_id)
                return

            exam = node.get("exam")
            if not isinstance(exam, dict):
                raise BundleMappingError("requirement leaf must contain an exam object")
            exam_id = self.resolve("admission_exams", exam.get("exam_key"), required=True)
            self.add(
                "admission_requirement_nodes",
                node_key,
                {
                    "requirement_set_id": requirement_id,
                    "parent_id": parent_id,
                    "ordinal": ordinal,
                    "path_key": path,
                    "node_kind": "exam",
                    "operator": None,
                    "min_count": None,
                    "exam_id": exam_id,
                    "subject_code": _as_text(exam.get("subject_code")),
                    "minimum_score": _as_decimal(exam.get("minimum_score"), "minimum_score"),
                    "is_choice": _as_bool(exam.get("is_choice"), "is_choice"),
                    "tiebreak_rank": _as_text(exam.get("tiebreak_rank")),
                },
                source_dataset="admission_exam_requirements.jsonl",
                source_record_key=record["external_key"],
            )

        add_node(tree, "$", 0, None)

    def add_documents_and_result_sources(self) -> None:
        for _, record in self.datasets.get("admission_documents.jsonl", []):
            self.add(
                "admission_documents",
                record["external_key"],
                {
                    "document_id": _as_int(record.get("document_id"), "document_id"),
                    "title": record["title"],
                    "document_group": _as_text(record.get("group")),
                    "scope_tag": _as_text(record.get("scope_tag")),
                    "captured": _as_bool(record.get("captured"), "captured", required=True),
                },
                source_dataset="admission_documents.jsonl",
                source_record_key=record["external_key"],
            )
        for _, record in self.datasets.get("admission_document_pages.jsonl", []):
            self.add(
                "admission_document_pages",
                record["external_key"],
                {
                    "document_id_fk": self.resolve(
                        "admission_documents", record.get("document_key"), required=True
                    ),
                    "page_number": _as_int(record.get("page"), "page", required=True),
                    "title": _as_text(record.get("title")),
                    "page_text": _as_text(record.get("text")),
                },
                source_dataset="admission_document_pages.jsonl",
                source_record_key=record["external_key"],
            )
        for _, record in self.datasets.get("admission_result_sources.jsonl", []):
            self.add(
                "admission_result_sources",
                record["external_key"],
                {
                    "title": _as_text(record.get("title")),
                    "classification": (
                        _as_text(record["classification"].get("document_kind"))
                        if isinstance(record.get("classification"), dict)
                        else _as_text(record.get("classification"))
                    ),
                    "source_url": _as_text(record.get("source_url")),
                    "retrieved_at": _as_datetime(record.get("retrieved_at"), "retrieved_at"),
                    "sha256": _as_text(record.get("sha256")),
                    "stored": _as_bool(record.get("stored"), "stored", required=True),
                    "omission_reason": _as_text(record.get("omission_reason")),
                },
                source_dataset="admission_result_sources.jsonl",
                source_record_key=record["external_key"],
            )

    def add_manual_reviews(self) -> None:
        for row in self.manual_rows:
            identity = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            external_key = (
                f"manual_review:sha256:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
            )
            record_key = _as_text(row.get("record_key"))
            artifact_id = self.resolve("source_artifacts", record_key)
            source_url = _as_text(row.get("source_url"))
            details = _as_text(row.get("details"))
            review_id = self.add(
                "manual_review_items",
                external_key,
                {
                    "status": "open",
                    "issue_code": (_as_text(row.get("issue_type")) or "unclassified")[:100],
                    "subject_type": record_key.split(":", 1)[0] if record_key else None,
                    "subject_key": record_key,
                    "source_key": record_key,
                    "target_key": None,
                    "candidate_keys": None,
                    "summary": details or (_as_text(row.get("issue_type")) or "Manual review item"),
                    "source_artifact_id": artifact_id,
                    "source_locator": {"source_url": source_url, "csv_record_key": record_key},
                },
                source_dataset="manual_review.csv",
                source_record_key=external_key,
            )
            self.manual_review_records[external_key] = row
            if artifact_id is not None:
                self.dataset_target_ids["manual_review.csv"][external_key] = (
                    "manual_review_items",
                    review_id,
                )

    def add_source_relationships_and_typed_links(self) -> None:
        relationship_rows = self.datasets.get("relationships.jsonl", [])
        for _, record in relationship_rows:
            source_artifact_id = self.resolve("source_artifacts", record.get("source_artifact_key"))
            self.add(
                "source_relationships",
                record["external_key"],
                {
                    "relation_type": record["relation_type"],
                    "source_key": record["source_key"],
                    "target_key": record["target_key"],
                    "evidence_kind": _as_text(record.get("evidence_kind")),
                    "source_artifact_id": source_artifact_id,
                    "source_url": _as_text(record.get("source_url")),
                    "source_locator": record.get("source_locator"),
                },
                source_dataset="relationships.jsonl",
                source_record_key=record["external_key"],
            )
            self.row_lookup["relationships.jsonl"][record["external_key"]] = record

        pair_ids: dict[tuple[str, str, str], UUID] = {}
        typed_requirement_pairs: dict[tuple[str, str], UUID] = {}
        for _, record in relationship_rows:
            relation_type = record["relation_type"]
            source_key = record["source_key"]
            target_key = record["target_key"]
            association_table: str | None = None
            association_target: str | None = None
            association_values: dict[str, Any] | None = None
            if relation_type == "direction_has_department":
                direction_id = self.resolve("directions", source_key)
                department_id = self.resolve("departments", target_key)
                if direction_id is not None and department_id is not None:
                    association_table = "direction_departments"
                    association_target = "direction_department_id"
                    association_values = {
                        "direction_id": direction_id,
                        "department_id": department_id,
                        "relation_type": None,
                        "source_relation_type": relation_type,
                    }
                    pair = (association_table, source_key, target_key)
                    association_key = _short_external_key(
                        "direction-department", f"{source_key}:{target_key}"
                    )
                    self.typed_relation_counts[relation_type] += 1
                else:
                    self.unresolved[relation_type] += 1
            elif relation_type == "profile_is_issued_by_department":
                program_id = self.resolve("educational_programs", source_key)
                department_id = self.resolve("departments", target_key)
                if program_id is not None and department_id is not None:
                    association_table = "educational_program_departments"
                    association_target = "program_department_id"
                    association_values = {
                        "program_id": program_id,
                        "department_id": department_id,
                        "relation_type": None,
                        "verification_status": "verified",
                        "source_relation_type": relation_type,
                    }
                    pair = (association_table, source_key, target_key)
                    association_key = _short_external_key(
                        "program-department", f"{source_key}:{target_key}"
                    )
                    self.typed_relation_counts[relation_type] += 1
                else:
                    self.unresolved[relation_type] += 1
            elif relation_type == "offering_competes_in_pool":
                offering_id = self.resolve("program_offerings", source_key)
                pool_id = self.resolve("competition_pools", target_key)
                if offering_id is not None and pool_id is not None:
                    association_table = "competition_pool_offerings"
                    association_target = "pool_offering_id"
                    association_values = {"offering_id": offering_id, "pool_id": pool_id}
                    pair = (association_table, source_key, target_key)
                    association_key = _short_external_key(
                        "pool-offering", f"{source_key}:{target_key}"
                    )
                    self.typed_relation_counts[relation_type] += 1
                else:
                    self.unresolved[relation_type] += 1
            elif relation_type in {
                "offering_has_exam_requirement_for_direction",
                "offering_has_direction_exam_requirement",
            }:
                offering_id = self.resolve("program_offerings", source_key)
                requirement_id = self.resolve("admission_requirement_sets", target_key)
                if offering_id is not None and requirement_id is not None:
                    association_table = "offering_requirement_links"
                    association_target = "link_id"
                    association_values = {
                        "offering_id": offering_id,
                        "requirement_set_id": requirement_id,
                        "relation_type": relation_type,
                    }
                    pair = (association_table, source_key, target_key)
                    association_key = _short_external_key(
                        "offering-requirement", f"{source_key}:{target_key}"
                    )
                    self.typed_relation_counts[relation_type] += 1
                else:
                    self.unresolved[relation_type] += 1
            else:
                continue

            if (
                association_table is None
                or association_values is None
                or association_target is None
            ):
                continue
            if association_table == "offering_requirement_links":
                pair_key = (source_key, target_key)
                if pair_key in typed_requirement_pairs:
                    existing_id = typed_requirement_pairs[pair_key]
                    self.relationship_association_targets[record["external_key"]].append(
                        (association_table, existing_id)
                    )
                    continue
                typed_requirement_pairs[pair_key] = stable_uuid(
                    self.release_id, association_table, association_key
                )
            else:
                pair_key_full = (association_table, source_key, target_key)
                if pair_key_full in pair_ids:
                    self.relationship_association_targets[record["external_key"]].append(
                        (association_table, pair_ids[pair_key_full])
                    )
                    continue
            association_id = self.add(
                association_table,
                association_key,
                association_values,
            )
            self.relationship_association_targets[record["external_key"]].append(
                (association_table, association_id)
            )
            if association_table != "offering_requirement_links":
                pair_ids[pair] = association_id

    def add_confirmed_plan_observations(self) -> None:
        manifest_key = "confirmed-study-plan-link-manifest"
        self.add(
            "source_observations",
            manifest_key,
            {
                "dataset_name": "user_confirmed_study_plan_links_manifest",
                "payload": {
                    key: value
                    for key, value in self.confirmed_plan_manifest.items()
                    if key != "links"
                },
                "source_artifact_id": None,
            },
        )
        for record in self.confirmed_plan_links:
            program_key = _as_text(record.get("program_external_key"))
            if not program_key:
                raise BundleMappingError("confirmed study plan link lacks program_external_key")
            artifact_key = _as_text(record.get("catalog_card_artifact_key"))
            external_key = _short_external_key("confirmed-study-plan-link", program_key)
            if external_key in self.ids["source_observations"]:
                raise BundleMappingError("confirmed study-plan link key is duplicated")
            self.add(
                "source_observations",
                external_key,
                {
                    "dataset_name": "user_confirmed_study_plan_links",
                    "payload": record,
                    "source_artifact_id": self.resolve("source_artifacts", artifact_key),
                },
            )

    def add_evidence_and_bridges(self) -> None:
        for dataset_name, rows in self.datasets.items():
            for line_number, record in rows:
                source_key = record.get("external_key")
                targets: list[tuple[str, UUID]] = []
                target = self.dataset_target_ids.get(dataset_name, {}).get(str(source_key))
                if target is not None:
                    targets.append(target)
                targets.extend(
                    self.dataset_extra_target_ids.get(dataset_name, {}).get(str(source_key), [])
                )
                if dataset_name == "relationships.jsonl":
                    targets.extend(self.relationship_association_targets.get(str(source_key), []))
                artifact_keys: list[str] = []
                singular = record.get("source_artifact_key")
                if isinstance(singular, str):
                    artifact_keys.append(singular)
                plural = record.get("source_artifact_keys")
                if isinstance(plural, list):
                    artifact_keys.extend(value for value in plural if isinstance(value, str))
                seen_artifacts: set[str] = set()
                for artifact_key in artifact_keys:
                    if artifact_key in seen_artifacts:
                        continue
                    seen_artifacts.add(artifact_key)
                    artifact_id = self.source_artifact_ids.get(artifact_key)
                    if artifact_id is None:
                        continue
                    evidence_key = _short_external_key(
                        "evidence", f"{dataset_name}:{source_key}:{artifact_key}"
                    )
                    evidence_id = self.add(
                        "source_evidence",
                        evidence_key,
                        {
                            "source_artifact_id": artifact_id,
                            "field_path": f"data/{dataset_name}#L{line_number}",
                            "locator": record.get("source_locator"),
                            "quoted_fragment": None,
                            "claim": f"Source record preserved from {dataset_name}",
                            "observed_at": self._source_datetime(record),
                            "verification_status": "source_backed",
                        },
                    )
                    for table_name, target_id in targets:
                        bridge_info = BRIDGE_TARGETS.get(table_name)
                        if bridge_info is None:
                            continue
                        bridge_table, target_field = bridge_info
                        bridge_key = _short_external_key(
                            "evidence-target", f"{evidence_key}:{table_name}:{target_id}"
                        )
                        bridge_id = stable_uuid(self.release_id, bridge_table, bridge_key)
                        self.rows[bridge_table].append(
                            {
                                "id": bridge_id,
                                "release_id": self.release_id,
                                "external_key": bridge_key,
                                "evidence_id": evidence_id,
                                target_field: target_id,
                            }
                        )
        for review_key, row in self.manual_review_records.items():
            review_id = self.resolve("manual_review_items", review_key)
            artifact_id = self.resolve("source_artifacts", row.get("record_key"))
            if review_id is None or artifact_id is None:
                continue
            evidence_key = _short_external_key(
                "evidence", f"manual_review.csv:{review_key}:{artifact_id}"
            )
            evidence_id = self.add(
                "source_evidence",
                evidence_key,
                {
                    "source_artifact_id": artifact_id,
                    "field_path": "manual_review.csv",
                    "locator": {"source_url": row.get("source_url")},
                    "quoted_fragment": None,
                    "claim": "Manual-review record references this source artifact",
                    "observed_at": None,
                    "verification_status": "manual_review",
                },
            )
            bridge_table, target_field = BRIDGE_TARGETS["manual_review_items"]
            bridge_key = _short_external_key(
                "evidence-target", f"{evidence_key}:manual:{review_id}"
            )
            self.rows[bridge_table].append(
                {
                    "id": stable_uuid(self.release_id, bridge_table, bridge_key),
                    "release_id": self.release_id,
                    "external_key": bridge_key,
                    "evidence_id": evidence_id,
                    target_field: review_id,
                }
            )

    def run(self) -> MappingResult:
        self.add_source_artifacts()
        self.add_university_and_catalog()
        self.add_admission_dimensions()
        self.add_campaigns_and_catalog_details()
        self.add_admission_facts()
        self.add_source_relationships_and_typed_links()
        self.add_manual_reviews()
        self.add_row_observations(
            "source_artifacts.jsonl",
            [(index, record) for index, record in enumerate(self.manifest, 1)],
        )
        for dataset_name, rows in self.datasets.items():
            self.add_row_observations(dataset_name, rows)
        self.add_confirmed_plan_observations()
        self._add_manual_row_observations()
        self.add_evidence_and_bridges()

        typed_counts = {name: len(rows) for name, rows in sorted(self.rows.items())}
        dataset_counts = {
            name.removesuffix(".jsonl"): len(rows) for name, rows in sorted(self.datasets.items())
        }
        artifact_statuses = Counter(
            _as_text(record.get("storage_status")) or "unspecified" for record in self.manifest
        )
        report = {
            "report_version": 1,
            "mapper_version": self.mapper_version,
            "release_key": self.release_key,
            "input_digest": self.input_digest,
            "validator_report_digest": hashlib.sha256(
                json.dumps(self.validator_report, sort_keys=True, ensure_ascii=False).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "source_dataset_counts": dataset_counts,
            "source_manifest_count": len(self.manifest),
            "source_artifact_storage_statuses": dict(sorted(artifact_statuses.items())),
            "source_observations_expected": sum(dataset_counts.values())
            + len(self.manifest)
            + len(self.confirmed_plan_links)
            + len(self.manual_rows)
            + 1,
            "typed_row_counts": typed_counts,
            "manual_review_count": len(self.manual_rows),
            "confirmed_study_plan_link_observations": len(self.confirmed_plan_links),
            "confirmed_study_plan_link_manifest_observations": 1,
            "exact_typed_relationship_counts": dict(sorted(self.typed_relation_counts.items())),
            "unresolved_exact_references": dict(sorted(self.unresolved.items())),
            "requirement_operator_counts": dict(sorted(self.requirement_operator_counts.items())),
            "warnings": sorted(
                self.warnings, key=lambda warning: json.dumps(warning, sort_keys=True)
            ),
            "retained_untyped_datasets": {
                name: DATASET_MAPPING_REGISTRY[name]
                for name in sorted(DATASET_MAPPING_REGISTRY)
                if "source_observations (" in DATASET_MAPPING_REGISTRY[name]
            },
            "excluded_personal_applicant_rows": 0,
            "excluded_olympiad_rows": 0,
            "raw_document_bytes_in_database": 0,
        }
        return MappingResult(
            release_id=self.release_id,
            release_key=self.release_key,
            input_digest=self.input_digest,
            validator_report=self.validator_report,
            report=report,
            table_rows=dict(self.rows),
            ids_by_table=dict(self.ids),
            raw_file_hashes={item.relative_path: item.sha256 for item in self.reader_files},
        )

    def _add_manual_row_observations(self) -> None:
        # The CSV is also typed in manual_review_items; preserve each original cell
        # without requiring a guessed FK to the row's subject.
        for _, row in enumerate(self.manual_rows, 1):
            identity = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            external_key = (
                f"observation:manual_review:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
            )
            artifact_id = self.resolve("source_artifacts", row.get("record_key"))
            self.add(
                "source_observations",
                external_key,
                {
                    "dataset_name": "manual_review.csv",
                    "payload": row,
                    "source_artifact_id": artifact_id,
                },
            )


def _read_jsonl(reader: BundleReader, path: str) -> list[tuple[int, dict[str, Any]]]:
    try:
        decoded = reader.read_bytes(path).decode("utf-8")
    except UnicodeDecodeError as error:
        raise BundleInputError(f"validated bundle file is not UTF-8: {path}") from error
    result: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(decoded.splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise BundleInputError(f"validated JSONL row is not an object: {path}:{line_number}")
        result.append((line_number, value))
    return result


def project_bundle(
    input_path: str | Path, *, mapper_version: str = MAPPER_VERSION
) -> MappingResult:
    """Validate and fully project the existing bundle without opening a DB connection."""

    validation_report = validate_bundle(input_path)
    if not validation_report.get("valid"):
        raise BundleInputError("bundle validation failed; mapping was not started")
    with BundleReader(input_path) as reader:
        if reader.input_digest != validation_report["input"]["digest"]:
            raise BundleInputError("bundle bytes changed between validation and mapping")
        dataset_paths = sorted(
            path
            for path in reader._file_names()
            if path.startswith("data/") and path.endswith(".jsonl")
        )
        datasets: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        unknown = []
        for path in dataset_paths:
            name = PurePosixPath(path).name
            if name not in DATASET_MAPPING_REGISTRY:
                unknown.append(name)
            datasets[name] = _read_jsonl(reader, path)
        if unknown:
            raise BundleMappingError(
                f"no import mapping is declared for datasets: {', '.join(unknown)}"
            )
        manifest = [record for _, record in _read_jsonl(reader, "source_artifacts.jsonl")]
        manual_bytes = reader.read_bytes("manual_review.csv")
        try:
            manual_text = manual_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise BundleInputError("manual_review.csv is not valid UTF-8") from error
        manual_rows = list(csv.DictReader(manual_text.splitlines()))
        confirmed: list[dict[str, Any]] = []
        if reader.has_file("user_confirmed_study_plan_links.json"):
            value = json.loads(reader.read_bytes("user_confirmed_study_plan_links.json"))
            if not isinstance(value, dict):
                raise BundleInputError("user_confirmed_study_plan_links.json must be an object")
            links = value.get("links")
            if not isinstance(links, list) or not all(isinstance(row, dict) for row in links):
                raise BundleInputError(
                    "user-confirmed plan document must contain an object array 'links'"
                )
            confirmed = links
            confirmed_manifest = value
        else:
            confirmed_manifest = None
        digest = reader.input_digest
        if not mapper_version or len(mapper_version) > 80:
            raise BundleMappingError("mapper_version must contain 1 to 80 characters")
        release_key = f"bmstu-2026:{digest}:{mapper_version}"
        release_id = uuid5(NAMESPACE_URL, f"andromeda-academic-release:{release_key}")
        projection = _Projection(
            release_id,
            release_key,
            digest,
            datasets,
            manifest,
            manual_rows,
            confirmed,
            confirmed_manifest,
            validation_report,
            mapper_version,
        )
        projection.reader_files = reader.files
        return projection.run()
