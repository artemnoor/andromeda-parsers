from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from pydantic import Field

from ..modules.disciplines.contracts.classification import ClassificationOutcome, TAXONOMY_VERSION
from ..modules.disciplines.domain.areas import DisciplineAreaCode
from ..shared.contracts.base import ContractModel
from ..shared.contracts.ids import SourceHash
from .contracts.normalized import CanonicalSnapshot


TAXONOMY_METRICS_VERSION = "taxonomy-metrics.v1"


class TaxonomyAreaUsage(ContractModel):
    area: DisciplineAreaCode
    discipline_count: int = Field(strict=True, ge=0)


class TaxonomyMetrics(ContractModel):
    metric_version: str = TAXONOMY_METRICS_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    run_id: str | None = None
    source_hashes: tuple[SourceHash, ...] = ()
    discipline_count: int = Field(strict=True, ge=0)
    outcome_count: int = Field(strict=True, ge=0)
    classified_count: int = Field(strict=True, ge=0)
    classification_coverage: float = Field(strict=True, ge=0, le=1)
    unresolved_count: int = Field(strict=True, ge=0)
    fallback_count: int = Field(strict=True, ge=0)
    explicit_universal_count: int = Field(strict=True, ge=0)
    exact_override_count: int = Field(strict=True, ge=0)
    alias_count: int = Field(strict=True, ge=0)
    keyword_rule_count: int = Field(strict=True, ge=0)
    conflicting_mapping_count: int = Field(strict=True, ge=0)
    duplicate_normalized_key_count: int = Field(strict=True, ge=0)
    affected_program_count: int = Field(strict=True, ge=0)
    unresolved_program_count: int = Field(strict=True, ge=0)
    area_usage: tuple[TaxonomyAreaUsage, ...] = ()


def calculate_taxonomy_metrics(
    canonical: CanonicalSnapshot,
    *,
    source_hashes: Sequence[str] = (),
    run_id: str | None = None,
) -> TaxonomyMetrics:
    outcomes = canonical.classification_outcomes
    methods = {"unresolved", "fallback"}
    classified_count = sum(1 for outcome in outcomes if outcome.method not in methods)
    unresolved_count = sum(1 for outcome in outcomes if outcome.method == "unresolved")
    fallback_count = sum(1 for outcome in outcomes if outcome.method == "fallback")
    by_name: dict[str, set[tuple[tuple[str, str], ...]]] = defaultdict(set)
    area_usage: dict[DisciplineAreaCode, set[str]] = defaultdict(set)
    unresolved_ids = {
        outcome.discipline_id
        for outcome in outcomes
        if outcome.method in methods
    }
    for outcome in outcomes:
        vector_key = tuple((weight.area.value, str(weight.weight)) for weight in outcome.area_weights)
        by_name[outcome.normalized_name].add(vector_key)
        for weight in outcome.area_weights:
            area_usage[weight.area].add(outcome.discipline_id)
    duplicate_normalized_key_count = sum(max(0, len(values) - 1) for values in by_name.values())
    conflicting_mapping_count = sum(1 for values in by_name.values() if len(values) > 1)
    unresolved_program_ids = {
        str(curriculum.program_id)
        for curriculum in canonical.curricula
        for item in curriculum.items
        if item.discipline_id in unresolved_ids
    }
    taxonomy_version = _single_or_mixed(outcome.taxonomy_version for outcome in outcomes)
    return TaxonomyMetrics(
        taxonomy_version=taxonomy_version,
        run_id=run_id,
        source_hashes=tuple(sorted(set(source_hashes))),
        discipline_count=len(canonical.disciplines),
        outcome_count=len(outcomes),
        classified_count=classified_count,
        classification_coverage=round(classified_count / len(outcomes), 6) if outcomes else 0.0,
        unresolved_count=unresolved_count,
        fallback_count=fallback_count,
        explicit_universal_count=sum(1 for outcome in outcomes if outcome.method == "explicit_universal"),
        exact_override_count=sum(1 for outcome in outcomes if outcome.method == "exact_override"),
        alias_count=sum(1 for outcome in outcomes if outcome.method == "alias"),
        keyword_rule_count=sum(1 for outcome in outcomes if outcome.method == "keyword_rule"),
        conflicting_mapping_count=conflicting_mapping_count,
        duplicate_normalized_key_count=duplicate_normalized_key_count,
        affected_program_count=len(canonical.programs),
        unresolved_program_count=len(unresolved_program_ids),
        area_usage=tuple(
            TaxonomyAreaUsage(area=area, discipline_count=len(ids))
            for area, ids in sorted(area_usage.items(), key=lambda item: item[0].value)
        ),
    )


def _single_or_mixed(values: Iterable[str]) -> str:
    resolved = tuple(values)
    if not resolved:
        return TAXONOMY_VERSION
    unique = tuple(dict.fromkeys(resolved))
    return unique[0] if len(unique) == 1 else "mixed"


__all__ = ["TAXONOMY_METRICS_VERSION", "TaxonomyAreaUsage", "TaxonomyMetrics", "calculate_taxonomy_metrics"]
