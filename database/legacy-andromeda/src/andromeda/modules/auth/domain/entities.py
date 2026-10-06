from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import AccountId


EmailAddress = Annotated[str, StringConstraints(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class Account(ContractModel):
    """Public account identity; credentials and session data stay private."""

    account_id: AccountId = Field(alias="accountId")
    email: EmailAddress
    created_at: datetime = Field(alias="createdAt")

    @model_validator(mode="after")
    def validate_created_at(self) -> Account:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("account created_at must be timezone-aware")
        if self.created_at.astimezone(timezone.utc) > datetime.now(timezone.utc):
            raise ValueError("account created_at cannot be in the future")
        return self


class AuthSessionResult(ContractModel):
    authenticated: bool
    account: Account | None = None


__all__ = ["Account", "AuthSessionResult", "EmailAddress"]
