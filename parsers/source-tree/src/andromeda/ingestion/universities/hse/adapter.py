from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import logging
import re
from pathlib import Path

from andromeda.ingestion.contracts.constraints import http_url
from andromeda.ingestion.contracts.normalized import CanonicalSnapshot
from andromeda.ingestion.contracts.raw import RawAdmissionPassingScore, RawAdmissionRecord, RawCurriculumRow, RawDirectionRecord, RawParserDiagnostic, RawProgramRecord, RawSourceGap, RawSourceSnapshot, RawTracerBundle, RawUniversityRecord, SourceLocator
from andromeda.ingestion.contracts.source import CapturedSources
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.disciplines.services.classifier import RuleBasedDisciplineClassifier
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.errors import ContractError, ErrorCode
from andromeda.shared.contracts.provenance import SourceAttribution

from .capture import DEFAULT_FIXTURE_DIR, HseSource
from .identity import canonicalize_program_records, direction_codes, normalize_name
from .mappings.discipline_areas import HSE_DISCIPLINE_AREA_OVERRIDES
from .normalizers.admissions import normalize_admissions
from .normalizers.canonical import normalize_bundle
from .parser.admissions import FactObservation, parse_enrollment_document, parse_historical_passing, parse_minimum_exams, parse_places, parse_tuition
from .parser.catalog import canonical_url, parse_program_detail, study_plan_urls
from .parser.curriculum import CurriculumObservation, parse_work_plan


fetch_logger = logging.getLogger("andromeda.ingestion.hse.fetch")
parse_logger = logging.getLogger("andromeda.ingestion.hse.parse")
normalize_logger = logging.getLogger("andromeda.ingestion.hse.normalize")


class HseUniversityAdapter:
    """Typed HSE boundary: official capture, deterministic parsing and canonical projection."""

    def __init__(self, fetcher: object | None = None) -> None:
        self._source = HseSource(fetcher=fetcher)  # type: ignore[arg-type]
        self._classifier = RuleBasedDisciplineClassifier(HSE_DISCIPLINE_AREA_OVERRIDES)

    def close(self) -> None:
        self._source.close()

    def capture(self, mode: str = "fixture", fixture_dir: Path | None = None) -> CapturedSources:
        fetch_logger.debug("stage=capture university=hse mode=%s", mode)
        return self._source.capture(mode=mode, fixture_dir=fixture_dir or DEFAULT_FIXTURE_DIR)

    def parse(self, captured: CapturedSources, program_codes: Sequence[str] | None = None) -> tuple[RawTracerBundle, CanonicalSnapshot]:
        detail_snapshots = captured.by_kind("hse_program_detail")
        if not detail_snapshots:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "HSE catalog has no program detail snapshots")
        raw_university = _parse_university(captured.first("hse_common"))
        work_plan_observations = _work_plan_observations(captured)
        direction_by_name = _catalog_direction_map(captured, work_plan_observations)
        raw_programs: list[RawProgramRecord] = []
        raw_directions: list[RawDirectionRecord] = []
        gaps: list[RawSourceGap] = list(captured.source_gaps)
        for snapshot in detail_snapshots:
            try:
                page = parse_program_detail(snapshot)
            except ValueError as exc:
                gaps.append(_gap("detail", str(snapshot.requested_url), "program_detail_parse_failed", snapshot))
                parse_logger.warning("[FIX:source-gap] %s", exc)
                continue
            direction_code = page.direction_code or direction_by_name.get(normalize_name(page.name))
            if not direction_code:
                gaps.append(_gap("program", str(snapshot.requested_url), "program-detail-does-not-publish-code-and-no-official-admission-or-plan-mapping", snapshot))
                parse_logger.warning("[FIX:source-gap] hse_program_code_missing url=%s name=%s", snapshot.requested_url, page.name)
                continue
            if page.education_year is None:
                gaps.append(_gap("program", str(snapshot.requested_url), "program-education-year-missing-from-official-source", snapshot))
                parse_logger.warning("[FIX:source-gap] hse_program_education_year_missing url=%s", snapshot.requested_url)
                continue
            locator = SourceLocator(source_url=snapshot.requested_url)
            education_level = "специалитет" if ".05." in direction_code or page.education_level == "специалитет" else "бакалавриат"
            raw_directions.append(RawDirectionRecord(code=direction_code, name=page.direction_name or page.name, education_level=education_level, locator=locator))
            program_root = page.url.rstrip("/")
            if program_root.endswith("/admission"):
                program_root = program_root[: -len("/admission")]
            raw_programs.append(RawProgramRecord(code="pending", name=page.name, direction_code=direction_code, education_level=education_level, education_year=page.education_year, study_plan_url=http_url(program_root + "/learn_plans/"), source_url=http_url(page.url), locator=locator, source_code=program_root))
        if not raw_programs:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "HSE details contain no parseable programs")
        raw_programs = list(canonicalize_program_records(raw_programs))
        if program_codes is not None:
            requested = set(program_codes)
            available = {program.code for program in raw_programs}
            unknown = requested - available
            if unknown:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"HSE selected programs are not in the discovered catalog: {sorted(unknown)}")
            raw_programs = [program for program in raw_programs if program.code in requested]
        raw_directions = list(_dedupe_directions(raw_directions))
        if not raw_directions:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "HSE details contain no valid directions")
        curriculum_plan_programs = _curriculum_plan_programs(captured, raw_programs)
        rows = list(_parse_curricula(captured, raw_programs, gaps, work_plan_observations, curriculum_plan_programs))
        for program in raw_programs:
            if not any(row.program_code == program.code for row in rows):
                gaps.append(_gap("program", program.code, "published study plans contain no parseable work-plan rows", _source_for_program(captured, program)))
        admissions = list(_parse_admissions(captured, raw_programs, gaps))
        raw = RawTracerBundle(
            snapshots=captured.snapshots,
            university=raw_university,
            direction=raw_directions[0],
            directions=tuple(raw_directions),
            programs=tuple(raw_programs),
            curriculum_rows=tuple(rows),
            admissions=tuple(admissions),
            source_gaps=tuple(_dedupe_gaps(gaps)),
            diagnostics=tuple(_diagnostics_from_gaps(_dedupe_gaps(gaps))),
        )
        parse_logger.info("stage=raw_complete university=hse directions=%d programs=%d curriculum_rows=%d admissions=%d gaps=%d", len(raw.directions), len(raw.programs), len(raw.curriculum_rows), len(raw.admissions), len(raw.source_gaps))
        canonical = normalize_bundle(raw)
        classified = tuple(Discipline.model_validate({**discipline.model_dump(), "area_weights": self._classifier.classify(discipline.name)}) for discipline in canonical.disciplines)
        classification_outcomes = tuple(
            self._classifier.classify_with_outcome(discipline.name, discipline_id=discipline.id)
            for discipline in canonical.disciplines
        )
        canonical = canonical.model_copy(update={"disciplines": classified, "classification_outcomes": classification_outcomes, "admissions": normalize_admissions(raw.admissions, programs=canonical.programs, snapshots=raw.snapshots)})
        area_count = len({weight.area for discipline in classified for weight in discipline.area_weights})
        normalize_logger.info("stage=canonical_complete university=hse programs=%d disciplines=%d curricula=%d areas=%d", len(canonical.programs), len(canonical.disciplines), len(canonical.curricula), area_count)
        return raw, canonical

    def parse_sources(self, mode: str = "fixture", fixture_dir: Path | None = None, program_codes: Sequence[str] | None = None) -> tuple[RawTracerBundle, CanonicalSnapshot]:
        return self.parse(self.capture(mode=mode, fixture_dir=fixture_dir), program_codes=program_codes)


def _parse_university(snapshot: object) -> RawUniversityRecord:
    typed = snapshot
    from andromeda.ingestion.contracts.raw import RawSourceSnapshot

    if not isinstance(typed, RawSourceSnapshot):
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Invalid HSE common snapshot")
    text = typed.body.decode("utf-8", errors="ignore")
    visible = re.sub(r"<[^>]+>", " ", text)
    address_match = re.search(r"(?:Главный корпус|Адрес)[^\n]{0,120}(\d{6},?\s*г\.?\s*Москва,?[^<\n]+)", visible, re.IGNORECASE)
    address = address_match.group(1).strip() if address_match else ""
    if not address:
        address_match = re.search(r"(109028,\s*г\.\s*Москва,\s*Покровский бульвар,\s*д\.\s*11)", visible, re.IGNORECASE)
        address = address_match.group(1) if address_match else ""
    if not address:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "HSE official contacts page contains no main address")
    return RawUniversityRecord(name="Национальный исследовательский университет «Высшая школа экономики»", city="Москва", address=address, official_site=http_url("https://www.hse.ru/"), locator=SourceLocator(source_url=typed.requested_url))


def _parse_curricula(
    captured: CapturedSources,
    programs: Sequence[RawProgramRecord],
    gaps: list[RawSourceGap],
    observations_by_url: dict[str, tuple[CurriculumObservation, ...]],
    curriculum_plan_programs: Mapping[str, tuple[RawProgramRecord, ...]],
) -> tuple[RawCurriculumRow, ...]:
    result: list[RawCurriculumRow] = []
    for snapshot in captured.by_kind("hse_curriculum_document"):
        if "workplan" not in str(snapshot.requested_url).casefold() and "work_plan" not in str(snapshot.requested_url).casefold():
            continue
        observations = observations_by_url.get(str(snapshot.requested_url), ())
        if not observations:
            gaps.append(_gap("curriculum", str(snapshot.requested_url), "work-plan-document-produced-no-rows", snapshot))
            continue
        for observation in observations:
            mapped_programs = curriculum_plan_programs.get(_source_key(snapshot.requested_url), ())
            if observation.direction_code and mapped_programs:
                compatible = tuple(
                    program
                    for program in mapped_programs
                    if observation.direction_code in direction_codes(program.direction_code)
                )
                mapped_programs = compatible
            if mapped_programs:
                target_programs = mapped_programs
            else:
                matched = _match_raw_program(observation.direction_code, observation.program_name, programs)
                target_programs = (matched,) if matched is not None else ()
            if not target_programs:
                gaps.append(_gap("curriculum", str(snapshot.requested_url), "work-plan-program-identity-ambiguous", snapshot))
                continue
            for program in target_programs:
                result.append(RawCurriculumRow(program_code=program.code, discipline=observation.discipline, semester=None, hours=observation.hours, credits=observation.credits, assessment=None, source_position=observation.source_position, source_url=snapshot.requested_url, locator=SourceLocator(source_url=snapshot.requested_url, row=observation.source_position), source_program_code=program.source_code or program.code))
    return tuple(result)


def _work_plan_observations(captured: CapturedSources) -> dict[str, tuple[CurriculumObservation, ...]]:
    result: dict[str, tuple[CurriculumObservation, ...]] = {}
    for snapshot in captured.by_kind("hse_curriculum_document"):
        if "workplan" not in str(snapshot.requested_url).casefold() and "work_plan" not in str(snapshot.requested_url).casefold():
            continue
        result[str(snapshot.requested_url)] = parse_work_plan(snapshot)
    return result


def _catalog_direction_map(captured: CapturedSources, work_plan_observations: dict[str, tuple[CurriculumObservation, ...]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for snapshot in captured.by_kind("hse_admission_rules"):
        for exam_observation in parse_minimum_exams(snapshot):
            if exam_observation.direction_code:
                for alias in _program_aliases(exam_observation.program_name):
                    result.setdefault(alias, exam_observation.direction_code)
    for observations in work_plan_observations.values():
        for curriculum_observation in observations:
            if curriculum_observation.direction_code and curriculum_observation.program_name:
                for alias in _program_aliases(curriculum_observation.program_name):
                    result.setdefault(alias, curriculum_observation.direction_code)
    return result


def _program_aliases(value: str) -> tuple[str, ...]:
    normalized = normalize_name(value)
    aliases = [normalized]
    quoted = re.findall(r"[\"«](.*?)[\"»]", value)
    aliases.extend(normalize_name(item) for item in quoted if item.strip())
    stripped = re.sub(r"^образовательная программа\s*", "", normalized)
    stripped = re.sub(r"\s+проректор$", "", stripped)
    if stripped:
        aliases.append(stripped)
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def _parse_admissions(captured: CapturedSources, programs: Sequence[RawProgramRecord], gaps: list[RawSourceGap]) -> tuple[RawAdmissionRecord, ...]:
    facts: list[tuple[str, FactObservation, RawSourceSnapshot]] = []
    minimum_year = max(program.education_year for program in programs)
    for snapshot in captured.by_kind("hse_admission_rules"):
        for exam_observation in parse_minimum_exams(snapshot):
            facts.append((str(snapshot.requested_url), FactObservation(exam_observation.direction_code, exam_observation.program_name, minimum_year, "full_time", "budget", None, exam_observation.exams, (), (), (), "hse_admission_rules", exam_observation.row), snapshot))
    for snapshot in captured.by_kind("hse_admission_places"):
        for places_observation in parse_places(snapshot, minimum_year):
            facts.append((str(snapshot.requested_url), places_observation, snapshot))
    for snapshot in captured.by_kind("hse_tuition"):
        for tuition_observation in parse_tuition(snapshot, minimum_year):
            facts.append((str(snapshot.requested_url), tuition_observation, snapshot))
    for snapshot in captured.by_kind("hse_passing_scores"):
        historical_match = re.search(r"result(20\d{2})", str(snapshot.requested_url), re.IGNORECASE)
        historical_year = int(historical_match.group(1)) if historical_match else minimum_year
        for passing_observation in parse_historical_passing(snapshot, historical_year):
            facts.append((str(snapshot.requested_url), passing_observation, snapshot))
    records: list[RawAdmissionRecord] = []
    for source_url, fact, snapshot in facts:
        program = _match_raw_program(fact.direction_code, fact.program_name, programs)
        if program is None:
            gaps.append(_gap("admission", source_url, "admission-program-identity-ambiguous", snapshot))
            continue
        records.append(_record_from_fact(program, source_url, fact, snapshot))
    for enrollment_snapshot in captured.by_kind("hse_enrollment_document"):
        for enrollment_observation in parse_enrollment_document(enrollment_snapshot):
            program = _match_raw_program(enrollment_observation.direction_code, enrollment_observation.program_name, programs)
            if program is None:
                gaps.append(_gap("enrollment", str(enrollment_snapshot.requested_url), "enrollment-program-identity-ambiguous", enrollment_snapshot))
                continue
            score = RawAdmissionPassingScore(score_type="budget", competition_type=enrollment_observation.competition_type, status=enrollment_observation.status, score=enrollment_observation.score)
            records.append(RawAdmissionRecord(id=_stable_id("enrollment", str(enrollment_snapshot.requested_url), program.code, str(enrollment_observation.row), enrollment_observation.competition_type), program_code=program.code, program_name=program.name, admission_year=enrollment_observation.admission_year, study_form=enrollment_observation.study_form, funding_type=enrollment_observation.funding_type, scope="program", passing_scores=(score,), source_kind="hse_enrollment_document", source_url=enrollment_snapshot.requested_url, locator=SourceLocator(source_url=enrollment_snapshot.requested_url, row=enrollment_observation.row), source_program_code=program.source_code or program.code))
    return tuple(records)


def _record_from_fact(program: RawProgramRecord, source_url: str, fact: FactObservation, snapshot: RawSourceSnapshot) -> RawAdmissionRecord:
    return RawAdmissionRecord(id=_stable_id(fact.source_kind, source_url, program.code, str(fact.row), fact.funding_type or "unknown"), program_code=program.code, program_name=program.name, admission_year=fact.admission_year, study_form=fact.study_form, funding_type=fact.funding_type, scope="program", places=fact.places, exams=fact.exams, quotas=fact.quotas, passing_scores=fact.passing_scores, tuition=fact.tuition, source_kind=fact.source_kind, source_url=http_url(source_url), locator=SourceLocator(source_url=http_url(source_url), row=fact.row), source_program_code=program.source_code or program.code)


def _match_raw_program(direction: str | None, name: str | None, programs: Sequence[RawProgramRecord]) -> RawProgramRecord | None:
    candidates = tuple(program for program in programs if not direction or direction in direction_codes(program.direction_code))
    if not name:
        return candidates[0] if len(candidates) == 1 else None
    target = _program_name_variants(name)
    exact = tuple(program for program in candidates if target.intersection(_program_name_variants(program.name)))
    if len(exact) == 1:
        return exact[0]
    contained = tuple(
        program
        for program in candidates
        if any(
            left in right or right in left
            for left in target
            for right in _program_name_variants(program.name)
            if len(left) >= 8 and len(right) >= 8
        )
    )
    return contained[0] if len(contained) == 1 else (candidates[0] if len(candidates) == 1 else None)


def _program_name_variants(value: str) -> set[str]:
    normalized = normalize_name(value)
    variants = {normalized}
    for prefix in ("бакалаврская программа ", "образовательная программа ", "образовательная программа"):
        if normalized.startswith(prefix):
            variants.add(normalized[len(prefix) :].strip(" -—–:«»\""))
    for quoted in re.findall(r"[«\"]([^»\"]+)[»\"]", value):
        variants.add(normalize_name(quoted))
    variants = {
        re.sub(r"\s+(?:проректор|профиль|профиля)$", "", item).strip()
        for item in variants
        if item
    }
    return variants


def _source_for_program(captured: CapturedSources, program: RawProgramRecord) -> RawSourceSnapshot:
    for snapshot in captured.by_kind("hse_curriculum_index"):
        if str(program.study_plan_url) == str(snapshot.requested_url):
            return snapshot
    for snapshot in captured.by_kind("hse_program_detail"):
        if str(program.source_url) == str(snapshot.requested_url):
            return snapshot
    return captured.snapshots[0]


def _gap(entity_type: str, entity_key: str, reason: str, snapshot: object) -> RawSourceGap:
    from andromeda.ingestion.contracts.raw import RawSourceSnapshot

    typed = snapshot if isinstance(snapshot, RawSourceSnapshot) else None
    source_url = typed.requested_url if typed is not None else http_url(entity_key if entity_key.startswith("http") else "https://www.hse.ru/")
    locator = SourceLocator(source_url=source_url)
    key = f"{entity_type}|{entity_key}|{reason}|{source_url}"
    return RawSourceGap(id=f"source-gap:{sha256(key.encode('utf-8')).hexdigest()[:24]}", entity_type=entity_type, entity_key=entity_key[:256] or "unknown", reason=reason, source_url=source_url, locator=locator)


def _dedupe_directions(values: Sequence[RawDirectionRecord]) -> tuple[RawDirectionRecord, ...]:
    result: list[RawDirectionRecord] = []
    seen: set[str] = set()
    for value in values:
        for code in direction_codes(value.code):
            if code in seen:
                continue
            seen.add(code)
            result.append(value.model_copy(update={"code": code}))
    return tuple(sorted(result, key=lambda item: item.code))


def _dedupe_gaps(values: Sequence[RawSourceGap]) -> tuple[RawSourceGap, ...]:
    result: list[RawSourceGap] = []
    seen: set[str] = set()
    for value in values:
        if value.id not in seen:
            seen.add(value.id)
            result.append(value)
    return tuple(result)


def _curriculum_plan_programs(
    captured: CapturedSources,
    programs: Sequence[RawProgramRecord],
) -> dict[str, tuple[RawProgramRecord, ...]]:
    """Recover the official index-to-plan relationship lost by flat capture.

    HSE exposes several historical work plans for one programme and reuses
    direction codes across programmes. The ``learn_plans`` index is the
    adapter-owned source of truth for associating a plan with its programme.
    A plan linked by more than one programme is intentionally left unmapped;
    the parser's identity resolver then remains fail-closed for that case.
    """

    programs_by_root: dict[str, tuple[RawProgramRecord, ...]] = {}
    grouped_programs: dict[str, list[RawProgramRecord]] = {}
    for program in programs:
        grouped_programs.setdefault(_program_root_url(str(program.source_url)), []).append(program)
    programs_by_root = {root: tuple(values) for root, values in grouped_programs.items()}

    owners_by_plan: dict[str, set[str]] = {}
    for index_snapshot in captured.by_kind("hse_curriculum_index"):
        owner_root = _program_root_url(str(index_snapshot.requested_url))
        if len(programs_by_root.get(owner_root, ())) != 1:
            continue
        for plan_url in study_plan_urls(index_snapshot.body, str(index_snapshot.final_url)):
            owners_by_plan.setdefault(_source_key(plan_url), set()).add(owner_root)

    result: dict[str, tuple[RawProgramRecord, ...]] = {}
    for plan_snapshot in captured.by_kind("hse_curriculum_document"):
        roots = owners_by_plan.get(_source_key(plan_snapshot.requested_url), set())
        program_values = tuple(
            program
            for root in sorted(roots)
            for program in programs_by_root.get(root, ())
        )
        if program_values:
            result[_source_key(plan_snapshot.requested_url)] = program_values
    return result


def _program_root_url(value: str) -> str:
    result = canonical_url(value)
    for suffix in ("/admission/", "/learn_plans/"):
        if result.endswith(suffix):
            return result[: -len(suffix)] + "/"
    return result


def _source_key(value: object) -> str:
    return canonical_url(str(value))


def _diagnostics_from_gaps(gaps: Sequence[RawSourceGap]) -> tuple[RawParserDiagnostic, ...]:
    return tuple(
        RawParserDiagnostic(
            code=gap.reason[:128],
            stage="capture" if gap.entity_type == "source" else "parse",
            message=gap.reason[:512],
            severity="ambiguous" if "ambig" in gap.reason.casefold() else "warning",
            source_url=gap.source_url,
        )
        for gap in gaps
    )


def _stable_id(*parts: str) -> str:
    return "hse-admission:" + sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


__all__ = ["HseUniversityAdapter"]
