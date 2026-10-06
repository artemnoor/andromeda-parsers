"""Strict public DTOs for the read-only academic data API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

ExternalKey = Annotated[str, Field(min_length=1, max_length=256)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
RequirementOperator = Literal["AND", "OR", "AT_LEAST"]
T = TypeVar("T")


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ApiDescription(ContractModel):
    service: Literal["andromeda-academic-data"]
    api_version: Literal["v1"]
    supported_scope: list[str]
    openapi_path: str


class LivenessRecord(ContractModel):
    status: Literal["alive"]
    service: Literal["andromeda-academic-data"]
    service_version: str


class ReadinessRecord(ContractModel):
    status: Literal["ready", "not_ready"]
    reason_code: Literal[
        "ready",
        "database_unavailable",
        "database_identity_mismatch",
        "database_version_unsupported",
        "schema_outdated",
        "active_release_unavailable",
        "release_not_reconciled",
    ]
    required_schema_revision: str
    schema_revision: str | None = None
    release_key: ExternalKey | None = None
    bundle_digest_prefix: Annotated[str, Field(pattern=r"^[0-9a-f]{12}$")] | None = None


class ApiFieldIssue(ContractModel):
    path: list[str | int]
    code: str
    message: str


class ApiError(ContractModel):
    code: str
    message: str
    request_id: str
    field_issues: list[ApiFieldIssue] = Field(default_factory=list)


class ApiErrorEnvelope(ContractModel):
    error: ApiError


class PaginationMetadata(ContractModel):
    limit: int = Field(ge=1, le=100)
    next_cursor: str | None = None
    total_count: int | None = Field(default=None, ge=0)
    release_key: ExternalKey


class PageResponse(ContractModel, Generic[T]):
    items: list[T]
    page: PaginationMetadata


class DataGap(ContractModel):
    field_path: str
    status: Literal[
        "not_stated",
        "unavailable",
        "unverified",
        "unresolved",
        "manual_review",
        "conflict",
    ]
    reason: str
    source_keys: list[ExternalKey] = Field(default_factory=list)


class SourceReference(ContractModel):
    source_artifact_key: ExternalKey
    source_url: str | None = None
    fetched_at: datetime | None = None
    sha256: Sha256 | None = None
    field_path: str | None = None
    locator: dict[str, Any] | str | None = None
    observed_at: datetime | None = None


class SourceEvidenceReference(ContractModel):
    evidence_key: ExternalKey
    source_artifact_key: ExternalKey
    claim_path: str
    locator: dict[str, Any] | str | None = None
    claim: str | None = None
    observed_at: datetime | None = None
    verification_status: Literal["source_backed", "unverified", "manual_review"]


class SourcedRecord(ContractModel):
    sources: list[SourceReference] = Field(default_factory=list)
    evidence: list[SourceEvidenceReference] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)


class TemporalFactRecord(ContractModel):
    valid_from: date | None = None
    valid_to: date | None = None
    observed_at: datetime | None = None
    ingested_at: datetime

    @model_validator(mode="after")
    def validate_validity_period(self) -> TemporalFactRecord:
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_from > self.valid_to:
                raise ValueError("valid_from cannot be later than valid_to")
        return self


class UniversityRecord(SourcedRecord):
    external_key: ExternalKey
    official_code: str | None = None
    name: str
    description: str | None = None
    city: str | None = None
    official_site: str | None = None


class DirectionRecord(SourcedRecord):
    external_key: ExternalKey
    code: str
    name: str
    description: str | None = None
    degree_label: str | None = None
    duration_label: str | None = None
    duration_months: int | None = Field(default=None, ge=1)
    qualification_label: str | None = None
    department_keys: list[ExternalKey] = Field(default_factory=list)
    program_keys: list[ExternalKey] = Field(default_factory=list)


class DepartmentRelation(ContractModel):
    department_key: ExternalKey
    relation_type: str | None = None
    verification_status: Literal["verified", "unverified", "manual_review"]
    source_relation_type: str | None = None
    sources: list[SourceReference] = Field(default_factory=list)


class DepartmentRecord(SourcedRecord):
    external_key: ExternalKey
    official_code: str | None = None
    name: str
    description: str | None = None
    faculty_name: str | None = None
    address: str | None = None
    campus_scope: str | None = None
    campus_key: ExternalKey | None = None
    campus_status: Literal["verified", "unverified", "not_stated"]


class EducationalProgramRecord(SourcedRecord):
    external_key: ExternalKey
    code: str
    name: str
    direction_key: ExternalKey
    description: str | None = None
    department_relations: list[DepartmentRelation] = Field(default_factory=list)
    study_plan_keys: list[ExternalKey] = Field(default_factory=list)
    course_keys: list[ExternalKey] = Field(default_factory=list)
    offering_keys: list[ExternalKey] = Field(default_factory=list)
    campus_scope: str | None = None
    catalog_course_names: list[str] = Field(default_factory=list)
    catalog_page_url: str | None = None
    study_plan_url: str | None = None
    campus_key: ExternalKey | None = None
    campus_status: Literal["verified", "unverified", "not_stated"]


class CatalogCourseRecord(SourcedRecord):
    external_key: ExternalKey
    program_key: ExternalKey
    name: str
    description: str | None = None
    description_status: str | None = None
    subject_classification: SubjectClassificationSummary | None = None


class StudyPlanRecord(SourcedRecord):
    external_key: ExternalKey
    program_key: ExternalKey | None = None
    profile_link_status: Literal["verified", "unverified", "unresolved", "manual_review"]
    academic_year: str | None = None
    version_label: str | None = None
    source_version: str | None = None
    profile_code: str | None = None
    header_profile_code: str | None = None
    profile_name_in_plan: str | None = None
    study_form: str | None = None
    duration_label: str | None = None
    semester_count: int | None = Field(default=None, ge=0)
    total_academic_hours: int | None = Field(default=None, ge=0)
    total_astronomical_hours: int | None = Field(default=None, ge=0)
    semester_totals: list[dict[str, Any]] | None = None
    document_url: str | None = None
    download_url: str | None = None
    study_plan_url: str | None = None
    unavailable_reason: str | None = None
    status: Literal["parsed", "unavailable", "unverified"]
    item_count: int | None = Field(default=None, ge=0)


class CurriculumItemRecord(SourcedRecord):
    external_key: ExternalKey
    study_plan_key: ExternalKey
    ordinal: int = Field(ge=0)
    discipline_name: str | None = None
    semester: int | None = Field(default=None, ge=1)
    credits: Decimal | None = Field(default=None, ge=0)
    hours: int | None = Field(default=None, ge=0)
    lecture_hours: int | None = Field(default=None, ge=0)
    practice_hours: int | None = Field(default=None, ge=0)
    lab_hours: int | None = Field(default=None, ge=0)
    self_study_hours: int | None = Field(default=None, ge=0)
    total_hours: int | None = Field(default=None, ge=0)
    control_form: str | None = None
    department_name: str | None = None
    faculty_name: str | None = None
    chair_name: str | None = None
    subject_classification: SubjectClassificationSummary | None = None


class SubjectClassificationSummary(ContractModel):
    taxonomy_key: str
    taxonomy_version: str
    category_code: str
    category_name: str
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float]
    model: str
    run_key: ExternalKey
    review_status: Literal["classified", "needs_review"]
    review_reasons: list[str] = Field(default_factory=list)


class SubjectTaxonomyCategoryRecord(ContractModel):
    category_code: str
    ordinal: int = Field(ge=1, le=16)
    name: str
    definition: str


class SubjectTaxonomyRecord(ContractModel):
    taxonomy_key: str
    taxonomy_version: str
    name: str
    description: str
    categories: list[SubjectTaxonomyCategoryRecord]


class AdmissionCampaignRecord(SourcedRecord):
    external_key: ExternalKey
    university_key: ExternalKey
    year: int = Field(ge=1900, le=2200)
    education_level: str | None = None
    campaign_kind: str
    title: str
    date_note: str | None = None
    campus_key: ExternalKey | None = None
    campus_status: Literal["verified", "unverified", "not_stated"]


class CampaignCalendarEventRecord(SourcedRecord):
    external_key: ExternalKey
    campaign_key: ExternalKey
    event_code: str | None = None
    label: str
    context: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    date_value: date | None = None
    time_value: str | None = None
    date_text: str | None = None


class AdmissionOfferingRecord(SourcedRecord):
    external_key: ExternalKey
    campaign_key: ExternalKey
    direction_key: ExternalKey | None = None
    direction_code: str | None = None
    program_key: ExternalKey | None = None
    program_link_status: Literal["exact", "unresolved", "manual_review"]
    program_name_in_source: str | None = None
    department_key: ExternalKey | None = None
    department_code: str | None = None
    study_form: str | None = None
    language: str | None = None
    study_duration_label: str | None = None
    campus_scope: str | None = None
    places_total: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_program_link(self) -> AdmissionOfferingRecord:
        if self.program_link_status == "exact" and self.program_key is None:
            raise ValueError("exact program links require a program_key")
        if self.program_link_status != "exact" and self.program_key is not None:
            raise ValueError("unresolved program links cannot publish a program_key")
        return self


class CompetitionPoolRecord(SourcedRecord, TemporalFactRecord):
    external_key: ExternalKey
    campaign_key: ExternalKey
    offering_key: ExternalKey | None = None
    direction_key: ExternalKey | None = None
    direction_code: str | None = None
    department_key: ExternalKey | None = None
    department_code: str | None = None
    department_status: Literal["verified", "unverified", "unresolved", "not_stated"]
    scope_level: str | None = None
    funding_type: str | None = None
    quota_type: str | None = None
    places: int | None = Field(default=None, ge=0)
    places_by_source_row: list[dict[str, Any]] | None = None
    offering_keys: list[ExternalKey] = Field(default_factory=list)


class RequirementLeaf(ContractModel):
    kind: Literal["leaf"] = "leaf"
    node_key: ExternalKey
    subject_code: str | None = None
    subject_name: str | None = None
    minimum_score: Decimal | None = Field(default=None, ge=0)
    is_choice: bool | None = None
    tiebreak_rank: str | None = None
    sources: list[SourceReference] = Field(default_factory=list)


class RequirementOperatorNode(ContractModel):
    kind: Literal["operator"] = "operator"
    node_key: ExternalKey
    operator: RequirementOperator
    threshold: int | None = Field(default=None, ge=1)
    children: list[RequirementNode] = Field(min_length=1)
    sources: list[SourceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_operator_threshold(self) -> RequirementOperatorNode:
        if self.operator == "AT_LEAST" and self.threshold is None:
            raise ValueError("AT_LEAST nodes require a threshold")
        if self.operator == "AND" and self.threshold is not None:
            raise ValueError("AND nodes do not take a threshold")
        if self.operator == "OR" and self.threshold not in (None, 1):
            raise ValueError("OR threshold, when present, must be 1")
        if self.threshold is not None and self.threshold > len(self.children):
            raise ValueError("threshold cannot exceed the number of children")
        return self


RequirementNode: TypeAlias = Annotated[
    RequirementLeaf | RequirementOperatorNode,
    Field(discriminator="kind"),
]
RequirementOperatorNode.model_rebuild()


class RequirementTreeRecord(SourcedRecord, TemporalFactRecord):
    external_key: ExternalKey
    campaign_key: ExternalKey
    direction_key: ExternalKey | None = None
    direction_code: str | None = None
    applicant_category: str | None = None
    root: RequirementNode


class TuitionRecord(SourcedRecord, TemporalFactRecord):
    external_key: ExternalKey
    campaign_key: ExternalKey | None = None
    direction_key: ExternalKey | None = None
    direction_code: str | None = None
    direction_name: str | None = None
    program_key: ExternalKey | None = None
    academic_year: str | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    table_category: str | None = None
    campus_scope: str | None = None


class OfficialAdmissionStatisticRecord(SourcedRecord, TemporalFactRecord):
    external_key: ExternalKey
    campaign_key: ExternalKey | None = None
    direction_key: ExternalKey | None = None
    direction_code: str | None = None
    year: int = Field(ge=1900, le=2200)
    statistic_kind: str | None = None
    admission_stage: str | None = None
    competition_type: str | None = None
    status: str | None = None
    scope_type: str | None = None
    scope_label: str | None = None
    funding_type: str | None = None
    study_form: str | None = None
    score: Decimal | None = Field(default=None, ge=0)
    minimum_score: Decimal | None = Field(default=None, ge=0)
    maximum_score: Decimal | None = Field(default=None, ge=0)
    average_score: Decimal | None = Field(default=None, ge=0)
    admitted_count: int | None = Field(default=None, ge=0)
    snapshot_date: date | None = None


class IndividualAchievementRecord(SourcedRecord, TemporalFactRecord):
    external_key: ExternalKey
    campaign_key: ExternalKey | None = None
    code: str | None = None
    name: str
    points: Decimal | None = Field(default=None, ge=0)
    description: str | None = None
    required_document: str | None = None
    row_number: int | None = None


class AdmissionDocumentRecord(SourcedRecord):
    external_key: ExternalKey
    campaign_key: ExternalKey | None = None
    title: str
    document_type: str | None = None
    source_url: str | None = None
    published_at: date | None = None
    document_id: int | None = None
    document_group: str | None = None
    scope_tag: str | None = None
    captured: bool


class SourceArtifactRecord(ContractModel):
    external_key: ExternalKey
    source_url: str | None = None
    fetched_at: datetime | None = None
    sha256: Sha256 | None = None
    media_type: str | None = None
    raw_status: Literal[
        "saved",
        "unavailable",
        "failed",
        "not_captured",
        "omitted_by_user_request",
        "omitted_privacy_sensitive_applicant_records",
        "not_required",
    ]
    file_name: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    note: str | None = None


class SourceEvidenceRecord(ContractModel):
    external_key: ExternalKey
    source_artifact_key: ExternalKey
    field_path: str
    locator: dict[str, Any] | str | None = None
    claim: str | None = None
    observed_at: datetime | None = None
    verification_status: Literal["source_backed", "unverified", "manual_review"]


class RuleScopeRecord(ContractModel):
    scope_key: ExternalKey
    university_key: ExternalKey | None = None
    campaign_year: int | None = Field(default=None, ge=1900, le=2200)
    education_level_code: str | None = None
    audience_code: str | None = None
    surface_code: str | None = None


class RulePackVersionRecord(ContractModel):
    external_key: ExternalKey
    version: int = Field(ge=1)
    status: Literal["draft", "published", "retired"]
    scope: RuleScopeRecord
    checksum: Sha256
    valid_from: date
    valid_to: date | None = None
    body: dict[str, Any]

    @model_validator(mode="after")
    def validate_validity_period(self) -> RulePackVersionRecord:
        if self.valid_to is not None and self.valid_from >= self.valid_to:
            raise ValueError("valid_to must be later than valid_from")
        return self


class ManualReviewRecord(ContractModel):
    external_key: ExternalKey
    issue_type: str
    record_key: ExternalKey
    source_key: ExternalKey | None = None
    candidate_keys: list[ExternalKey] = Field(default_factory=list)
    reason: str
    status: Literal["open", "resolved", "dismissed"]
    target_key: ExternalKey | None = None
    source_url: str | None = None


class ManualReviewSummaryRecord(ContractModel):
    release_key: ExternalKey
    total_count: int = Field(ge=0)
    open_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    dismissed_count: int = Field(ge=0)


class ReleaseMetadataRecord(ContractModel):
    release_key: ExternalKey
    source_bundle_sha256: Sha256
    mapper_version: str
    activated_at: datetime
    reconciliation_status: Literal["passed", "passed_with_gaps"]
    schema_revision: str


class DirectionPage(PageResponse[DirectionRecord]):
    """Typed paginated directions response published in the v1 schema."""


class OfferingPage(PageResponse[AdmissionOfferingRecord]):
    """Typed paginated offerings response published in the v1 schema."""


CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    ApiDescription,
    LivenessRecord,
    ReadinessRecord,
    ApiFieldIssue,
    ApiError,
    ApiErrorEnvelope,
    PaginationMetadata,
    DataGap,
    SourceReference,
    SourceEvidenceReference,
    TemporalFactRecord,
    UniversityRecord,
    DirectionRecord,
    DepartmentRelation,
    DepartmentRecord,
    EducationalProgramRecord,
    CatalogCourseRecord,
    StudyPlanRecord,
    CurriculumItemRecord,
    AdmissionCampaignRecord,
    CampaignCalendarEventRecord,
    AdmissionOfferingRecord,
    CompetitionPoolRecord,
    RequirementLeaf,
    RequirementOperatorNode,
    RequirementTreeRecord,
    TuitionRecord,
    OfficialAdmissionStatisticRecord,
    AdmissionDocumentRecord,
    IndividualAchievementRecord,
    SourceArtifactRecord,
    SourceEvidenceRecord,
    RuleScopeRecord,
    RulePackVersionRecord,
    ManualReviewRecord,
    ManualReviewSummaryRecord,
    ReleaseMetadataRecord,
    DirectionPage,
    OfferingPage,
)


def contract_schema_registry() -> dict[str, Any]:
    """Return all DTO schemas keyed by their stable public model names."""
    return {model.__name__: model.model_json_schema() for model in CONTRACT_MODELS}
