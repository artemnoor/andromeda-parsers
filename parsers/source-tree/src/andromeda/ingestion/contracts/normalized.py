from __future__ import annotations

from pydantic import Field

from ...modules.curricula.contracts.public import Curriculum
from ...modules.disciplines.contracts.public import Discipline
from ...modules.disciplines.contracts.classification import ClassificationOutcome
from ...modules.programs.contracts.public import Program
from ...modules.admissions.contracts.public import ProgramAdmissions
from ...modules.events.contracts.public import Event
from ...modules.campus.contracts.public import CampusPoint
from ...modules.universities.contracts.public import Direction, University
from ...shared.contracts.base import ContractModel
from ...shared.contracts.provenance import SourceAttribution
from .raw import RawSourceGap


class CanonicalSnapshot(ContractModel):
    """Canonical graph emitted by an ingestion adapter."""

    university: University
    direction: Direction
    programs: tuple[Program, ...] = Field(min_length=1)
    disciplines: tuple[Discipline, ...] = Field(min_length=1)
    curricula: tuple[Curriculum, ...] = ()
    sources: tuple[SourceAttribution, ...] = Field(min_length=1)
    admissions: tuple[ProgramAdmissions, ...] = ()
    events: tuple[Event, ...] = ()
    campus_points: tuple[CampusPoint, ...] = ()
    directions: tuple[Direction, ...] = ()
    source_gaps: tuple[RawSourceGap, ...] = ()
    classification_outcomes: tuple[ClassificationOutcome, ...] = ()
