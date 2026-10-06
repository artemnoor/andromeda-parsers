"""Read-side ports used by the v1 query service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PageRows:
    items: list[dict[str, Any]]
    next_cursor: str | None
    total_count: int


class AcademicDataReadRepository(Protocol):
    """Stable-key read contract; implementations must scope every query to active data."""

    @property
    def active_release_key(self) -> str: ...

    @property
    def active_release_id(self) -> UUID: ...

    def active_release(self) -> dict[str, Any]: ...

    def get(self, table_name: str, external_key: str) -> dict[str, Any] | None: ...

    def get_by_id(self, table_name: str, record_id: UUID) -> dict[str, Any] | None: ...

    def page(
        self,
        table_name: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> PageRows: ...

    def related(
        self,
        table_name: str,
        foreign_key: str,
        parent_id: UUID,
        *,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def evidence_for(self, entity_table: str, entity_id: UUID) -> list[dict[str, Any]]: ...

    def manual_reviews_for(self, external_key: str) -> list[dict[str, Any]]: ...

    def subject_classifications_for(
        self,
        subject_type: str,
        subject_ids: list[UUID],
        taxonomy_key: str,
        taxonomy_version: str,
    ) -> dict[UUID, dict[str, Any]]: ...

    def subject_taxonomy(
        self, taxonomy_key: str, taxonomy_version: str
    ) -> dict[str, Any] | None: ...
