"""Deterministic, explainable selection of published policy versions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

logger = logging.getLogger("academic_data_service.rules")


@dataclass(frozen=True, slots=True)
class RuleScope:
    """Exact typed scope axes; a null candidate axis is a wildcard."""

    scope_key: str
    university_key: str | None = None
    campaign_year: int | None = None
    education_level_code: str | None = None
    audience_code: str | None = None
    surface_code: str | None = None

    @property
    def specificity(self) -> int:
        return sum(
            value is not None
            for value in (
                self.university_key,
                self.campaign_year,
                self.education_level_code,
                self.audience_code,
                self.surface_code,
            )
        )

    def applies_to(self, request: RuleScope) -> bool:
        axes = (
            "university_key",
            "campaign_year",
            "education_level_code",
            "audience_code",
            "surface_code",
        )
        return all(
            getattr(self, axis) is None or getattr(self, axis) == getattr(request, axis)
            for axis in axes
        )


@dataclass(frozen=True, slots=True)
class RuleVersionCandidate:
    rule_pack_version_key: str
    version: int
    status: str
    scope: RuleScope
    checksum: str
    valid_from: date
    valid_to: date | None
    body: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ResolvedRuleVersion:
    rule_pack_version_key: str
    version: int
    scope: RuleScope
    checksum: str
    body: dict[str, Any]


class RuleResolutionError(ValueError):
    """Base typed error for policy resolution failures."""

    code = "rule_resolution_error"


class RuleVersionNotFoundError(RuleResolutionError):
    """No published, date-valid policy applies to the requested scope."""

    code = "rule_version_not_found"


class AmbiguousRuleScopeError(RuleResolutionError):
    """Two equally specific wildcard scopes apply; the resolver will not guess."""

    code = "ambiguous_rule_scope"

    def __init__(self, scope_keys: list[str]) -> None:
        self.scope_keys = tuple(sorted(scope_keys))
        super().__init__(f"equally specific rule scopes match: {', '.join(self.scope_keys)}")


def resolve_rule_pack_version(
    candidates: list[RuleVersionCandidate],
    request_scope: RuleScope,
    on_date: date,
) -> ResolvedRuleVersion:
    """Choose the most specific active published version or return a stable error."""

    logger.debug(
        "rule version resolution started",
        extra={
            "event": "rules.resolve.started",
            "request_scope_key": request_scope.scope_key,
            "candidate_count": len(candidates),
            "on_date": on_date.isoformat(),
        },
    )
    applicable = [
        candidate
        for candidate in candidates
        if candidate.status == "published"
        and candidate.valid_from <= on_date
        and (candidate.valid_to is None or on_date < candidate.valid_to)
        and candidate.scope.applies_to(request_scope)
    ]
    if not applicable:
        logger.info(
            "no published rule version matched",
            extra={
                "event": "rules.resolve.not_found",
                "request_scope_key": request_scope.scope_key,
                "on_date": on_date.isoformat(),
                "outcome": "not_found",
            },
        )
        raise RuleVersionNotFoundError("no active published rule version matches the request")

    highest_specificity = max(candidate.scope.specificity for candidate in applicable)
    best = [
        candidate for candidate in applicable if candidate.scope.specificity == highest_specificity
    ]
    if len(best) != 1:
        scope_keys = sorted({candidate.scope.scope_key for candidate in best})
        logger.warning(
            "equally specific rule scopes matched",
            extra={
                "event": "rules.resolve.ambiguous",
                "request_scope_key": request_scope.scope_key,
                "candidate_scope_keys": scope_keys,
                "outcome": "ambiguous",
            },
        )
        raise AmbiguousRuleScopeError(scope_keys)

    selected = best[0]
    logger.info(
        "published rule version resolved",
        extra={
            "event": "rules.resolve.completed",
            "request_scope_key": request_scope.scope_key,
            "selected_scope_key": selected.scope.scope_key,
            "rule_pack_version_key": selected.rule_pack_version_key,
            "rule_version": selected.version,
            "rule_checksum": selected.checksum,
            "outcome": "resolved",
        },
    )
    return ResolvedRuleVersion(
        rule_pack_version_key=selected.rule_pack_version_key,
        version=selected.version,
        scope=selected.scope,
        checksum=selected.checksum,
        body=selected.body,
    )
