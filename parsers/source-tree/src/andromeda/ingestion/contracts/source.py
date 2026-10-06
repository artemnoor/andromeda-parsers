from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from ...shared.contracts.errors import ContractError, ErrorCode, ErrorDetail
from ...shared.contracts.provenance import GapSeverity, SourceGapReference
from .constraints import http_url
from .raw import RawSourceGap, RawSourceSnapshot, SourceLocator


@dataclass(frozen=True, slots=True)
class CapturedSources:
    snapshots: tuple[RawSourceSnapshot, ...]
    source_gaps: tuple[RawSourceGap, ...] = ()

    def by_kind(self, kind: str) -> tuple[RawSourceSnapshot, ...]:
        return tuple(snapshot for snapshot in self.snapshots if snapshot.source_kind == kind)

    def first(self, kind: str) -> RawSourceSnapshot:
        matches = self.by_kind(kind)
        if len(matches) != 1:
            raise ContractError(
                ErrorCode.SOURCE_CONTRACT_ERROR,
                "Expected exactly one source snapshot",
                (ErrorDetail(path="source.snapshots", message=f"invalid count for {kind}", type="source_selection"),),
            )
        return matches[0]


def source_fetch_gap(source_kind: str, source_url: str, reason: str) -> RawSourceGap:
    """Build a stable gap for a rejected/unavailable source before parsing."""

    url = http_url(source_url)
    key = f"source|{source_kind}|{url}|{reason}"
    return RawSourceGap(
        id=f"source-gap:{sha256(key.encode('utf-8')).hexdigest()[:24]}",
        entity_type="source",
        entity_key=f"{source_kind}:{str(url)[:240]}",
        reason=reason,
        source_url=url,
        locator=SourceLocator(source_url=url),
    )


def source_gap_reference(
    gap: RawSourceGap,
    *,
    field: str | None = None,
    record_key: str | None = None,
) -> SourceGapReference:
    """Convert an ingestion gap into a safe application-facing summary."""

    severity = gap_severity_for_reason(gap.reason)
    code = "".join(character if character.isalnum() else "_" for character in gap.reason.casefold()).strip("_")[:96] or "source_gap"
    return SourceGapReference(
        code=code,
        severity=severity,
        message=gap.reason,
        source_url=gap.source_url,
        field=field,
        record_key=record_key,
        can_continue=severity is not GapSeverity.BLOCKING,
    )


_INFORMATIONAL_GAP_REASONS = frozenset(
    {
        "admission-program-identity-unknown",
        "order_direction_not_in_catalog",
        "unsupported_document_kind",
    }
)

_DEGRADABLE_GAP_REASONS = frozenset(
    {
        "admission-program-identity-ambiguous",
        "admission_year_unknown",
        "direction_section_not_published",
        "document_missing",
        "enrollment-program-identity-ambiguous",
        "program education year is absent from official sources",
        "program-education-year-missing-from-official-source",
        "passing_score_missing",
        "published study plans contain no parseable work-plan rows",
        "work-plan-document-produced-no-rows",
        "work-plan-program-identity-ambiguous",
    }
)


def gap_severity_for_reason(reason: str) -> GapSeverity:
    """Classify known source gaps without hiding unknown core failures.

    University adapters emit some expected partial-data conditions while
    parsing otherwise valid sources. Those conditions must be visible to
    consumers without rejecting a complete catalog projection. Unknown gaps
    that mention program/curriculum/identity concepts remain blocking by
    default; unrelated new gap codes remain degradable until explicitly
    reviewed.
    """

    normalized = reason.casefold().strip()
    if normalized in _INFORMATIONAL_GAP_REASONS:
        return GapSeverity.INFORMATIONAL
    if normalized in _DEGRADABLE_GAP_REASONS or normalized.startswith("competition_heading_unknown"):
        return GapSeverity.DEGRADABLE
    if any(token in normalized for token in ("direction", "program", "curriculum", "study-plan", "work-plan", "admission")):
        return GapSeverity.BLOCKING
    return GapSeverity.DEGRADABLE


__all__ = ["CapturedSources", "RawSourceSnapshot", "gap_severity_for_reason", "source_fetch_gap", "source_gap_reference"]
