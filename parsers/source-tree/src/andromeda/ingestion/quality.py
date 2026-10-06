"""Pre-publication quality evaluation for captured canonical snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from ..shared.contracts.provenance import GapSeverity
from .contracts.normalized import CanonicalSnapshot
from .contracts.raw import RawTracerBundle
from .contracts.source import gap_severity_for_reason
from .taxonomy_metrics import calculate_taxonomy_metrics


QualityStatus = Literal["passed", "degraded", "rejected"]


@dataclass(frozen=True, slots=True)
class PreviousProjection:
    run_id: str
    university_id: str
    program_count: int
    curriculum_item_count: int
    source_count: int
    program_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class QualityOutcome:
    status: QualityStatus
    metrics: Mapping[str, object]
    blocking_reasons: tuple[str, ...] = ()
    degradable_reasons: tuple[str, ...] = ()
    previous_good_run_id: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status in {"passed", "degraded"}


def evaluate_quality(
    raw: RawTracerBundle,
    canonical: CanonicalSnapshot,
    *,
    previous: PreviousProjection | None = None,
    minimum_relative_count: float = 0.25,
    run_id: str | None = None,
) -> QualityOutcome:
    """Evaluate blocking regressions before canonical projection.

    The thresholds are deliberately conservative and count-based. They are
    versioned in the stored metrics and can be tightened per adapter after a
    reviewed baseline, without moving university-specific parsing into core.
    """

    program_ids = frozenset(str(program.id) for program in canonical.programs)
    curriculum_program_ids = frozenset(str(curriculum.program_id) for curriculum in canonical.curricula if curriculum.items)
    admission_program_ids = frozenset(str(admission.program_id) for admission in canonical.admissions)
    curriculum_item_count = sum(len(curriculum.items) for curriculum in canonical.curricula)
    critical_gap_count = sum(
        1
        for gap in canonical.source_gaps
        if is_critical_gap(gap.reason)
    )
    taxonomy_metrics = calculate_taxonomy_metrics(
        canonical,
        source_hashes=tuple(snapshot.content_sha256 for snapshot in raw.snapshots),
        run_id=run_id,
    )
    unknown_taxonomy_count = taxonomy_metrics.unresolved_count + taxonomy_metrics.fallback_count
    metrics: dict[str, object] = {
        "policy_version": "mvp023.v1",
        "program_count": len(program_ids),
        "curriculum_count": len(canonical.curricula),
        "curriculum_item_count": curriculum_item_count,
        "curriculum_coverage": _ratio(len(curriculum_program_ids), len(program_ids)),
        "admission_coverage": _ratio(len(admission_program_ids), len(program_ids)),
        "source_count": len(raw.snapshots),
        "source_hash_count": len({snapshot.content_sha256 for snapshot in raw.snapshots}),
        "source_gap_count": len(canonical.source_gaps),
        "critical_gap_count": critical_gap_count,
        "unknown_taxonomy_count": unknown_taxonomy_count,
        "taxonomy_metric_version": taxonomy_metrics.metric_version,
        "taxonomy_version": taxonomy_metrics.taxonomy_version,
        "taxonomy_coverage": taxonomy_metrics.classification_coverage,
        "taxonomy_unresolved_count": taxonomy_metrics.unresolved_count,
        "taxonomy_fallback_count": taxonomy_metrics.fallback_count,
        "taxonomy": taxonomy_metrics.model_dump(mode="json"),
        "identity_count": len(program_ids),
    }

    blocking: list[str] = []
    degradable: list[str] = []
    if not program_ids:
        blocking.append("catalog_empty")
    if not canonical.disciplines:
        blocking.append("discipline_catalog_empty")
    if len(curriculum_program_ids) < len(program_ids) * 0.5:
        blocking.append("curriculum_coverage_below_50_percent")
    if critical_gap_count:
        blocking.append("critical_source_gap")
    if unknown_taxonomy_count:
        degradable.append("taxonomy_unknown")
    if taxonomy_metrics.outcome_count < taxonomy_metrics.discipline_count:
        degradable.append("taxonomy_outcome_missing")
    if len(curriculum_program_ids) < len(program_ids):
        degradable.append("curriculum_partial")
    if len(admission_program_ids) < len(program_ids):
        degradable.append("admission_partial")
    if raw.diagnostics:
        degradable.append("parser_diagnostics_present")

    if previous is not None:
        metrics.update(
            {
                "previous_good_run_id": previous.run_id,
                "program_count_ratio": _ratio(len(program_ids), previous.program_count),
                "curriculum_item_count_ratio": _ratio(curriculum_item_count, previous.curriculum_item_count),
                "source_count_ratio": _ratio(len(raw.snapshots), previous.source_count),
                "identity_continuity": _ratio(len(program_ids & previous.program_ids), len(previous.program_ids)),
            }
        )
        for name, current, old in (
            ("program_count", len(program_ids), previous.program_count),
            ("curriculum_item_count", curriculum_item_count, previous.curriculum_item_count),
            ("source_count", len(raw.snapshots), previous.source_count),
        ):
            if old > 0 and current < old * minimum_relative_count:
                blocking.append(f"{name}_regression")
        if previous.program_ids and len(program_ids & previous.program_ids) < len(previous.program_ids) * minimum_relative_count:
            blocking.append("program_identity_continuity_regression")
    else:
        degradable.append("no_previous_good_projection")

    status: QualityStatus = "rejected" if blocking else "degraded" if degradable else "passed"
    metrics["decision"] = status
    metrics["blocking_reason_count"] = len(blocking)
    metrics["degradable_reason_count"] = len(degradable)
    return QualityOutcome(
        status=status,
        metrics=metrics,
        blocking_reasons=tuple(dict.fromkeys(blocking)),
        degradable_reasons=tuple(dict.fromkeys(degradable)),
        previous_good_run_id=previous.run_id if previous is not None else None,
    )


def is_critical_gap(reason: str) -> bool:
    return gap_severity_for_reason(reason) is GapSeverity.BLOCKING


def _ratio(current: int | float, previous: int | float) -> float:
    if previous == 0:
        return 1.0 if current == 0 else float(current)
    return round(float(current) / float(previous), 6)


__all__ = ["PreviousProjection", "QualityOutcome", "QualityStatus", "evaluate_quality", "is_critical_gap"]
