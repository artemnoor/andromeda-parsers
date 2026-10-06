"""Result value objects shared by proftest services and API adapters."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import IngestRunId, NonEmptyText, ProgramCode, ProgramId, ShortText
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference

from .adaptive import AdaptiveSelection
from .entities import ActivityCode, ProgramFingerprint, Question, UserProfile


class MetricStatus(StrEnum):
    NOT_AVAILABLE = "not_available"


class EvidenceStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    NOT_AVAILABLE = "not_available"


class EvidenceSignal(StrEnum):
    PROFILE_SUBJECT_PREFERENCE = "profile_subject_preference"
    PROFILE_ACTIVITY_PREFERENCE = "profile_activity_preference"
    PROFILE_ANTI_INTEREST = "profile_anti_interest"
    CURRICULUM_AREA_SHARE = "curriculum_area_share"
    CURRICULUM_ACTIVITY_MAPPING = "curriculum_activity_mapping"
    DISTINCTIVE_SUBJECT = "distinctive_subject"
    SEMESTER_DISTRIBUTION = "semester_distribution"


class EvidenceMetric(ContractModel):
    """A bounded evidence-quality metric, never a missing-data sentinel."""

    value: Decimal | None = Field(default=None, strict=True, ge=0, le=1, max_digits=5, decimal_places=4)
    status: EvidenceStatus


class SourceFreshness(EvidenceMetric):
    """Deterministic source snapshot metadata used by reliability evidence.

    The value describes source snapshot identity consistency, not predictive
    accuracy and not an age-relative-to-now claim.  A temporal SLA belongs to
    ingestion operations, while recommendation replay must remain deterministic.
    """

    latest_captured_at: datetime | None = None
    run_ids: tuple[IngestRunId, ...] = Field(default=(), max_length=8)
    snapshot_consistent: bool | None = None


class ReasonKind(StrEnum):
    FIT = "fit"
    ANTI_FIT = "anti_fit"


class OptionalMetric(ContractModel):
    status: MetricStatus = MetricStatus.NOT_AVAILABLE
    value: int | None = Field(default=None, strict=True, ge=0, le=100)


class ScoreBreakdown(ContractModel):
    subject_fit: Decimal = Field(strict=True, ge=0, le=100)
    activity_fit: Decimal = Field(strict=True, ge=0, le=100)
    distinctive_fit: Decimal = Field(strict=True, ge=0, le=100)
    anti_penalty: Decimal = Field(strict=True, ge=0, le=100)
    raw_content_fit: Decimal


class MatchScore(ContractModel):
    program_id: ProgramId
    program_code: ProgramCode
    content_fit: int = Field(strict=True, ge=0, le=100)
    breakdown: ScoreBreakdown


class MatchReason(ContractModel):
    kind: ReasonKind
    area: DisciplineAreaCode | None = None
    activity: ActivityCode | None = None
    text: NonEmptyText
    workload: Decimal = Field(strict=True, ge=0)
    share: Decimal = Field(strict=True, ge=0, le=1, max_digits=7, decimal_places=4)
    source_names: tuple[ShortText, ...] = ()
    provenance: tuple[SourceAttribution, ...] = ()


class Recommendation(ContractModel):
    program_id: ProgramId
    program_code: ProgramCode
    program_name: NonEmptyText
    content_fit: int = Field(strict=True, ge=0, le=100)
    score: MatchScore
    reasons: tuple[MatchReason, ...] = ()
    anti_fit_reasons: tuple[MatchReason, ...] = ()
    area_share: dict[DisciplineAreaCode, Decimal] = Field(default_factory=dict)
    semester_distribution: dict[str, Decimal] = Field(default_factory=dict)
    distinctive_subjects: tuple[str, ...] = ()
    admission_fit: OptionalMetric = Field(default_factory=OptionalMetric)
    provenance: tuple[SourceAttribution, ...] = ()
    source_gaps: tuple[SourceGapReference, ...] = ()
    evidence: "RecommendationEvidence" = Field(default_factory=lambda: RecommendationEvidence.unavailable())

    @classmethod
    def from_fingerprint(cls, fingerprint: ProgramFingerprint, score: MatchScore) -> "Recommendation":
        return cls(
            program_id=fingerprint.program_id,
            program_code=fingerprint.program_code,
            program_name=fingerprint.program_name,
            content_fit=score.content_fit,
            score=score,
            area_share=fingerprint.area_share,
            semester_distribution=fingerprint.semester_distribution,
            distinctive_subjects=tuple(subject.source_name for subject in fingerprint.distinctive_subjects),
            provenance=fingerprint.provenance,
            source_gaps=fingerprint.source_gaps,
        )


class RecommendationEvidence(ContractModel):
    """Typed reliability envelope independent from the Content Fit score."""

    profile_confidence: EvidenceMetric
    catalog_completeness: EvidenceMetric
    source_freshness: SourceFreshness
    reliability: EvidenceMetric
    signals_used: tuple[EvidenceSignal, ...] = Field(default=(), max_length=8)
    inferred_signals: tuple[EvidenceSignal, ...] = Field(default=(), max_length=8)
    missing_data: tuple[SourceGapReference, ...] = Field(default=(), max_length=16)
    policy_version: ShortText
    taxonomy_version: ShortText
    question_set_version: ShortText | None = None
    profile_revision: int | None = Field(default=None, strict=True, ge=1)
    catalog_run_ids: tuple[IngestRunId, ...] = Field(default=(), max_length=8)

    @classmethod
    def unavailable(cls) -> "RecommendationEvidence":
        metric = EvidenceMetric(value=None, status=EvidenceStatus.NOT_AVAILABLE)
        return cls(
            profile_confidence=metric,
            catalog_completeness=metric,
            source_freshness=SourceFreshness(value=None, status=EvidenceStatus.NOT_AVAILABLE),
            reliability=metric,
            policy_version="content-fit.v1",
            taxonomy_version="taxonomy-22.v1",
        )


class PreviewCandidate(ContractModel):
    program_id: ProgramId
    program_code: ProgramCode
    content_fit: int = Field(strict=True, ge=0, le=100)


class ProftestPreview(ContractModel):
    profile: UserProfile
    adaptive: AdaptiveSelection
    question: Question | None = None
    candidates: tuple[PreviewCandidate, ...] = ()


class ProftestResults(ContractModel):
    profile: UserProfile
    recommendations: tuple[Recommendation, ...] = ()


__all__ = [
    "MatchReason",
    "MatchScore",
    "MetricStatus",
    "EvidenceMetric",
    "EvidenceSignal",
    "EvidenceStatus",
    "OptionalMetric",
    "PreviewCandidate",
    "ProftestPreview",
    "ProftestResults",
    "ReasonKind",
    "Recommendation",
    "RecommendationEvidence",
    "ScoreBreakdown",
    "SourceFreshness",
]
