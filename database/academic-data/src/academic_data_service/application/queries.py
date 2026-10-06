"""Public read models assembled from source-backed canonical rows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast
from uuid import UUID

from academic_data_service.application.ports import AcademicDataReadRepository
from academic_data_service.contracts.v1.models import (
    AdmissionCampaignRecord,
    AdmissionDocumentRecord,
    AdmissionOfferingRecord,
    CampaignCalendarEventRecord,
    CatalogCourseRecord,
    CompetitionPoolRecord,
    CurriculumItemRecord,
    DataGap,
    DepartmentRecord,
    DepartmentRelation,
    DirectionRecord,
    EducationalProgramRecord,
    IndividualAchievementRecord,
    ManualReviewRecord,
    ManualReviewSummaryRecord,
    OfficialAdmissionStatisticRecord,
    PageResponse,
    PaginationMetadata,
    ReleaseMetadataRecord,
    RequirementLeaf,
    RequirementNode,
    RequirementOperatorNode,
    RequirementTreeRecord,
    SourceArtifactRecord,
    SourceEvidenceRecord,
    SourceEvidenceReference,
    SourceReference,
    StudyPlanRecord,
    SubjectClassificationSummary,
    SubjectTaxonomyCategoryRecord,
    SubjectTaxonomyRecord,
    TuitionRecord,
    UniversityRecord,
)
from academic_data_service.infrastructure.database.read_repository import InvalidCursorError

T = TypeVar("T")


class ApiReadError(Exception):
    """Expected public query failure translated into a safe API response."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.public_message = message


class AcademicDataQueries:
    """Translate stable external-key queries into the versioned v1 contracts."""

    def __init__(self, repository: AcademicDataReadRepository) -> None:
        self.repository = repository

    @property
    def release_key(self) -> str:
        return self.repository.active_release_key

    def university(self) -> UniversityRecord:
        page = self.repository.page("universities", limit=1)
        if not page.items:
            raise ApiReadError(
                404, "university_not_found", "No university is present in this release."
            )
        return self._university(page.items[0])

    def directions(self, limit: int, cursor: str | None) -> PageResponse[DirectionRecord]:
        return self._page("directions", DirectionRecord, self._direction, limit, cursor)

    def direction(self, key: str) -> DirectionRecord:
        return self._direction(self._required("directions", key))

    def departments(self, limit: int, cursor: str | None) -> PageResponse[DepartmentRecord]:
        return self._page("departments", DepartmentRecord, self._department, limit, cursor)

    def department(self, key: str) -> DepartmentRecord:
        return self._department(self._required("departments", key))

    def programs(
        self, limit: int, cursor: str | None, direction_key: str | None = None
    ) -> PageResponse[EducationalProgramRecord]:
        filters: dict[str, Any] = {}
        if direction_key is not None:
            direction = self._required("directions", direction_key)
            filters["direction_id"] = direction["id"]
        return self._page(
            "educational_programs", EducationalProgramRecord, self._program, limit, cursor, filters
        )

    def program(self, key: str) -> EducationalProgramRecord:
        return self._program(self._required("educational_programs", key))

    def program_courses(
        self, program_key: str, limit: int, cursor: str | None
    ) -> PageResponse[CatalogCourseRecord]:
        program = self._required("educational_programs", program_key)
        return self._page(
            "catalog_courses",
            CatalogCourseRecord,
            self._catalog_course,
            limit,
            cursor,
            {"program_id": program["id"]},
        )

    def study_plans(
        self, limit: int, cursor: str | None, program_key: str | None = None
    ) -> PageResponse[StudyPlanRecord]:
        filters: dict[str, Any] = {}
        if program_key is not None:
            program = self._required("educational_programs", program_key)
            filters["program_id"] = program["id"]
        return self._page("study_plans", StudyPlanRecord, self._study_plan, limit, cursor, filters)

    def study_plan(self, key: str) -> StudyPlanRecord:
        return self._study_plan(self._required("study_plans", key))

    def curriculum_items(
        self, plan_key: str, limit: int, cursor: str | None, semester: int | None = None
    ) -> PageResponse[CurriculumItemRecord]:
        plan = self._required("study_plans", plan_key)
        filters: dict[str, Any] = {"study_plan_id": plan["id"]}
        if semester is not None:
            filters["semester"] = semester
        return self._page(
            "curriculum_items", CurriculumItemRecord, self._curriculum_item, limit, cursor, filters
        )

    def campaigns(
        self,
        limit: int,
        cursor: str | None,
        year: int | None = None,
        education_level: str | None = None,
    ) -> PageResponse[AdmissionCampaignRecord]:
        filters = {
            key: value
            for key, value in {
                "year": year,
                "education_level": education_level,
            }.items()
            if value is not None
        }
        return self._page(
            "admission_campaigns", AdmissionCampaignRecord, self._campaign, limit, cursor, filters
        )

    def campaign(self, key: str) -> AdmissionCampaignRecord:
        return self._campaign(self._required("admission_campaigns", key))

    def campaign_calendar(
        self, campaign_key: str, limit: int, cursor: str | None
    ) -> PageResponse[CampaignCalendarEventRecord]:
        campaign = self._required("admission_campaigns", campaign_key)
        return self._page(
            "campaign_calendar_events",
            CampaignCalendarEventRecord,
            self._calendar_event,
            limit,
            cursor,
            {"campaign_id": campaign["id"]},
        )

    def campaign_offerings(
        self, campaign_key: str, limit: int, cursor: str | None
    ) -> PageResponse[AdmissionOfferingRecord]:
        campaign = self._required("admission_campaigns", campaign_key)
        return self._page(
            "program_offerings",
            AdmissionOfferingRecord,
            self._offering,
            limit,
            cursor,
            {"campaign_id": campaign["id"]},
        )

    def offering(self, key: str) -> AdmissionOfferingRecord:
        return self._offering(self._required("program_offerings", key))

    def competition_pools(
        self, limit: int, cursor: str | None, campaign_key: str | None = None
    ) -> PageResponse[CompetitionPoolRecord]:
        filters: dict[str, Any] = {}
        if campaign_key is not None:
            campaign = self._required("admission_campaigns", campaign_key)
            filters["campaign_id"] = campaign["id"]
        return self._page(
            "competition_pools",
            CompetitionPoolRecord,
            self._competition_pool,
            limit,
            cursor,
            filters,
        )

    def competition_pool(self, key: str) -> CompetitionPoolRecord:
        return self._competition_pool(self._required("competition_pools", key))

    def requirements(
        self, limit: int, cursor: str | None, campaign_key: str | None = None
    ) -> PageResponse[RequirementTreeRecord]:
        filters: dict[str, Any] = {}
        if campaign_key is not None:
            campaign = self._required("admission_campaigns", campaign_key)
            filters["campaign_id"] = campaign["id"]
        return self._page(
            "admission_requirement_sets",
            RequirementTreeRecord,
            self._requirement_tree,
            limit,
            cursor,
            filters,
        )

    def requirement(self, key: str) -> RequirementTreeRecord:
        return self._requirement_tree(self._required("admission_requirement_sets", key))

    def tuition(
        self, limit: int, cursor: str | None, direction_code: str | None = None
    ) -> PageResponse[TuitionRecord]:
        filters = {"direction_code": direction_code} if direction_code is not None else None
        return self._page(
            "tuition_assertions", TuitionRecord, self._tuition, limit, cursor, filters
        )

    def statistics(
        self,
        kind: str,
        limit: int,
        cursor: str | None,
        year: int | None = None,
        direction_code: str | None = None,
    ) -> PageResponse[OfficialAdmissionStatisticRecord]:
        is_historical = kind == "historical"
        table = "historical_admission_statistics" if is_historical else "admission_statistics"
        filters: dict[str, Any] = {}
        if year is not None:
            filters["admission_year"] = year
        if direction_code is not None:
            filters["direction_code"] = direction_code
        mapper = self._historical_statistic if is_historical else self._admission_statistic
        return self._page(table, OfficialAdmissionStatisticRecord, mapper, limit, cursor, filters)

    def achievements(
        self, limit: int, cursor: str | None, campaign_key: str | None = None
    ) -> PageResponse[IndividualAchievementRecord]:
        filters: dict[str, Any] = {}
        if campaign_key is not None:
            campaign = self._required("admission_campaigns", campaign_key)
            filters["campaign_id"] = campaign["id"]
        return self._page(
            "individual_achievement_policies",
            IndividualAchievementRecord,
            self._achievement,
            limit,
            cursor,
            filters,
        )

    def admission_documents(
        self, limit: int, cursor: str | None
    ) -> PageResponse[AdmissionDocumentRecord]:
        return self._page(
            "admission_documents", AdmissionDocumentRecord, self._document, limit, cursor
        )

    def source_artifacts(
        self, limit: int, cursor: str | None, status: str | None = None
    ) -> PageResponse[SourceArtifactRecord]:
        filters = {"storage_status": status} if status is not None else None
        return self._page(
            "source_artifacts", SourceArtifactRecord, self._source_artifact, limit, cursor, filters
        )

    def source_evidence(
        self, limit: int, cursor: str | None, source_artifact_key: str | None = None
    ) -> PageResponse[SourceEvidenceRecord]:
        filters: dict[str, Any] = {}
        if source_artifact_key is not None:
            artifact = self._required("source_artifacts", source_artifact_key)
            filters["source_artifact_id"] = artifact["id"]
        return self._page(
            "source_evidence", SourceEvidenceRecord, self._evidence_record, limit, cursor, filters
        )

    def manual_reviews(
        self, limit: int, cursor: str | None, status: str | None = None
    ) -> PageResponse[ManualReviewRecord]:
        filters = {"status": status} if status is not None else None
        return self._page(
            "manual_review_items", ManualReviewRecord, self._manual_review, limit, cursor, filters
        )

    def manual_review_summary(self) -> ManualReviewSummaryRecord:
        table = "manual_review_items"
        total = self.repository.page(table, limit=1).total_count
        counts = {
            status: self.repository.page(table, filters={"status": status}, limit=1).total_count
            for status in ("open", "resolved", "dismissed")
        }
        return ManualReviewSummaryRecord(
            release_key=self.release_key,
            total_count=total,
            open_count=counts["open"],
            resolved_count=counts["resolved"],
            dismissed_count=counts["dismissed"],
        )

    def release(self) -> ReleaseMetadataRecord:
        row = self.repository.active_release()
        return ReleaseMetadataRecord(
            release_key=row["release_key"],
            source_bundle_sha256=row["source_bundle_sha256"],
            mapper_version=row["mapper_version"],
            activated_at=row["committed_at"],
            reconciliation_status=row["reconciliation_status"],
            schema_revision=row["schema_revision"] or "unknown",
        )

    def subject_taxonomy(self, taxonomy_key: str, taxonomy_version: str) -> SubjectTaxonomyRecord:
        getter = getattr(self.repository, "subject_taxonomy", None)
        row = getter(taxonomy_key, taxonomy_version) if getter is not None else None
        if row is None:
            raise ApiReadError(
                404, "taxonomy_not_found", "The requested subject taxonomy was not found."
            )
        return SubjectTaxonomyRecord(
            taxonomy_key=row["taxonomy_key"],
            taxonomy_version=row["taxonomy_version"],
            name=row["name"],
            description=row["description"],
            categories=[
                SubjectTaxonomyCategoryRecord(**category) for category in row["categories"]
            ],
        )

    def _page(
        self,
        table: str,
        model: type[T],
        mapper: Callable[[dict[str, Any]], T],
        limit: int,
        cursor: str | None,
        filters: dict[str, Any] | None = None,
    ) -> PageResponse[T]:
        try:
            page_rows = self.repository.page(table, filters=filters, limit=limit, cursor=cursor)
        except InvalidCursorError as error:
            raise ApiReadError(422, "invalid_cursor", "The page cursor is invalid.") from error
        subject_type = {
            "catalog_courses": "catalog_course",
            "curriculum_items": "curriculum_item",
        }.get(table)
        if subject_type is not None:
            classifier = getattr(self.repository, "subject_classifications_for", None)
            if classifier is not None:
                classified = classifier(
                    subject_type,
                    [row["id"] for row in page_rows.items],
                    "bmstu-subject-domain-16",
                    "v1",
                )
                for row in page_rows.items:
                    summary = classified.get(row["id"])
                    row["subject_classification"] = (
                        SubjectClassificationSummary(**summary) if summary is not None else None
                    )
        page_model = PageResponse[model]  # type: ignore[valid-type]
        return cast(
            PageResponse[T],
            page_model(
                items=[mapper(row) for row in page_rows.items],
                page=PaginationMetadata(
                    limit=limit,
                    next_cursor=page_rows.next_cursor,
                    total_count=page_rows.total_count,
                    release_key=self.release_key,
                ),
            ),
        )

    def _required(self, table: str, key: str) -> dict[str, Any]:
        row = self.repository.get(table, key)
        if row is None:
            raise ApiReadError(404, "record_not_found", "The requested record was not found.")
        return row

    def _sourced(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        evidence_rows = self.repository.evidence_for(table, row["id"])
        sources: dict[str, SourceReference] = {}
        evidence = []
        for source in evidence_rows:
            artifact_key = source["source_artifact_key"]
            sources.setdefault(
                artifact_key,
                SourceReference(
                    source_artifact_key=artifact_key,
                    source_url=source["final_url"] or source["requested_url"],
                    fetched_at=source["fetched_at"],
                    sha256=source["sha256"],
                    field_path=source["field_path"],
                    locator=source["locator"],
                    observed_at=source["observed_at"],
                ),
            )
            evidence.append(
                SourceEvidenceReference(
                    evidence_key=source["evidence_key"],
                    source_artifact_key=artifact_key,
                    claim_path=source["field_path"],
                    locator=source["locator"],
                    claim=source["claim"] or source["quoted_fragment"],
                    observed_at=source["observed_at"],
                    verification_status=source["verification_status"],
                )
            )
        gaps = [
            DataGap(
                field_path=review["issue_code"],
                status="manual_review",
                reason=review["summary"],
                source_keys=[
                    key for key in (review["source_key"], review["target_key"]) if key is not None
                ],
            )
            for review in self.repository.manual_reviews_for(row["external_key"])
            if review["status"] == "open"
        ]
        return {"sources": list(sources.values()), "evidence": evidence, "data_gaps": gaps}

    def _source_references(self, table: str, row: dict[str, Any]) -> list[SourceReference]:
        sources: dict[str, SourceReference] = {}
        for source in self.repository.evidence_for(table, row["id"]):
            artifact_key = source["source_artifact_key"]
            sources.setdefault(
                artifact_key,
                SourceReference(
                    source_artifact_key=artifact_key,
                    source_url=source["final_url"] or source["requested_url"],
                    fetched_at=source["fetched_at"],
                    sha256=source["sha256"],
                    field_path=source["field_path"],
                    locator=source["locator"],
                    observed_at=source["observed_at"],
                ),
            )
        return list(sources.values())

    def _temporal(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "valid_from": row.get("valid_from"),
            "valid_to": row.get("valid_to"),
            "observed_at": row.get("observed_at"),
            "ingested_at": row.get("ingested_at"),
        }

    def _university(self, row: dict[str, Any]) -> UniversityRecord:
        return UniversityRecord(
            external_key=row["external_key"],
            official_code=row["official_code"],
            name=row["name"],
            description=row["identity_source_note"],
            city=row["city"],
            official_site=row["official_site"],
            **self._sourced("universities", row),
        )

    def _direction(self, row: dict[str, Any]) -> DirectionRecord:
        department_links = self.repository.related(
            "direction_departments", "direction_id", row["id"]
        )
        program_rows = self.repository.related("educational_programs", "direction_id", row["id"])
        return DirectionRecord(
            external_key=row["external_key"],
            code=row["code"],
            name=row["name"],
            description=row["description"],
            degree_label=row["degree_label"],
            duration_label=row["duration_label"],
            duration_months=row["duration_months"],
            qualification_label=row["qualification_label"],
            department_keys=self._related_keys("departments", department_links, "department_id"),
            program_keys=[program["external_key"] for program in program_rows],
            **self._sourced("directions", row),
        )

    def _department(self, row: dict[str, Any]) -> DepartmentRecord:
        return DepartmentRecord(
            external_key=row["external_key"],
            official_code=row["official_code"],
            name=row["name"],
            description=row["description"],
            faculty_name=row["faculty_name"],
            address=row["address"],
            campus_scope=row["campus_scope"],
            campus_key=None,
            campus_status=self._campus_status(row.get("campus_scope")),
            **self._sourced("departments", row),
        )

    def _program(self, row: dict[str, Any]) -> EducationalProgramRecord:
        department_rows = self.repository.related(
            "educational_program_departments", "program_id", row["id"]
        )
        departments = []
        for relation in department_rows:
            department = self.repository.get_by_id("departments", relation["department_id"])
            if department is not None:
                departments.append(
                    DepartmentRelation(
                        department_key=department["external_key"],
                        relation_type=relation["relation_type"],
                        verification_status=relation["verification_status"],
                        source_relation_type=relation["source_relation_type"],
                        sources=self._source_references(
                            "educational_program_departments", relation
                        ),
                    )
                )
        plans = self.repository.related("study_plans", "program_id", row["id"])
        courses = self.repository.related("catalog_courses", "program_id", row["id"])
        offerings = self.repository.related("program_offerings", "program_id", row["id"])
        return EducationalProgramRecord(
            external_key=row["external_key"],
            code=row["code"],
            name=row["name"],
            direction_key=self._linked_key("directions", row["direction_id"]),
            description=row["description"],
            department_relations=departments,
            study_plan_keys=[plan["external_key"] for plan in plans],
            course_keys=[course["external_key"] for course in courses],
            offering_keys=[offering["external_key"] for offering in offerings],
            campus_scope=row["campus_scope"],
            catalog_course_names=row["catalog_course_names"] or [],
            catalog_page_url=row["catalog_page_url"],
            study_plan_url=row["study_plan_url"],
            campus_key=None,
            campus_status=self._campus_status(row.get("campus_scope")),
            **self._sourced("educational_programs", row),
        )

    def _study_plan(self, row: dict[str, Any]) -> StudyPlanRecord:
        program = (
            self.repository.get_by_id("educational_programs", row["program_id"])
            if row["program_id"] is not None
            else None
        )
        item_count = self.repository.page(
            "curriculum_items", filters={"study_plan_id": row["id"]}, limit=1
        ).total_count
        return StudyPlanRecord(
            external_key=row["external_key"],
            program_key=program["external_key"] if program else None,
            profile_link_status=row["profile_link_status"],
            academic_year=str(row["education_year"]) if row["education_year"] else None,
            version_label=row["version_label"] or row["source_version"],
            source_version=row["source_version"],
            profile_code=row["profile_code"],
            header_profile_code=row["header_profile_code"],
            profile_name_in_plan=row["profile_name_in_plan"],
            study_form=row["study_form"],
            duration_label=row["duration_label"],
            semester_count=row["semester_count"],
            total_academic_hours=row["total_academic_hours"],
            total_astronomical_hours=row["total_astronomical_hours"],
            semester_totals=row["semester_totals"],
            document_url=row["document_url"],
            download_url=row["download_url"],
            study_plan_url=row["study_plan_url"],
            unavailable_reason=row["unavailable_reason"],
            status=row["status"],
            item_count=item_count,
            **self._sourced("study_plans", row),
        )

    def _curriculum_item(self, row: dict[str, Any]) -> CurriculumItemRecord:
        return CurriculumItemRecord(
            external_key=row["external_key"],
            study_plan_key=self._linked_key("study_plans", row["study_plan_id"]),
            ordinal=row["ordinal"],
            discipline_name=row["discipline_name"],
            semester=row["semester"],
            credits=row["credits"],
            hours=row["total_hours"] if row["total_hours"] is not None else row["hours"],
            lecture_hours=row["total_lecture_hours"] or row["lecture_hours"],
            practice_hours=row["total_practice_hours"] or row["practice_hours"],
            lab_hours=row["total_lab_hours"] or row["lab_hours"],
            self_study_hours=row["total_self_study_hours"] or row["self_study_hours"],
            total_hours=row["total_hours"],
            control_form=row["assessment_type"],
            department_name=row["department_name"],
            faculty_name=row["faculty_name"],
            chair_name=row["chair_name"],
            subject_classification=row.get("subject_classification"),
            **self._sourced("curriculum_items", row),
        )

    def _campaign(self, row: dict[str, Any]) -> AdmissionCampaignRecord:
        return AdmissionCampaignRecord(
            external_key=row["external_key"],
            university_key=self._linked_key("universities", row["university_id"]),
            year=row["year"],
            education_level=row["education_level"],
            campaign_kind=row["campaign_kind"],
            title=row["title"],
            date_note=row["date_note"],
            campus_key=None,
            campus_status="not_stated",
            **self._sourced("admission_campaigns", row),
        )

    def _calendar_event(self, row: dict[str, Any]) -> CampaignCalendarEventRecord:
        return CampaignCalendarEventRecord(
            external_key=row["external_key"],
            campaign_key=self._linked_key("admission_campaigns", row["campaign_id"]),
            event_code=row["event_code"],
            label=row["label"],
            context=row["context"],
            starts_at=row["starts_at"],
            ends_at=row["ends_at"],
            date_value=row["date_value"],
            time_value=row["time_value"].isoformat() if row["time_value"] else None,
            date_text=row["date_text"],
            **self._sourced("campaign_calendar_events", row),
        )

    def _offering(self, row: dict[str, Any]) -> AdmissionOfferingRecord:
        program = (
            self.repository.get_by_id("educational_programs", row["program_id"])
            if row["program_id"] is not None
            else None
        )
        direction = (
            self.repository.get_by_id("directions", row["direction_id"])
            if row["direction_id"] is not None
            else None
        )
        department = (
            self.repository.get_by_id("departments", row["department_id"])
            if row["department_id"] is not None
            else None
        )
        review_status = any(
            review["status"] == "open"
            for review in self.repository.manual_reviews_for(row["external_key"])
        )
        if program is not None:
            link_status: Literal["exact", "unresolved", "manual_review"] = "exact"
        elif review_status:
            link_status = "manual_review"
        else:
            link_status = "unresolved"
        return AdmissionOfferingRecord(
            external_key=row["external_key"],
            campaign_key=self._linked_key("admission_campaigns", row["campaign_id"]),
            direction_key=direction["external_key"] if direction else None,
            direction_code=row["direction_code"],
            program_key=program["external_key"] if program else None,
            program_link_status=link_status,
            program_name_in_source=row["program_name_in_document"],
            department_key=department["external_key"] if department else None,
            department_code=row["department_code"],
            study_form=row["study_form"],
            language=row["language"],
            study_duration_label=row["study_duration_label"],
            campus_scope=row["campus_scope"],
            places_total=None,
            **self._sourced("program_offerings", row),
        )

    def _competition_pool(self, row: dict[str, Any]) -> CompetitionPoolRecord:
        direction = (
            self.repository.get_by_id("directions", row["direction_id"])
            if row["direction_id"] is not None
            else None
        )
        department = (
            self.repository.get_by_id("departments", row["department_id"])
            if row["department_id"] is not None
            else None
        )
        pool_links = self.repository.related("competition_pool_offerings", "pool_id", row["id"])
        offering_keys = self._related_keys("program_offerings", pool_links, "offering_id")
        return CompetitionPoolRecord(
            external_key=row["external_key"],
            campaign_key=self._linked_key("admission_campaigns", row["campaign_id"]),
            direction_key=direction["external_key"] if direction else None,
            direction_code=row["direction_code"],
            department_key=department["external_key"] if department else None,
            department_code=row["department_code"],
            department_status=(
                "verified"
                if department
                else "unresolved"
                if row["department_code"]
                else "not_stated"
            ),
            scope_level=row["scope_level"],
            funding_type=self._lookup_code("funding_types", row["funding_type_id"]),
            quota_type=self._lookup_code("quota_types", row["quota_type_id"]),
            places=row["places"],
            places_by_source_row=row["places_by_source_row"],
            offering_keys=offering_keys,
            **self._temporal(row),
            **self._sourced("competition_pools", row),
        )

    def _requirement_tree(self, row: dict[str, Any]) -> RequirementTreeRecord:
        direction = (
            self.repository.get_by_id("directions", row["direction_id"])
            if row["direction_id"] is not None
            else None
        )
        nodes = self.repository.related(
            "admission_requirement_nodes", "requirement_set_id", row["id"]
        )
        by_parent: dict[UUID | None, list[dict[str, Any]]] = {}
        for node in nodes:
            by_parent.setdefault(node["parent_id"], []).append(node)
        for children in by_parent.values():
            children.sort(key=lambda child: (child["ordinal"], child["external_key"]))
        roots = by_parent.get(None, [])
        if not roots:
            raise ApiReadError(
                503, "requirement_tree_unavailable", "The stored requirement tree is incomplete."
            )

        def build_node(node: dict[str, Any]) -> RequirementNode:
            node_sources = self._sourced("admission_requirement_nodes", node)
            if node["node_kind"] == "operator":
                return RequirementOperatorNode(
                    node_key=node["external_key"],
                    operator=node["operator"],
                    threshold=node["min_count"],
                    children=[build_node(child) for child in by_parent.get(node["id"], [])],
                    sources=node_sources["sources"],
                )
            exam = (
                self.repository.get_by_id("admission_exams", node["exam_id"])
                if node["exam_id"] is not None
                else None
            )
            return RequirementLeaf(
                node_key=node["external_key"],
                subject_code=node["subject_code"],
                subject_name=exam["name"] if exam else None,
                minimum_score=node["minimum_score"],
                is_choice=node["is_choice"],
                tiebreak_rank=node["tiebreak_rank"],
                sources=node_sources["sources"],
            )

        return RequirementTreeRecord(
            external_key=row["external_key"],
            campaign_key=self._linked_key("admission_campaigns", row["campaign_id"]),
            direction_key=direction["external_key"] if direction else None,
            direction_code=row["direction_code"],
            applicant_category=row["applicant_category_text"],
            root=build_node(roots[0]),
            **self._temporal(row),
            **self._sourced("admission_requirement_sets", row),
        )

    def _tuition(self, row: dict[str, Any]) -> TuitionRecord:
        direction = (
            self.repository.get_by_id("directions", row["direction_id"])
            if row["direction_id"] is not None
            else None
        )
        return TuitionRecord(
            external_key=row["external_key"],
            direction_key=direction["external_key"] if direction else None,
            direction_code=row["direction_code"],
            direction_name=row["direction_name"],
            academic_year=row["academic_year_label"],
            amount=row["amount"],
            currency=row["currency"],
            table_category=row["table_category"],
            campus_scope=row["campus_scope"],
            **self._temporal(row),
            **self._sourced("tuition_assertions", row),
        )

    def _historical_statistic(self, row: dict[str, Any]) -> OfficialAdmissionStatisticRecord:
        direction = (
            self.repository.get_by_id("directions", row["direction_id"])
            if row["direction_id"] is not None
            else None
        )
        return OfficialAdmissionStatisticRecord(
            external_key=row["external_key"],
            direction_key=direction["external_key"] if direction else None,
            direction_code=row["direction_code"],
            year=row["admission_year"],
            statistic_kind=row["outcome_type"],
            scope_type=row["scope_type"],
            scope_label=row["scope_label"],
            funding_type=row["funding_type_code"],
            study_form=row["study_form"],
            score=row["minimum_score"],
            minimum_score=row["minimum_score"],
            maximum_score=row["maximum_score"],
            average_score=row["average_score"],
            admitted_count=row["admitted_count"],
            snapshot_date=row["snapshot_date"],
            **self._temporal(row),
            **self._sourced("historical_admission_statistics", row),
        )

    def _admission_statistic(self, row: dict[str, Any]) -> OfficialAdmissionStatisticRecord:
        direction = (
            self.repository.get_by_id("directions", row["direction_id"])
            if row["direction_id"] is not None
            else None
        )
        return OfficialAdmissionStatisticRecord(
            external_key=row["external_key"],
            direction_key=direction["external_key"] if direction else None,
            direction_code=row["direction_code"],
            year=row["admission_year"],
            statistic_kind=row["competition_type"] or row["status"],
            admission_stage=row["admission_stage"],
            competition_type=row["competition_type"],
            status=row["status"],
            funding_type=row["funding_type_code"],
            study_form=row["study_form"],
            score=row["score"],
            snapshot_date=row["snapshot_date"],
            **self._temporal(row),
            **self._sourced("admission_statistics", row),
        )

    def _achievement(self, row: dict[str, Any]) -> IndividualAchievementRecord:
        campaign = (
            self.repository.get_by_id("admission_campaigns", row["campaign_id"])
            if row["campaign_id"] is not None
            else None
        )
        return IndividualAchievementRecord(
            external_key=row["external_key"],
            campaign_key=campaign["external_key"] if campaign else None,
            name=row["achievement_name"],
            points=row["additional_points"],
            required_document=row["required_document"],
            row_number=row["row_number"],
            **self._temporal(row),
            **self._sourced("individual_achievement_policies", row),
        )

    def _document(self, row: dict[str, Any]) -> AdmissionDocumentRecord:
        sources = self.repository.evidence_for("admission_documents", row["id"])
        source_url = next(
            (
                source["final_url"] or source["requested_url"]
                for source in sources
                if source["final_url"] or source["requested_url"]
            ),
            None,
        )
        return AdmissionDocumentRecord(
            external_key=row["external_key"],
            title=row["title"],
            document_type=row["document_group"],
            source_url=source_url,
            document_id=row["document_id"],
            document_group=row["document_group"],
            scope_tag=row["scope_tag"],
            captured=row["captured"],
            **self._sourced("admission_documents", row),
        )

    def _source_artifact(self, row: dict[str, Any]) -> SourceArtifactRecord:
        return SourceArtifactRecord(
            external_key=row["external_key"],
            source_url=row["final_url"] or row["requested_url"],
            fetched_at=row["fetched_at"],
            sha256=row["sha256"],
            media_type=row["content_type"],
            raw_status=row["storage_status"],
            file_name=(
                str(row["raw_path"]).replace("\\", "/").rsplit("/", 1)[-1]
                if row["raw_path"]
                else None
            ),
            byte_size=row["byte_size"],
            note=row["note"],
        )

    def _catalog_course(self, row: dict[str, Any]) -> CatalogCourseRecord:
        return CatalogCourseRecord(
            external_key=row["external_key"],
            program_key=self._linked_key("educational_programs", row["program_id"]),
            name=row["name"],
            description=row["description"],
            description_status=row["description_status"],
            subject_classification=row.get("subject_classification"),
            **self._sourced("catalog_courses", row),
        )

    def _evidence_record(self, row: dict[str, Any]) -> SourceEvidenceRecord:
        return SourceEvidenceRecord(
            external_key=row["external_key"],
            source_artifact_key=self._linked_key("source_artifacts", row["source_artifact_id"]),
            field_path=row["field_path"],
            locator=row["locator"],
            claim=row["claim"] or row["quoted_fragment"],
            observed_at=row["observed_at"],
            verification_status=row["verification_status"],
        )

    def _manual_review(self, row: dict[str, Any]) -> ManualReviewRecord:
        locator = row["source_locator"] or {}
        return ManualReviewRecord(
            external_key=row["external_key"],
            issue_type=row["issue_code"],
            record_key=row["subject_key"] or row["source_key"] or row["external_key"],
            source_key=row["source_key"],
            target_key=row["target_key"],
            candidate_keys=row["candidate_keys"] or [],
            reason=row["summary"],
            status=row["status"],
            source_url=locator.get("source_url") if isinstance(locator, dict) else None,
        )

    def _related_keys(
        self, target_table: str, relationship_rows: list[dict[str, Any]], foreign_key: str
    ) -> list[str]:
        keys = []
        for relation in relationship_rows:
            target = self.repository.get_by_id(target_table, relation[foreign_key])
            if target is not None:
                keys.append(target["external_key"])
        return keys

    def _lookup_code(self, table: str, record_id: UUID | None) -> str | None:
        if record_id is None:
            return None
        row = self.repository.get_by_id(table, record_id)
        return row["code"] if row else None

    def _linked_key(self, table: str, record_id: UUID | None) -> str:
        if record_id is None:
            raise ApiReadError(
                503, "linked_record_unavailable", "A required linked record is unavailable."
            )
        row = self.repository.get_by_id(table, record_id)
        if row is None:
            raise ApiReadError(
                503, "linked_record_unavailable", "A required linked record is unavailable."
            )
        return str(row["external_key"])

    @staticmethod
    def _campus_status(
        scope: str | None,
    ) -> Literal["verified", "unverified", "not_stated"]:
        if scope == "head_moscow":
            return "verified"
        if scope in {"unknown", "unverified"}:
            return "unverified"
        return "not_stated"
