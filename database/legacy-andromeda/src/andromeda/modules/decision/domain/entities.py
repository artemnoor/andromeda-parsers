"""Pure, user-owned decision entities.

The entities in this module contain explicit choice state only.  Candidate
recommendations and admission/content evidence are deliberately represented by
separate result contracts so a refresh can never mutate a user's shortlist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Literal, Self

from pydantic import Field, model_validator

from andromeda.modules.admission_fit.contracts.public import ApplicantAdmissionProfile
from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.modules.proftest.contracts.public import UserProfile
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EducationYear, NonEmptyText, ProgramId, ShortText

from .values import DecisionId, DecisionSourceKind, DecisionStatus, ShortlistEntryState, ShortlistRole


logger = logging.getLogger("andromeda.modules.decision.domain")
ZERO = Decimal("0")


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _ensure_aware(value: datetime) -> datetime:
    if not _is_aware(value):
        logger.warning("decision_domain_rejected invariant=timezone_aware_timestamp")
        raise ValueError("decision timestamps must be timezone-aware")
    return value


class AdmissionConstraints(ContractModel):
    """Admission facts explicitly supplied by a user.

    This contract intentionally contains no Content Fit or recommendation
    score.  ``None`` means that a dimension is unknown, not that its value is
    zero or that the user chose a default.
    """

    version: Literal[1] = 1
    applicant: ApplicantAdmissionProfile | None = None
    admission_year: EducationYear | None = None
    funding_preference: FundingType | None = None
    study_form: StudyForm | None = None
    max_tuition: Decimal | None = Field(
        default=None,
        strict=True,
        ge=ZERO,
        max_digits=12,
        decimal_places=2,
    )
    location: ShortText | None = None


class ShortlistEntry(ContractModel):
    """One explicit, restorable user choice for a canonical program."""

    program_id: ProgramId
    role: ShortlistRole
    state: ShortlistEntryState = ShortlistEntryState.ACTIVE
    origin: DecisionSourceKind = DecisionSourceKind.USER
    revision: int = Field(default=1, strict=True, ge=1)
    created_at: datetime
    updated_at: datetime
    removed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        for timestamp in (self.created_at, self.updated_at, self.removed_at):
            if timestamp is not None and not _is_aware(timestamp):
                raise ValueError("shortlist timestamps must be timezone-aware")
        if self.created_at > self.updated_at:
            raise ValueError("shortlist entry created_at cannot be after updated_at")
        if self.state is ShortlistEntryState.ACTIVE and self.removed_at is not None:
            raise ValueError("active shortlist entry cannot have removed_at")
        if self.state is ShortlistEntryState.REMOVED and self.removed_at is None:
            raise ValueError("removed shortlist entry must have removed_at")
        if self.removed_at is not None and self.removed_at < self.updated_at:
            raise ValueError("removed_at cannot be before updated_at")
        return self


class DecisionChoice(ContractModel):
    """Ordered explicit choice state; derived candidate refresh never edits it."""

    considered_program_ids: tuple[ProgramId, ...] = Field(default=(), max_length=50)
    shortlist_entries: tuple[ShortlistEntry, ...] = Field(default=(), max_length=20)
    excluded_program_ids: tuple[ProgramId, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def validate_identity_and_state(self) -> Self:
        if len(self.considered_program_ids) != len(set(self.considered_program_ids)):
            raise ValueError("considered programs must be unique")
        if len(self.excluded_program_ids) != len(set(self.excluded_program_ids)):
            raise ValueError("excluded programs must be unique")
        entry_ids = tuple(entry.program_id for entry in self.shortlist_entries)
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("shortlist entries must have unique program ids")
        excluded = set(self.excluded_program_ids)
        active_ids = {entry.program_id for entry in self.shortlist_entries if entry.state is ShortlistEntryState.ACTIVE}
        if excluded.intersection(active_ids):
            raise ValueError("excluded programs cannot remain active in shortlist")
        return self

    @property
    def active_shortlist(self) -> tuple[ShortlistEntry, ...]:
        return tuple(entry for entry in self.shortlist_entries if entry.state is ShortlistEntryState.ACTIVE)

    @property
    def removed_shortlist(self) -> tuple[ShortlistEntry, ...]:
        return tuple(entry for entry in self.shortlist_entries if entry.state is ShortlistEntryState.REMOVED)

    def consider(self, program_id: ProgramId) -> DecisionChoice:
        """Add a considered program id idempotently without saving a shortlist entry."""

        logger.debug("decision_choice_consider_start considered_count=%d", len(self.considered_program_ids))
        if program_id in self.considered_program_ids:
            return self
        if len(self.considered_program_ids) >= 50:
            raise ValueError("considered program limit exceeded")
        result = self.__class__(
            considered_program_ids=(*self.considered_program_ids, program_id),
            shortlist_entries=self.shortlist_entries,
            excluded_program_ids=self.excluded_program_ids,
        )
        logger.info("decision_choice_consider_complete considered_count=%d", len(result.considered_program_ids))
        return result

    def add_shortlist(
        self,
        program_id: ProgramId,
        *,
        role: ShortlistRole,
        origin: DecisionSourceKind,
        now: datetime,
    ) -> DecisionChoice:
        """Add or restore a program through an explicit user command."""

        _ensure_aware(now)
        logger.debug(
            "decision_choice_add_start active_count=%d retained_count=%d",
            len(self.active_shortlist),
            len(self.shortlist_entries),
        )
        if program_id in self.excluded_program_ids:
            raise ValueError("excluded program must be restored before adding to shortlist")
        existing = next((entry for entry in self.shortlist_entries if entry.program_id == program_id), None)
        if existing is not None:
            if existing.state is ShortlistEntryState.ACTIVE and existing.role is role:
                return self
            if existing.state is ShortlistEntryState.ACTIVE:
                return self.set_role(program_id, role=role, now=now)
            restored = ShortlistEntry(
                program_id=program_id,
                role=role,
                state=ShortlistEntryState.ACTIVE,
                origin=origin,
                revision=existing.revision + 1,
                created_at=existing.created_at,
                updated_at=now,
            )
            return self._replace_entry(restored)
        if len(self.shortlist_entries) >= 20:
            raise ValueError("retained shortlist limit exceeded")
        entry = ShortlistEntry(
            program_id=program_id,
            role=role,
            origin=origin,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        result = self._replace_entry(entry)
        logger.info("decision_choice_add_complete active_count=%d retained_count=%d", len(result.active_shortlist), len(result.shortlist_entries))
        return result

    def remove_shortlist(self, program_id: ProgramId, *, now: datetime) -> DecisionChoice:
        """Mark an entry removed while retaining it for an explicit restore."""

        _ensure_aware(now)
        entry = self._entry(program_id)
        if entry.state is ShortlistEntryState.REMOVED:
            return self
        removed = ShortlistEntry(
            program_id=entry.program_id,
            role=entry.role,
            state=ShortlistEntryState.REMOVED,
            origin=entry.origin,
            revision=entry.revision + 1,
            created_at=entry.created_at,
            updated_at=now,
            removed_at=now,
        )
        result = self._replace_entry(removed)
        logger.info("decision_choice_remove_complete active_count=%d retained_count=%d", len(result.active_shortlist), len(result.shortlist_entries))
        return result

    def restore_shortlist(self, program_id: ProgramId, *, now: datetime) -> DecisionChoice:
        """Restore only a known removed entry; never invent a new program."""

        _ensure_aware(now)
        entry = self._entry(program_id)
        if entry.state is ShortlistEntryState.ACTIVE:
            return self
        restored = ShortlistEntry(
            program_id=entry.program_id,
            role=entry.role,
            state=ShortlistEntryState.ACTIVE,
            origin=entry.origin,
            revision=entry.revision + 1,
            created_at=entry.created_at,
            updated_at=now,
        )
        return self._replace_entry(restored)

    def set_role(self, program_id: ProgramId, *, role: ShortlistRole, now: datetime) -> DecisionChoice:
        """Change an active role explicitly, preserving program identity/order."""

        _ensure_aware(now)
        entry = self._entry(program_id)
        if entry.state is ShortlistEntryState.REMOVED:
            raise ValueError("removed shortlist entry must be restored before changing role")
        if entry.role is role:
            return self
        changed = ShortlistEntry(
            program_id=entry.program_id,
            role=role,
            state=entry.state,
            origin=entry.origin,
            revision=entry.revision + 1,
            created_at=entry.created_at,
            updated_at=now,
        )
        return self._replace_entry(changed)

    def exclude(self, program_id: ProgramId) -> DecisionChoice:
        """Record an explicit exclusion; active shortlist entries must be removed first."""

        if any(entry.program_id == program_id and entry.state is ShortlistEntryState.ACTIVE for entry in self.shortlist_entries):
            raise ValueError("active shortlist program must be removed before exclusion")
        if program_id in self.excluded_program_ids:
            return self
        if len(self.excluded_program_ids) >= 50:
            raise ValueError("excluded program limit exceeded")
        return self.__class__(
            considered_program_ids=self.considered_program_ids,
            shortlist_entries=self.shortlist_entries,
            excluded_program_ids=(*self.excluded_program_ids, program_id),
        )

    def restore_excluded(self, program_id: ProgramId) -> DecisionChoice:
        """Remove an explicit exclusion without adding the program to shortlist."""

        if program_id not in self.excluded_program_ids:
            return self
        return self.__class__(
            considered_program_ids=self.considered_program_ids,
            shortlist_entries=self.shortlist_entries,
            excluded_program_ids=tuple(item for item in self.excluded_program_ids if item != program_id),
        )

    def _entry(self, program_id: ProgramId) -> ShortlistEntry:
        entry = next((item for item in self.shortlist_entries if item.program_id == program_id), None)
        if entry is None:
            raise ValueError("shortlist program was not found")
        return entry

    def _replace_entry(self, replacement: ShortlistEntry) -> DecisionChoice:
        entries = tuple(
            replacement if entry.program_id == replacement.program_id else entry for entry in self.shortlist_entries
        )
        if not any(entry.program_id == replacement.program_id for entry in self.shortlist_entries):
            entries = (*entries, replacement)
        return self.__class__(
            considered_program_ids=self.considered_program_ids,
            shortlist_entries=entries,
            excluded_program_ids=self.excluded_program_ids,
        )


class DecisionState(ContractModel):
    """Only decision-owned state persisted by the decision repository."""

    version: Literal[1] = 1
    admission_constraints: AdmissionConstraints | None = None
    choice: DecisionChoice = Field(default_factory=DecisionChoice)
    selected_program_id: ProgramId | None = None
    selected_at: datetime | None = None
    explicit_priorities: tuple[ShortText, ...] = Field(default=(), max_length=12)
    revision: int = Field(default=1, strict=True, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if not _is_aware(self.created_at) or not _is_aware(self.updated_at):
            raise ValueError("decision state timestamps must be timezone-aware")
        if self.created_at > self.updated_at:
            raise ValueError("decision state created_at cannot be after updated_at")
        if len(self.explicit_priorities) != len(set(self.explicit_priorities)):
            raise ValueError("explicit priorities must be unique")
        if self.selected_at is not None and not _is_aware(self.selected_at):
            raise ValueError("selected_at must be timezone-aware")
        if self.selected_program_id is None and self.selected_at is not None:
            raise ValueError("selected_at requires selected_program_id")
        if self.selected_program_id is not None:
            selected = next((entry for entry in self.choice.active_shortlist if entry.program_id == self.selected_program_id), None)
            if selected is None:
                raise ValueError("final program must be an active shortlist entry")
        return self

    @property
    def status(self) -> DecisionStatus:
        if self.admission_constraints is None and not self.choice.considered_program_ids and not self.choice.shortlist_entries and not self.explicit_priorities:
            return DecisionStatus.EMPTY
        if self.selected_program_id is not None:
            return DecisionStatus.FINALIZED
        if self.choice.active_shortlist:
            return DecisionStatus.READY
        return DecisionStatus.IN_PROGRESS

    def with_choice(self, choice: DecisionChoice, *, now: datetime) -> DecisionState:
        _ensure_aware(now)
        return self.__class__(
            version=self.version,
            admission_constraints=self.admission_constraints,
            choice=choice,
            selected_program_id=self.selected_program_id,
            selected_at=self.selected_at,
            explicit_priorities=self.explicit_priorities,
            revision=self.revision + 1,
            created_at=self.created_at,
            updated_at=now,
        )

    def with_constraints(self, constraints: AdmissionConstraints | None, *, now: datetime) -> DecisionState:
        _ensure_aware(now)
        return self.__class__(
            version=self.version,
            admission_constraints=constraints,
            choice=self.choice,
            selected_program_id=self.selected_program_id,
            selected_at=self.selected_at,
            explicit_priorities=self.explicit_priorities,
            revision=self.revision + 1,
            created_at=self.created_at,
            updated_at=now,
        )

    def select_final_choice(self, program_id: ProgramId, *, now: datetime) -> DecisionState:
        _ensure_aware(now)
        if not any(entry.program_id == program_id and entry.state is ShortlistEntryState.ACTIVE for entry in self.choice.shortlist_entries):
            raise ValueError("final program must be an active shortlist entry")
        if self.selected_program_id == program_id:
            return self
        return self.__class__(
            version=self.version,
            admission_constraints=self.admission_constraints,
            choice=self.choice,
            selected_program_id=program_id,
            selected_at=now,
            explicit_priorities=self.explicit_priorities,
            revision=self.revision + 1,
            created_at=self.created_at,
            updated_at=now,
        )

    def reopen_final_choice(self, *, now: datetime) -> DecisionState:
        _ensure_aware(now)
        if self.selected_program_id is None:
            return self
        return self.__class__(
            version=self.version,
            admission_constraints=self.admission_constraints,
            choice=self.choice,
            selected_program_id=None,
            selected_at=None,
            explicit_priorities=self.explicit_priorities,
            revision=self.revision + 1,
            created_at=self.created_at,
            updated_at=now,
        )


class DecisionContextMetadata(ContractModel):
    """Safe context metadata exposed to UI/application consumers."""

    decision_id: DecisionId
    revision: int = Field(strict=True, ge=1)
    status: DecisionStatus
    created_at: datetime
    updated_at: datetime
    profile_revision: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if not _is_aware(self.created_at) or not _is_aware(self.updated_at):
            raise ValueError("decision metadata timestamps must be timezone-aware")
        if self.created_at > self.updated_at:
            raise ValueError("decision metadata created_at cannot be after updated_at")
        return self


class DecisionContext(ContractModel):
    """Hydrated explicit state plus a read-only preference projection."""

    decision_id: DecisionId
    state: DecisionState
    preferences: UserProfile | None = None
    profile_revision: int | None = Field(default=None, strict=True, ge=1)
    missing_data: tuple[ShortText, ...] = Field(default=(), max_length=32)
    metadata: DecisionContextMetadata

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.metadata.decision_id != self.decision_id:
            raise ValueError("decision metadata id must match context id")
        if self.metadata.revision != self.state.revision:
            raise ValueError("decision metadata revision must match state revision")
        if self.metadata.profile_revision != self.profile_revision:
            raise ValueError("decision metadata profile revision must match context")
        if len(self.missing_data) != len(set(self.missing_data)):
            raise ValueError("decision missing_data must be unique")
        return self


class DecisionSnapshot(ContractModel):
    """Repository envelope; owner_key is never part of public API responses."""

    decision_id: DecisionId
    owner_key: NonEmptyText
    state: DecisionState
    revision: int = Field(strict=True, ge=1)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.revision != self.state.revision:
            raise ValueError("snapshot revision must match decision state revision")
        timestamp_fields = (self.created_at, self.updated_at, self.expires_at)
        if not all(_is_aware(value) for value in timestamp_fields):
            raise ValueError("decision snapshot timestamps must be timezone-aware")
        if self.created_at > self.updated_at:
            raise ValueError("decision snapshot created_at cannot be after updated_at")
        if self.updated_at >= self.expires_at:
            raise ValueError("decision snapshot expires_at must be after updated_at")
        return self


__all__ = [
    "AdmissionConstraints",
    "DecisionChoice",
    "DecisionContext",
    "DecisionContextMetadata",
    "DecisionSnapshot",
    "DecisionState",
    "ShortlistEntry",
]
