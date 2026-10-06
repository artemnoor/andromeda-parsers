"""Identity helpers that do not depend on a source or storage implementation."""

from __future__ import annotations

from ..contracts.public import AdmissionOffering


def offering_identity(offering: AdmissionOffering) -> tuple[object, ...]:
    return (
        offering.program_id,
        offering.admission_year,
        offering.study_form,
        offering.funding_type,
        offering.scope,
    )


__all__ = ["offering_identity"]
