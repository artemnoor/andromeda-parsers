"""Source evidence with real same-release foreign keys to typed records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from academic_data_service.infrastructure.database.base import Base
from academic_data_service.infrastructure.database.mixins import (
    ReleaseScopedMixin,
    release_scoped_constraints,
)


class SourceEvidenceModel(ReleaseScopedMixin, Base):
    __tablename__ = "source_evidence"
    __table_args__ = release_scoped_constraints(
        __tablename__,
        ForeignKeyConstraint(
            ["release_id", "source_artifact_id"],
            ["source_artifacts.release_id", "source_artifacts.id"],
            name="fk_source_evidence_artifact_release",
        ),
        CheckConstraint(
            "verification_status IN ('source_backed', 'unverified', 'manual_review')",
            name="valid_verification_status",
        ),
        CheckConstraint("length(field_path) > 0", name="nonempty_field_path"),
        Index("ix_source_evidence_release_artifact", "release_id", "source_artifact_id"),
    )

    source_artifact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    field_path: Mapped[str] = mapped_column(String(512), nullable=False)
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    quoted_fragment: Mapped[str | None] = mapped_column(Text)
    claim: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def evidence_bridge_table(
    name: str,
    target_field: str,
    target_table: str,
) -> Table:
    """Build one physical bridge with evidence and target FKs scoped to a release."""

    return Table(
        name,
        Base.metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True, default=uuid4),
        Column(
            "release_id",
            Uuid(as_uuid=True),
            ForeignKey("data_releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("external_key", String(512), nullable=False),
        Column("evidence_id", Uuid(as_uuid=True), nullable=False),
        Column(target_field, Uuid(as_uuid=True), nullable=False),
        ForeignKeyConstraint(
            ["release_id", "evidence_id"],
            ["source_evidence.release_id", "source_evidence.id"],
            ondelete="CASCADE",
            name=f"fk_{name}_evidence_release",
        ),
        ForeignKeyConstraint(
            ["release_id", target_field],
            [f"{target_table}.release_id", f"{target_table}.id"],
            ondelete="CASCADE",
            name=f"fk_{name}_target_release",
        ),
        UniqueConstraint("release_id", "external_key", name=f"uq_{name}_release_external_key"),
        UniqueConstraint("release_id", "id", name=f"uq_{name}_release_id"),
        UniqueConstraint(
            "release_id", "evidence_id", target_field, name=f"uq_{name}_evidence_target"
        ),
        Index(f"ix_{name}_release_target", "release_id", target_field),
    )


UniversityEvidenceModel = evidence_bridge_table(
    "university_evidence", "university_id", "universities"
)
DirectionEvidenceModel = evidence_bridge_table("direction_evidence", "direction_id", "directions")
DepartmentEvidenceModel = evidence_bridge_table(
    "department_evidence", "department_id", "departments"
)
DirectionDepartmentEvidenceModel = evidence_bridge_table(
    "direction_department_evidence", "direction_department_id", "direction_departments"
)
ProgramEvidenceModel = evidence_bridge_table(
    "program_evidence", "program_id", "educational_programs"
)
ProgramDepartmentEvidenceModel = evidence_bridge_table(
    "program_department_evidence", "program_department_id", "educational_program_departments"
)
CatalogCourseEvidenceModel = evidence_bridge_table(
    "catalog_course_evidence", "course_id", "catalog_courses"
)
StudyPlanEvidenceModel = evidence_bridge_table(
    "study_plan_evidence", "study_plan_id", "study_plans"
)
CurriculumEvidenceModel = evidence_bridge_table(
    "curriculum_evidence", "curriculum_item_id", "curriculum_items"
)
CampaignEvidenceModel = evidence_bridge_table(
    "campaign_evidence", "campaign_id", "admission_campaigns"
)
CalendarEventEvidenceModel = evidence_bridge_table(
    "calendar_event_evidence", "calendar_event_id", "campaign_calendar_events"
)
OfferingEvidenceModel = evidence_bridge_table(
    "offering_evidence", "offering_id", "program_offerings"
)
CompetitionPoolEvidenceModel = evidence_bridge_table(
    "competition_pool_evidence", "pool_id", "competition_pools"
)
PoolOfferingEvidenceModel = evidence_bridge_table(
    "pool_offering_evidence", "pool_offering_id", "competition_pool_offerings"
)
PlaceQuotaEvidenceModel = evidence_bridge_table(
    "place_quota_evidence", "assertion_id", "place_quota_assertions"
)
RequirementSetEvidenceModel = evidence_bridge_table(
    "requirement_set_evidence", "requirement_set_id", "admission_requirement_sets"
)
RequirementNodeEvidenceModel = evidence_bridge_table(
    "requirement_node_evidence", "requirement_node_id", "admission_requirement_nodes"
)
OfferingRequirementEvidenceModel = evidence_bridge_table(
    "offering_requirement_evidence", "link_id", "offering_requirement_links"
)
TuitionEvidenceModel = evidence_bridge_table(
    "tuition_evidence", "tuition_assertion_id", "tuition_assertions"
)
HistoricalStatisticEvidenceModel = evidence_bridge_table(
    "historical_statistic_evidence", "statistic_id", "historical_admission_statistics"
)
AdmissionStatisticEvidenceModel = evidence_bridge_table(
    "admission_statistic_evidence", "statistic_id", "admission_statistics"
)
AchievementEvidenceModel = evidence_bridge_table(
    "achievement_evidence", "achievement_policy_id", "individual_achievement_policies"
)
AdmissionDocumentEvidenceModel = evidence_bridge_table(
    "admission_document_evidence", "document_id", "admission_documents"
)
AdmissionDocumentPageEvidenceModel = evidence_bridge_table(
    "admission_document_page_evidence", "page_id", "admission_document_pages"
)
AdmissionResultSourceEvidenceModel = evidence_bridge_table(
    "admission_result_source_evidence", "result_source_id", "admission_result_sources"
)
SourceRelationshipEvidenceModel = evidence_bridge_table(
    "source_relationship_evidence", "relationship_id", "source_relationships"
)
ManualReviewEvidenceModel = evidence_bridge_table(
    "manual_review_evidence", "manual_review_id", "manual_review_items"
)
ExamEvidenceModel = evidence_bridge_table("exam_evidence", "exam_id", "admission_exams")
FundingTypeEvidenceModel = evidence_bridge_table(
    "funding_type_evidence", "funding_type_id", "funding_types"
)
QuotaTypeEvidenceModel = evidence_bridge_table(
    "quota_type_evidence", "quota_type_id", "quota_types"
)
