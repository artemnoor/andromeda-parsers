"""Persistence-facing value objects owned by the proftest module.

The profile itself remains a stable content contract.  Storage metadata lives
in a separate snapshot envelope so consumers cannot accidentally persist
answers, cookies, or infrastructure models as part of ``UserProfile``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Annotated, Self, TypeAlias

from pydantic import Field, StringConstraints, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import AccountId, SourceHash

from .entities import UserProfile


logger = logging.getLogger("andromeda.proftest.contracts.profile")

ProfileId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^profile:[0-9a-f]{32}$")]


def _is_aware(value: datetime) -> bool:
    """Return whether a datetime has an unambiguous UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


class ProfileScope(ContractModel):
    """Opaque owner reference passed from the HTTP adapter to application code.

    Only the one-way session hash and optional canonical account ID cross this
    boundary. Raw cookie tokens are intentionally not representable here.
    """

    session_key_hash: SourceHash
    account_id: AccountId | None = None

    @property
    def owner_key(self) -> str:
        """Return a stable storage key without exposing the raw cookie token."""

        if self.account_id is not None:
            return self.account_id
        return f"anonymous:{self.session_key_hash}"

    @property
    def owner_kind(self) -> str:
        return "account" if self.account_id is not None else "anonymous"


class ProfileRefinement(ContractModel):
    """A bounded preference signal produced by a current decision question.

    The decision module may select an option, but it does not own profile
    persistence or profile scoring.  Only the typed dimension is passed to the
    proftest owner; labels and source text never cross this boundary.
    """

    question_id: str = Field(min_length=1, max_length=128)
    option_id: str = Field(min_length=1, max_length=128)
    affected_dimension: str = Field(min_length=1, max_length=128)


class UserProfileSnapshot(ContractModel):
    """Current persisted profile plus storage metadata.

    Expiry is checked here against the current clock so an expired row cannot
    be exposed as a valid public snapshot.  Repository adapters must check the
    row before constructing this contract and may return ``None`` for expired
    records.
    """

    profile_id: ProfileId
    profile: UserProfile
    revision: int = Field(strict=True, ge=1)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_identity_and_timestamps(self) -> Self:
        logger.debug(
            "profile_snapshot_validate profile_id=%s revision=%d profile_axis_count=%d",
            self.profile_id,
            self.revision,
            len(self.profile.preferred_subject_weights) + len(self.profile.preferred_activity_weights),
        )
        timestamp_fields = (self.created_at, self.updated_at, self.expires_at)
        if not all(_is_aware(value) for value in timestamp_fields):
            logger.warning("profile_snapshot_rejected invariant=timezone_aware_timestamps")
            raise ValueError("profile snapshot timestamps must be timezone-aware")
        if self.created_at > self.updated_at:
            logger.warning("profile_snapshot_rejected invariant=created_before_updated")
            raise ValueError("profile snapshot created_at cannot be after updated_at")
        if self.updated_at >= self.expires_at:
            logger.warning("profile_snapshot_rejected invariant=expiry_after_updated")
            raise ValueError("profile snapshot expires_at must be after updated_at")
        if self.expires_at <= datetime.now(timezone.utc):
            logger.warning("profile_snapshot_rejected invariant=not_expired")
            raise ValueError("profile snapshot has expired")
        return self


__all__ = ["ProfileId", "ProfileRefinement", "ProfileScope", "UserProfileSnapshot"]
