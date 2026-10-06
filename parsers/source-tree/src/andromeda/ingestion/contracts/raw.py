from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self, TypeAlias

from pydantic import Field, HttpUrl, model_validator

from ...shared.contracts.base import ContractModel
from ...shared.contracts.ids import UniversityId

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class RawSourceSnapshot(ContractModel):
    source_kind: str = Field(min_length=1, max_length=128)
    requested_url: HttpUrl
    final_url: HttpUrl
    status_code: int = Field(strict=True, ge=200, le=599)
    content_type: str | None = Field(default=None, max_length=256)
    captured_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    body: bytes = Field(min_length=1)
    response_class: str = Field(default="success", min_length=1, max_length=64)
    access_mode: str = Field(default="http", min_length=1, max_length=32)
    truncated: bool = False


class SourceLocator(ContractModel):
    source_url: HttpUrl
    page: int | None = Field(default=None, strict=True, ge=1)
    row: int | None = Field(default=None, strict=True, ge=1)
    field: str | None = Field(default=None, min_length=1, max_length=128)


class RawUniversityRecord(ContractModel):
    name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    address: str = Field(min_length=1)
    official_site: HttpUrl
    locator: SourceLocator


class RawDirectionRecord(ContractModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    education_level: str = Field(min_length=1)
    locator: SourceLocator


class RawSourceGap(ContractModel):
    """Published source fact that could not be projected into a domain row."""

    id: str = Field(min_length=1, max_length=384)
    entity_type: str = Field(min_length=1, max_length=64)
    entity_key: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=512)
    source_url: HttpUrl
    locator: SourceLocator


class RawParserDiagnostic(ContractModel):
    """Structured parser warning retained alongside raw source evidence."""

    code: str = Field(min_length=1, max_length=128)
    stage: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)
    severity: Literal["info", "warning", "ambiguous"] = "warning"
    source_url: HttpUrl | None = None
    candidates: tuple[str, ...] = ()
    count: int = Field(default=1, strict=True, ge=1, le=100_000)


class RawProgramRecord(ContractModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    direction_code: str = Field(min_length=1)
    education_level: str = Field(min_length=1)
    education_year: int = Field(strict=True, ge=2000, le=2100)
    study_plan_url: HttpUrl
    source_url: HttpUrl
    locator: SourceLocator
    source_code: str | None = Field(default=None, min_length=1, max_length=256)


class RawCurriculumRow(ContractModel):
    program_code: str = Field(min_length=1)
    discipline: str = Field(min_length=1)
    semester: int | None = Field(default=None, strict=True, ge=1, le=12)
    hours: int = Field(strict=True, ge=0, le=2_000)
    credits: str | float | int | None = None
    assessment: str | None = None
    source_position: int | None = Field(default=None, strict=True, ge=1, le=10_000)
    source_url: HttpUrl
    locator: SourceLocator
    source_program_code: str | None = Field(default=None, min_length=1, max_length=256)


class RawAdmissionExamRequirement(ContractModel):
    subject: str = Field(min_length=1, max_length=256)
    source_name: str = Field(min_length=1, max_length=256)
    minimum_score: Decimal | None = Field(default=None, strict=True, ge=0, le=100, max_digits=5, decimal_places=2)
    is_choice: bool = False
    is_required: bool = True


class RawAdmissionQuota(ContractModel):
    quota_type: str = Field(min_length=1, max_length=64)
    source_name: str = Field(min_length=1, max_length=256)
    places: int = Field(strict=True, ge=0, le=100_000)


class RawAdmissionPassingScore(ContractModel):
    score_type: str = Field(min_length=1, max_length=64)
    competition_type: str = Field(default="general", min_length=1, max_length=64)
    status: str = Field(default="numeric", min_length=1, max_length=32)
    score: Decimal | None = Field(default=None, strict=True, ge=0, le=400, max_digits=6, decimal_places=2)

    @model_validator(mode="after")
    def validate_score_status(self) -> Self:
        if self.status == "numeric" and self.score is None:
            raise ValueError("numeric admission passing score must contain score")
        if self.status == "bvi" and self.score is not None:
            raise ValueError("BVI admission passing score must not contain score")
        if self.status not in {"numeric", "bvi"}:
            raise ValueError("unsupported admission passing score status")
        if self.status == "bvi" and self.competition_type not in {
            "bvi",
            "special_quota",
            "separate_quota",
            "targeted",
        }:
            raise ValueError("BVI admission passing score must use a BVI or quota competition type")
        return self


class RawAdmissionTuition(ContractModel):
    amount: Decimal = Field(strict=True, ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(min_length=1, max_length=16)
    academic_year: str | None = Field(default=None, min_length=4, max_length=32)
    period: str | None = Field(default=None, min_length=1, max_length=512)
    study_form: str | None = Field(default=None, min_length=1, max_length=64)
    is_discounted: bool = False


class RawAdmissionRecord(ContractModel):
    id: str = Field(min_length=1, max_length=384)
    program_code: str = Field(min_length=1, max_length=64)
    program_name: str | None = Field(default=None, min_length=1, max_length=512)
    admission_year: int = Field(strict=True, ge=2000, le=2100)
    study_form: str | None = Field(default=None, min_length=1, max_length=64)
    funding_type: str | None = Field(default=None, min_length=1, max_length=64)
    scope: str = Field(default="program", min_length=1, max_length=32)
    places: int | None = Field(default=None, strict=True, ge=0, le=100_000)
    exams: tuple[RawAdmissionExamRequirement, ...] = ()
    quotas: tuple[RawAdmissionQuota, ...] = ()
    passing_scores: tuple[RawAdmissionPassingScore, ...] = ()
    tuition: tuple[RawAdmissionTuition, ...] = ()
    source_kind: str = Field(min_length=1, max_length=256)
    source_url: HttpUrl
    locator: SourceLocator
    source_program_code: str | None = Field(default=None, min_length=1, max_length=256)


class RawVenueRecord(ContractModel):
    external_key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=512)
    address: str | None = Field(default=None, min_length=1, max_length=1024)
    latitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-90"), le=Decimal("90"), max_digits=9, decimal_places=6)
    longitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-180"), le=Decimal("180"), max_digits=9, decimal_places=6)


class RawCampusPointRecord(ContractModel):
    external_key: str = Field(min_length=1, max_length=128)
    point_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=512)
    address: str | None = Field(default=None, min_length=1, max_length=1024)
    latitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-90"), le=Decimal("90"), max_digits=9, decimal_places=6)
    longitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-180"), le=Decimal("180"), max_digits=9, decimal_places=6)
    university_ids: tuple[UniversityId, ...] = Field(min_length=1)
    department_codes: tuple[str, ...] = ()
    program_codes: tuple[str, ...] = ()
    source_kind: str = Field(min_length=1, max_length=128)
    source_url: HttpUrl
    locator: SourceLocator

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("campus point latitude and longitude must be provided together")
        return self


class RawEventRecord(ContractModel):
    external_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=64)
    format: str = Field(min_length=1, max_length=32)
    starts_at: datetime
    ends_at: datetime | None = None
    description: str | None = Field(default=None, min_length=1, max_length=10_000)
    registration_url: HttpUrl | None = None
    university_ids: tuple[UniversityId, ...] = Field(min_length=1)
    department_codes: tuple[str, ...] = ()
    program_codes: tuple[str, ...] = ()
    venue: RawVenueRecord | None = None
    source_kind: str = Field(min_length=1, max_length=128)
    source_url: HttpUrl
    locator: SourceLocator


class RawTracerBundle(ContractModel):
    snapshots: tuple[RawSourceSnapshot, ...] = Field(min_length=1)
    university: RawUniversityRecord
    direction: RawDirectionRecord
    programs: tuple[RawProgramRecord, ...] = Field(min_length=1)
    curriculum_rows: tuple[RawCurriculumRow, ...] = ()
    directions: tuple[RawDirectionRecord, ...] = ()
    source_gaps: tuple[RawSourceGap, ...] = ()
    diagnostics: tuple[RawParserDiagnostic, ...] = ()
    admissions: tuple[RawAdmissionRecord, ...] = ()
    events: tuple[RawEventRecord, ...] = ()
    campus_points: tuple[RawCampusPointRecord, ...] = ()
