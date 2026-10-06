"""Offline validation for the already-normalized Andromeda source bundle."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import stat
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

logger = logging.getLogger("academic_data_service.bundle")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DRIVE_PATH_PATTERN = re.compile(r"^[A-Za-z]:")
UNRESOLVED_DETAIL_PATTERN = re.compile(
    r"(?P<field>[A-Za-z0-9_.\[\]]+) points to (?P<target>[^,]+),"
)
VALIDATOR_CONTRACT_VERSION = 1
REQUIRED_ROOT_FILES = (
    "README.md",
    "report.md",
    "validation_report.json",
    "manual_review.csv",
    "source_artifacts.jsonl",
)
DATASET_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "universities.jsonl": ("code", "name"),
    "directions.jsonl": ("code", "name", "university_key"),
    "departments.jsonl": ("code", "name", "university_key"),
    "educational_programs.jsonl": ("code", "name", "direction_key"),
    "study_plans.jsonl": ("status", "program_key"),
    "curriculum_items.jsonl": ("curriculum_key", "discipline"),
    "program_offerings.jsonl": ("campaign_key", "campaign_year", "direction_code"),
    "relationships.jsonl": ("relation_type", "source_key", "target_key"),
    "admission_exam_requirements.jsonl": ("campaign_key", "requirement_tree"),
}
ALLOWED_STORAGE_STATUSES = frozenset(
    {
        "saved",
        "unavailable",
        "failed",
        "not_captured",
        "omitted_by_user_request",
        "omitted_privacy_sensitive_applicant_records",
    }
)
PERSONAL_FIELD_NAMES = frozenset(
    {
        "applicantname",
        "applicantfullname",
        "firstname",
        "lastname",
        "surname",
        "birthdate",
        "dateofbirth",
        "snils",
        "passport",
        "passportnumber",
        "personalid",
        "applicantid",
        "email",
        "phone",
    }
)
SAFE_APPLICANT_FIELDS = frozenset({"applicant_category_text", "candidate_pii_filter"})


class BundleInputError(ValueError):
    """The supplied directory or archive cannot be read safely."""


@dataclass(frozen=True, slots=True)
class BundleFile:
    relative_path: str
    size_bytes: int
    sha256: str


class BundleReader:
    """Read bundle files without extracting ZIP entries or following inner links."""

    def __init__(self, input_path: str | Path) -> None:
        self.input_path = Path(input_path).expanduser()
        if not self.input_path.exists():
            raise BundleInputError("bundle input path does not exist")
        self.canonical_input_path = self.input_path.resolve(strict=True)
        self._directory: Path | None = None
        self._zip: zipfile.ZipFile | None = None
        self._directory_entries: dict[str, Path] = {}
        self._zip_entries: dict[str, zipfile.ZipInfo] = {}

        try:
            if self.canonical_input_path.is_dir():
                self._directory = self.canonical_input_path
                self._index_directory()
            elif (
                self.canonical_input_path.is_file()
                and self.canonical_input_path.suffix.lower() == ".zip"
            ):
                self._zip = zipfile.ZipFile(self.canonical_input_path)
                self._index_zip()
            else:
                raise BundleInputError("bundle input must be a directory or a .zip file")

            if not self._file_names():
                raise BundleInputError("bundle input contains no files")
            self.files = self._build_file_inventory()
            self._file_by_path = {item.relative_path: item for item in self.files}
            self.input_digest, self.digest_algorithm = self._compute_input_digest()
        except BundleInputError:
            self.close()
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            self.close()
            raise BundleInputError("bundle content is unreadable or corrupt") from error

    def __enter__(self) -> BundleReader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def _index_directory(self) -> None:
        assert self._directory is not None
        for current_root, directory_names, file_names in os.walk(self._directory):
            root = Path(current_root)
            for directory_name in list(directory_names):
                directory_path = root / directory_name
                if directory_path.is_symlink():
                    raise BundleInputError("bundle contains an inner symbolic link")
            for file_name in file_names:
                file_path = root / file_name
                if file_path.is_symlink():
                    raise BundleInputError("bundle contains an inner symbolic link")
                resolved = file_path.resolve(strict=True)
                if not resolved.is_relative_to(self._directory):
                    raise BundleInputError("bundle file resolves outside the input directory")
                relative_path = resolved.relative_to(self._directory).as_posix()
                self._directory_entries[relative_path] = resolved

    @staticmethod
    def _normalize_zip_path(raw_path: str) -> str:
        normalized = raw_path.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or path.is_absolute()
            or DRIVE_PATH_PATTERN.match(normalized) is not None
            or any(part in {"..", ""} for part in path.parts)
        ):
            raise BundleInputError("bundle ZIP contains an unsafe member path")
        return path.as_posix().rstrip("/")

    def _index_zip(self) -> None:
        assert self._zip is not None
        normalized_entries: dict[str, zipfile.ZipInfo] = {}
        for info in self._zip.infolist():
            normalized = self._normalize_zip_path(info.filename)
            if not normalized or info.is_dir():
                continue
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise BundleInputError("bundle ZIP contains a symbolic link")
            if normalized in normalized_entries:
                raise BundleInputError("bundle ZIP contains duplicate normalized paths")
            normalized_entries[normalized] = info

        top_level_names = {PurePosixPath(name).parts[0] for name in normalized_entries}
        has_top_level_file = any(len(PurePosixPath(name).parts) == 1 for name in normalized_entries)
        prefix = ""
        if len(top_level_names) == 1 and not has_top_level_file:
            prefix = next(iter(top_level_names)) + "/"
        for name, info in normalized_entries.items():
            if prefix:
                if not name.startswith(prefix):
                    raise BundleInputError("bundle ZIP has an inconsistent root folder")
                name = name[len(prefix) :]
            self._zip_entries[name] = info

    def _file_names(self) -> list[str]:
        entries = self._directory_entries if self._directory is not None else self._zip_entries
        return sorted(entries)

    def open_binary(self, relative_path: str) -> BinaryIO:
        if relative_path not in self._file_by_path:
            raise FileNotFoundError(relative_path)
        if self._directory is not None:
            return self._directory_entries[relative_path].open("rb")
        assert self._zip is not None
        return self._zip.open(self._zip_entries[relative_path], "r")  # type: ignore[return-value]

    def read_bytes(self, relative_path: str) -> bytes:
        with self.open_binary(relative_path) as source:
            return source.read()

    def has_file(self, relative_path: str) -> bool:
        return relative_path in self._file_by_path

    def _build_file_inventory(self) -> tuple[BundleFile, ...]:
        entries: list[BundleFile] = []
        for relative_path in self._file_names():
            digest = hashlib.sha256()
            size_bytes = 0
            with self._open_unindexed(relative_path) as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    size_bytes += len(chunk)
            entries.append(BundleFile(relative_path, size_bytes, digest.hexdigest()))
        return tuple(entries)

    def _open_unindexed(self, relative_path: str) -> BinaryIO:
        if self._directory is not None:
            return self._directory_entries[relative_path].open("rb")
        assert self._zip is not None
        return self._zip.open(self._zip_entries[relative_path], "r")  # type: ignore[return-value]

    def _compute_input_digest(self) -> tuple[str, str]:
        if self.canonical_input_path.is_file():
            digest = hashlib.sha256()
            with self.canonical_input_path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            return digest.hexdigest(), "sha256-zip-bytes-v1"

        digest = hashlib.sha256()
        for item in self.files:
            digest.update(item.relative_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(item.sha256.encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest(), "andromeda-directory-manifest-sha256-v1"

    def file_sha256(self, relative_path: str) -> str | None:
        item = self._file_by_path.get(relative_path)
        return item.sha256 if item is not None else None

    def file_size(self, relative_path: str) -> int | None:
        item = self._file_by_path.get(relative_path)
        return item.size_bytes if item is not None else None


def _issue(report: dict[str, Any], severity: str, code: str, message: str, **context: Any) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    item.update({key: value for key, value in context.items() if value is not None})
    report[severity].append(item)


def _parse_json_bytes(reader: BundleReader, path: str, report: dict[str, Any]) -> Any | None:
    try:
        return json.loads(reader.read_bytes(path).decode("utf-8"))
    except UnicodeDecodeError:
        _issue(report, "errors", "INVALID_UTF8", "JSON file is not valid UTF-8", file=path)
    except json.JSONDecodeError as error:
        _issue(
            report,
            "errors",
            "INVALID_JSON",
            "JSON file is malformed",
            file=path,
            line=error.lineno,
        )
    return None


def _parse_jsonl(
    reader: BundleReader,
    path: str,
    report: dict[str, Any],
    required_fields: tuple[str, ...] = ("external_key",),
    key_field: str = "external_key",
) -> list[tuple[int, dict[str, Any]]]:
    try:
        text_value = reader.read_bytes(path).decode("utf-8")
    except UnicodeDecodeError:
        _issue(report, "errors", "INVALID_UTF8", "JSONL file is not valid UTF-8", file=path)
        return []

    records: list[tuple[int, dict[str, Any]]] = []
    seen_keys: set[str] = set()
    for line_number, raw_line in enumerate(text_value.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            _issue(
                report,
                "errors",
                "INVALID_JSONL_LINE",
                "line is not a valid JSON value",
                file=path,
                line=line_number,
            )
            continue
        if not isinstance(record, dict):
            _issue(
                report,
                "errors",
                "JSONL_VALUE_NOT_OBJECT",
                "each nonblank JSONL line must contain one object",
                file=path,
                line=line_number,
            )
            continue

        missing_fields = [field for field in required_fields if field not in record]
        if missing_fields:
            _issue(
                report,
                "errors",
                "REQUIRED_FIELDS_MISSING",
                "record is missing required fields",
                file=path,
                line=line_number,
                fields=missing_fields,
            )
        external_key = record.get(key_field)
        if not isinstance(external_key, str) or not external_key.strip():
            _issue(
                report,
                "errors",
                "INVALID_RECORD_KEY",
                f"record {key_field} must be a nonempty string",
                file=path,
                line=line_number,
            )
        elif external_key in seen_keys:
            _issue(
                report,
                "errors",
                "DUPLICATE_DATASET_EXTERNAL_KEY"
                if key_field == "external_key"
                else "DUPLICATE_RECORD_KEY",
                f"{key_field} is duplicated within the dataset",
                file=path,
                line=line_number,
                source_key=external_key,
            )
        else:
            seen_keys.add(external_key)
        records.append((line_number, record))
    return records


def _walk_records(value: Any, path: str = "") -> list[tuple[str, Any]]:
    fields: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            fields.append((child_path, (key, child)))
            fields.extend(_walk_records(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            fields.extend(_walk_records(child, child_path))
    return fields


def _validate_requirement_tree(
    node: Any,
    *,
    report: dict[str, Any],
    file: str,
    line: int,
    operator_counts: Counter[str],
    path: str = "requirement_tree",
) -> None:
    if not isinstance(node, dict):
        _issue(
            report,
            "errors",
            "INVALID_REQUIREMENT_TREE_NODE",
            "requirement tree node must be an object",
            file=file,
            line=line,
            field_path=path,
        )
        return

    operator = node.get("operator")
    if operator is not None:
        if operator not in {"AND", "OR", "AT_LEAST"}:
            _issue(
                report,
                "errors",
                "INVALID_REQUIREMENT_OPERATOR",
                "requirement tree uses an unsupported operator",
                file=file,
                line=line,
                field_path=path,
            )
            return
        operator_counts[operator] += 1
        children = node.get("children")
        if not isinstance(children, list) or not children:
            _issue(
                report,
                "errors",
                "INVALID_REQUIREMENT_CHILDREN",
                "operator nodes require a nonempty children array",
                file=file,
                line=line,
                field_path=path,
            )
            return
        threshold = node.get("min_count")
        if operator == "AT_LEAST" and (
            not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1
        ):
            _issue(
                report,
                "errors",
                "INVALID_REQUIREMENT_THRESHOLD",
                "AT_LEAST nodes require a positive integer min_count",
                file=file,
                line=line,
                field_path=path,
            )
        elif (
            operator != "AT_LEAST"
            and threshold is not None
            and (
                not isinstance(threshold, int)
                or isinstance(threshold, bool)
                or threshold < 1
                or threshold > len(children)
            )
        ):
            _issue(
                report,
                "errors",
                "INVALID_REQUIREMENT_THRESHOLD",
                "operator min_count must be within the number of children",
                file=file,
                line=line,
                field_path=path,
            )
        if (
            operator == "AT_LEAST"
            and isinstance(threshold, int)
            and not isinstance(threshold, bool)
            and threshold > len(children)
        ):
            _issue(
                report,
                "errors",
                "INVALID_REQUIREMENT_THRESHOLD",
                "operator min_count cannot exceed the number of children",
                file=file,
                line=line,
                field_path=path,
            )
        for index, child in enumerate(children):
            _validate_requirement_tree(
                child,
                report=report,
                file=file,
                line=line,
                operator_counts=operator_counts,
                path=f"{path}.children[{index}]",
            )
        return

    exam = node.get("exam")
    if not isinstance(exam, dict) or not isinstance(exam.get("exam_key"), str):
        _issue(
            report,
            "errors",
            "INVALID_REQUIREMENT_LEAF",
            "leaf nodes must contain an exam object with exam_key",
            file=file,
            line=line,
            field_path=path,
        )
        return
    minimum_score = exam.get("minimum_score")
    if minimum_score is not None and (
        not isinstance(minimum_score, (int, float))
        or isinstance(minimum_score, bool)
        or minimum_score < 0
    ):
        _issue(
            report,
            "errors",
            "INVALID_REQUIREMENT_SCORE",
            "minimum_score must be nonnegative when present",
            file=file,
            line=line,
            field_path=f"{path}.exam.minimum_score",
        )


def _manual_unresolved_signatures(
    rows: list[dict[str, str]], report: dict[str, Any]
) -> Counter[tuple[str, str, str]]:
    signatures: Counter[tuple[str, str, str]] = Counter()
    for row_number, row in enumerate(rows, start=2):
        if row.get("issue_type") != "record_reference_unresolved":
            continue
        match = UNRESOLVED_DETAIL_PATTERN.search(row.get("details", ""))
        if match is None:
            _issue(
                report,
                "warnings",
                "MANUAL_REFERENCE_DETAIL_UNPARSED",
                "manual unresolved-reference detail is not in the recognized format",
                file="manual_review.csv",
                line=row_number,
                source_key=row.get("record_key"),
            )
            continue
        signatures[(row.get("record_key", ""), match.group("field"), match.group("target"))] += 1
    return signatures


def validate_bundle(input_path: str | Path) -> dict[str, Any]:
    """Return a deterministic report; this function does not use a database or network."""

    with BundleReader(input_path) as reader:
        report: dict[str, Any] = {
            "report_version": 1,
            "validator_contract_version": VALIDATOR_CONTRACT_VERSION,
            "valid": True,
            "input": {
                "path": str(reader.canonical_input_path),
                "kind": "zip" if reader.canonical_input_path.is_file() else "directory",
                "digest_algorithm": reader.digest_algorithm,
                "digest": reader.input_digest,
            },
            "input_schema_versions": {},
            "files": [],
            "datasets": {},
            "counts": {},
            "source_artifacts": {},
            "relationships": {},
            "requirements": {},
            "manual_review": {},
            "sanitization": {},
            "comparison_to_export_validation": {},
            "errors": [],
            "warnings": [],
        }
        logger.info(
            "bundle validation started",
            extra={
                "event": "bundle.validation.started",
                "phase": "input",
                "digest": reader.input_digest,
                "outcome": "started",
            },
        )

        file_inventory = [
            {
                "path": item.relative_path,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in reader.files
        ]
        report["files"] = file_inventory
        report["counts"]["bundle_files"] = len(file_inventory)
        report["counts"]["bundle_bytes"] = sum(item.size_bytes for item in reader.files)

        for required_file in REQUIRED_ROOT_FILES:
            if not reader.has_file(required_file):
                _issue(
                    report,
                    "errors",
                    "REQUIRED_BUNDLE_FILE_MISSING",
                    "required bundle file is missing",
                    file=required_file,
                )
        if not reader.has_file("data") and not any(
            name.startswith("data/") for name in reader._file_by_path
        ):
            _issue(
                report, "errors", "DATA_DIRECTORY_MISSING", "normalized data directory is missing"
            )

        for text_file in ("README.md", "report.md"):
            if reader.has_file(text_file):
                try:
                    reader.read_bytes(text_file).decode("utf-8")
                except UnicodeDecodeError:
                    _issue(
                        report,
                        "errors",
                        "INVALID_UTF8",
                        "text file is not valid UTF-8",
                        file=text_file,
                    )

        export_report = _parse_json_bytes(reader, "validation_report.json", report)
        if not isinstance(export_report, dict):
            export_report = {}
        confirmed_plan_links: list[dict[str, Any]] = []
        if reader.has_file("user_confirmed_study_plan_links.json"):
            parsed_confirmation = _parse_json_bytes(
                reader, "user_confirmed_study_plan_links.json", report
            )
            if isinstance(parsed_confirmation, dict):
                report["input_schema_versions"]["user_confirmed_study_plan_links"] = (
                    parsed_confirmation.get("schema_version")
                )
                if parsed_confirmation.get("schema_version") != 1:
                    _issue(
                        report,
                        "errors",
                        "UNSUPPORTED_INPUT_SCHEMA_VERSION",
                        "user-confirmed mapping schema version is not supported",
                        file="user_confirmed_study_plan_links.json",
                    )
                raw_links = parsed_confirmation.get("links", [])
                if not isinstance(raw_links, list) or not all(
                    isinstance(link, dict) for link in raw_links
                ):
                    _issue(
                        report,
                        "errors",
                        "USER_CONFIRMATION_LINKS_INVALID",
                        "user-confirmed plan links must be an array of objects",
                        file="user_confirmed_study_plan_links.json",
                    )
                else:
                    confirmed_plan_links = raw_links
                required_confirmation_fields = {
                    "program_external_key",
                    "profile_code",
                    "catalog_card_artifact_key",
                    "study_plan_url",
                }
                for index, link in enumerate(confirmed_plan_links, start=1):
                    missing_fields = sorted(required_confirmation_fields - set(link))
                    if missing_fields:
                        _issue(
                            report,
                            "errors",
                            "USER_CONFIRMATION_FIELDS_MISSING",
                            "confirmed plan link is missing required fields",
                            file="user_confirmed_study_plan_links.json",
                            line=index,
                            fields=missing_fields,
                        )
                report["counts"]["user_confirmed_study_plan_links"] = len(confirmed_plan_links)
        else:
            _issue(
                report,
                "warnings",
                "USER_CONFIRMATION_FILE_MISSING",
                "no user-confirmed plan-link metadata file was included",
                file="user_confirmed_study_plan_links.json",
            )
        report["input_schema_versions"]["normalized_jsonl"] = export_report.get("schema_version")
        if export_report.get("schema_version") is None:
            _issue(
                report,
                "warnings",
                "EXPORT_SCHEMA_VERSION_UNDECLARED",
                "normalized JSONL files do not declare an export schema version",
                file="validation_report.json",
            )

        source_manifest_path = "source_artifacts.jsonl"
        manifest_entries: list[dict[str, Any]] = []
        if reader.has_file(source_manifest_path):
            for line_number, record in _parse_jsonl(
                reader,
                source_manifest_path,
                report,
                required_fields=(
                    "source_key",
                    "requested_url",
                    "retrieved_at",
                    "sha256",
                    "raw_path",
                    "storage_status",
                ),
                key_field="source_key",
            ):
                manifest_entries.append(record)
                source_key = record.get("source_key")
                if not isinstance(source_key, str) or not source_key.strip():
                    _issue(
                        report,
                        "errors",
                        "INVALID_SOURCE_ARTIFACT_KEY",
                        "manifest source_key must be a nonempty string",
                        file=source_manifest_path,
                        line=line_number,
                    )

        manifest_by_key: dict[str, dict[str, Any]] = {}
        manifest_by_raw_path: dict[str, dict[str, Any]] = {}
        status_counts: Counter[str] = Counter()
        raw_expected_paths: set[str] = set()
        raw_hash_failures: list[str] = []
        for line_number, artifact in enumerate(manifest_entries, start=1):
            source_key = artifact.get("source_key")
            if not isinstance(source_key, str):
                continue
            if source_key in manifest_by_key:
                _issue(
                    report,
                    "errors",
                    "DUPLICATE_SOURCE_ARTIFACT_KEY",
                    "source artifact key is duplicated",
                    file=source_manifest_path,
                    line=line_number,
                    source_key=source_key,
                )
                continue
            manifest_by_key[source_key] = artifact
            storage_status = artifact.get("storage_status")
            status_counts[str(storage_status)] += 1
            normalized_source_type = str(artifact.get("source_type") or "").casefold()
            if "olymp" in normalized_source_type and storage_status == "saved":
                _issue(
                    report,
                    "errors",
                    "OLYMPIAD_SOURCE_FILE_FORBIDDEN",
                    "saved olympiad source artifacts are excluded from this service",
                    file=source_manifest_path,
                    line=line_number,
                    source_key=source_key,
                )
            if "personal" in normalized_source_type and storage_status == "saved":
                _issue(
                    report,
                    "errors",
                    "PERSONAL_SOURCE_FILE_FORBIDDEN",
                    "source artifacts declared as personal data must not be saved",
                    file=source_manifest_path,
                    line=line_number,
                    source_key=source_key,
                )
            if storage_status not in ALLOWED_STORAGE_STATUSES:
                _issue(
                    report,
                    "warnings",
                    "UNKNOWN_SOURCE_STORAGE_STATUS",
                    "source artifact uses an unrecognized status and is retained as declared",
                    file=source_manifest_path,
                    line=line_number,
                    source_key=source_key,
                )
            source_digest = artifact.get("sha256")
            if source_digest is not None and (
                not isinstance(source_digest, str)
                or SHA256_PATTERN.fullmatch(source_digest) is None
            ):
                _issue(
                    report,
                    "errors",
                    "INVALID_SOURCE_SHA256",
                    "source artifact SHA-256 is not a lowercase hexadecimal digest",
                    file=source_manifest_path,
                    line=line_number,
                    source_key=source_key,
                )
            raw_path_value = artifact.get("raw_path")
            if storage_status == "saved":
                if not isinstance(raw_path_value, str) or not raw_path_value:
                    _issue(
                        report,
                        "errors",
                        "SAVED_SOURCE_PATH_MISSING",
                        "saved source artifact has no raw_path",
                        file=source_manifest_path,
                        line=line_number,
                        source_key=source_key,
                    )
                    continue
                try:
                    relative_raw_path = BundleReader._normalize_zip_path(raw_path_value)
                except BundleInputError:
                    _issue(
                        report,
                        "errors",
                        "UNSAFE_RAW_PATH",
                        "source artifact raw_path is unsafe",
                        file=source_manifest_path,
                        line=line_number,
                        source_key=source_key,
                    )
                    continue
                if not relative_raw_path.startswith("raw/"):
                    _issue(
                        report,
                        "errors",
                        "RAW_PATH_OUTSIDE_RAW_DIRECTORY",
                        "saved source files must reside under raw/",
                        file=source_manifest_path,
                        line=line_number,
                        source_key=source_key,
                    )
                    continue
                raw_expected_paths.add(relative_raw_path)
                manifest_by_raw_path[relative_raw_path] = artifact
                actual_digest = reader.file_sha256(relative_raw_path)
                if actual_digest is None:
                    _issue(
                        report,
                        "errors",
                        "SAVED_SOURCE_FILE_MISSING",
                        "manifest marks a source file saved but the file is missing",
                        file=relative_raw_path,
                        line=line_number,
                        source_key=source_key,
                    )
                    raw_hash_failures.append(source_key)
                elif not isinstance(source_digest, str) or actual_digest != source_digest:
                    _issue(
                        report,
                        "errors",
                        "SAVED_SOURCE_HASH_MISMATCH",
                        "saved source file does not match its manifest SHA-256",
                        file=relative_raw_path,
                        line=line_number,
                        source_key=source_key,
                    )
                    raw_hash_failures.append(source_key)
            elif raw_path_value is not None:
                _issue(
                    report,
                    "errors",
                    "UNSAVED_SOURCE_HAS_RAW_PATH",
                    "non-saved source status must not claim an archived raw file",
                    file=source_manifest_path,
                    line=line_number,
                    source_key=source_key,
                )

        raw_actual_paths = {name for name in reader._file_by_path if name.startswith("raw/")}
        for relative_path in sorted(raw_actual_paths):
            normalized_raw_path = relative_path.casefold()
            if any(term in normalized_raw_path for term in ("olymp", "applicant", "personal")):
                _issue(
                    report,
                    "errors",
                    "SENSITIVE_RAW_PATH_FORBIDDEN",
                    "raw source path appears to contain excluded olympiad or applicant data",
                    file=relative_path,
                )
        for unexpected_path in sorted(raw_actual_paths - raw_expected_paths):
            _issue(
                report,
                "errors",
                "UNREFERENCED_RAW_FILE",
                "raw file is not declared as saved in the manifest",
                file=unexpected_path,
            )
        report["source_artifacts"] = {
            "manifest_count": len(manifest_entries),
            "unique_keys": len(manifest_by_key),
            "storage_status_counts": dict(sorted(status_counts.items())),
            "saved_files_declared": len(raw_expected_paths),
            "saved_files_present": len(raw_actual_paths & raw_expected_paths),
            "saved_file_hash_failures": sorted(set(raw_hash_failures)),
            "unreferenced_raw_files": sorted(raw_actual_paths - raw_expected_paths),
        }
        report["counts"]["source_artifacts"] = len(manifest_entries)
        report["counts"]["saved_raw_files"] = len(raw_expected_paths)
        report["counts"]["unavailable_or_omitted_raw_files"] = sum(
            count for status, count in status_counts.items() if status != "saved"
        )

        dataset_paths = sorted(
            path
            for path in reader._file_by_path
            if path.startswith("data/") and path.endswith(".jsonl")
        )
        if not dataset_paths:
            _issue(
                report,
                "errors",
                "NO_NORMALIZED_DATASETS",
                "no normalized JSONL datasets were found",
            )

        datasets: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        key_to_dataset: dict[str, str] = {}
        duplicate_global_keys: set[str] = set()
        for path in dataset_paths:
            dataset_name = PurePosixPath(path).name
            records = _parse_jsonl(
                reader,
                path,
                report,
                required_fields=("external_key", *DATASET_REQUIRED_FIELDS.get(dataset_name, ())),
            )
            datasets[dataset_name] = records
            report["datasets"][dataset_name] = {
                "record_count": len(records),
                "sha256": reader.file_sha256(path),
                "size_bytes": reader.file_size(path),
            }
            report["counts"][dataset_name.removesuffix(".jsonl")] = len(records)
            logger.info(
                "bundle dataset parsed",
                extra={
                    "event": "bundle.validation.dataset_parsed",
                    "phase": "jsonl",
                    "relative_file": path,
                    "record_count": len(records),
                    "digest": reader.file_sha256(path),
                    "outcome": "completed",
                },
            )
            if "olymp" in dataset_name.casefold():
                _issue(
                    report,
                    "errors",
                    "OLYMPIAD_DATASET_FORBIDDEN",
                    "olympiad datasets are excluded from this service",
                    file=path,
                )
            for line_number, record in records:
                external_key = record.get("external_key")
                if isinstance(external_key, str):
                    if external_key in key_to_dataset:
                        duplicate_global_keys.add(external_key)
                    else:
                        key_to_dataset[external_key] = dataset_name
                for field_path, (field_name, field_value) in _walk_records(record):
                    normalized_field_name = re.sub(r"[^a-z0-9]", "", field_name.casefold())
                    if normalized_field_name in PERSONAL_FIELD_NAMES:
                        _issue(
                            report,
                            "errors",
                            "APPLICANT_PERSONAL_FIELD_FORBIDDEN",
                            "personal applicant fields are excluded from this service",
                            file=path,
                            line=line_number,
                            field_path=field_path,
                        )
                    if "olymp" in field_name.casefold():
                        _issue(
                            report,
                            "errors",
                            "OLYMPIAD_FIELD_FORBIDDEN",
                            "olympiad data fields are excluded from this service",
                            file=path,
                            line=line_number,
                            field_path=field_path,
                        )
                    if field_name not in SAFE_APPLICANT_FIELDS and isinstance(field_value, str):
                        if re.search(r"olymp|олимп", field_value, flags=re.IGNORECASE):
                            _issue(
                                report,
                                "errors",
                                "OLYMPIAD_CONTENT_FORBIDDEN",
                                "normalized records contain excluded olympiad content",
                                file=path,
                                line=line_number,
                                field_path=field_path,
                            )
            if dataset_name == "admission_exam_requirements.jsonl":
                requirement_operator_counts: Counter[str] = Counter()
                for line_number, record in records:
                    _validate_requirement_tree(
                        record.get("requirement_tree"),
                        report=report,
                        file=path,
                        line=line_number,
                        operator_counts=requirement_operator_counts,
                    )
                report["requirements"]["operator_counts"] = {
                    operator: requirement_operator_counts.get(operator, 0)
                    for operator in ("AND", "OR", "AT_LEAST")
                }
                report["requirements"]["tree_count"] = len(records)
                report["counts"]["requirement_trees"] = len(records)

        if duplicate_global_keys:
            for external_key in sorted(duplicate_global_keys):
                _issue(
                    report,
                    "errors",
                    "DUPLICATE_GLOBAL_EXTERNAL_KEY",
                    "external_key occurs in more than one normalized record",
                    source_key=external_key,
                )
        report["counts"]["normalized_datasets"] = len(dataset_paths)
        report["counts"]["normalized_records"] = sum(len(records) for records in datasets.values())

        program_keys = {
            record.get("external_key")
            for _, record in datasets.get("educational_programs.jsonl", [])
        }
        study_plan_rows = datasets.get("study_plans.jsonl", [])
        confirmed_link_programs: set[str] = set()
        confirmed_plan_matches = 0
        for index, link in enumerate(confirmed_plan_links, start=1):
            program_key = link.get("program_external_key")
            artifact_key = link.get("catalog_card_artifact_key")
            if not isinstance(program_key, str) or program_key not in program_keys:
                _issue(
                    report,
                    "errors",
                    "USER_CONFIRMED_PROGRAM_UNRESOLVED",
                    "confirmed plan link points to a missing program record",
                    file="user_confirmed_study_plan_links.json",
                    line=index,
                    source_key=str(program_key),
                )
            if not isinstance(artifact_key, str) or artifact_key not in manifest_by_key:
                _issue(
                    report,
                    "errors",
                    "USER_CONFIRMED_SOURCE_UNRESOLVED",
                    "confirmed plan link points to a missing catalog-card artifact",
                    file="user_confirmed_study_plan_links.json",
                    line=index,
                    source_key=str(artifact_key),
                )
            if isinstance(program_key, str):
                if program_key in confirmed_link_programs:
                    _issue(
                        report,
                        "errors",
                        "DUPLICATE_USER_CONFIRMED_PROGRAM_LINK",
                        "program has more than one user-confirmed plan-link row",
                        file="user_confirmed_study_plan_links.json",
                        line=index,
                        source_key=program_key,
                    )
                confirmed_link_programs.add(program_key)
            exact_plan_match = any(
                plan.get("program_key") == program_key
                and plan.get("study_plan_url") == link.get("study_plan_url")
                for _, plan in study_plan_rows
            )
            if exact_plan_match:
                confirmed_plan_matches += 1
            else:
                _issue(
                    report,
                    "errors",
                    "USER_CONFIRMED_PLAN_TARGET_UNRESOLVED",
                    "confirmed catalog link has no matching study-plan record",
                    file="user_confirmed_study_plan_links.json",
                    line=index,
                    source_key=str(program_key),
                )
        report["counts"]["user_confirmed_plan_matches"] = confirmed_plan_matches

        known_keys = set(key_to_dataset) | set(manifest_by_key)
        manual_rows: list[dict[str, str]] = []
        if reader.has_file("manual_review.csv"):
            try:
                csv_text = reader.read_bytes("manual_review.csv").decode("utf-8-sig")
                parsed_csv = csv.DictReader(io.StringIO(csv_text, newline=""))
                required_headers = {"record_key", "issue_type", "source_url", "details"}
                if parsed_csv.fieldnames is None or not required_headers <= set(
                    parsed_csv.fieldnames
                ):
                    _issue(
                        report,
                        "errors",
                        "MANUAL_REVIEW_HEADERS_INVALID",
                        "manual-review CSV does not have the required headers",
                        file="manual_review.csv",
                    )
                else:
                    for row_number, row in enumerate(parsed_csv, start=2):
                        if None in row:
                            _issue(
                                report,
                                "errors",
                                "MANUAL_REVIEW_ROW_INVALID",
                                "manual-review CSV row has more columns than its header",
                                file="manual_review.csv",
                                line=row_number,
                            )
                            continue
                        clean_row = {key: value or "" for key, value in row.items() if key}
                        if not clean_row.get("record_key") or not clean_row.get("issue_type"):
                            _issue(
                                report,
                                "errors",
                                "MANUAL_REVIEW_ROW_MISSING_IDENTITY",
                                "manual-review row requires record_key and issue_type",
                                file="manual_review.csv",
                                line=row_number,
                            )
                        manual_rows.append(clean_row)
            except UnicodeDecodeError:
                _issue(
                    report,
                    "errors",
                    "INVALID_UTF8",
                    "manual-review CSV is not valid UTF-8",
                    file="manual_review.csv",
                )

        unresolved_manual_signatures = _manual_unresolved_signatures(manual_rows, report)
        unresolved_references: Counter[tuple[str, str, str]] = Counter()
        resolved_reference_count = 0
        source_artifact_reference_errors = 0
        for dataset_name, records in datasets.items():
            path = f"data/{dataset_name}"
            for line_number, record in records:
                external_key = record.get("external_key")
                if not isinstance(external_key, str):
                    continue
                for field_path, (field_name, field_value) in _walk_records(record):
                    if field_name in {"source_artifact_key", "source_artifact_keys"}:
                        values = field_value if isinstance(field_value, list) else [field_value]
                        for source_key in values:
                            if source_key is None:
                                continue
                            if not isinstance(source_key, str) or source_key not in manifest_by_key:
                                source_artifact_reference_errors += 1
                                _issue(
                                    report,
                                    "errors",
                                    "SOURCE_ARTIFACT_REFERENCE_UNRESOLVED",
                                    "normalized row references a missing source artifact",
                                    file=path,
                                    line=line_number,
                                    source_key=external_key,
                                    field_path=field_path,
                                )
                        continue
                    if field_name == "external_key":
                        continue
                    if dataset_name == "relationships.jsonl" and field_name in {
                        "source_key",
                        "target_key",
                    }:
                        continue
                    if field_name.endswith("_key") or field_name.endswith("_keys"):
                        values = field_value if isinstance(field_value, list) else [field_value]
                        for target_key in values:
                            if target_key is None:
                                continue
                            if isinstance(target_key, str) and target_key in known_keys:
                                resolved_reference_count += 1
                            elif isinstance(target_key, str):
                                unresolved_references[(external_key, field_path, target_key)] += 1

        for signature, count in sorted(unresolved_references.items()):
            if unresolved_manual_signatures[signature] < count:
                record_key, field_path, target_key = signature
                _issue(
                    report,
                    "errors",
                    "UNREVIEWED_NESTED_REFERENCE",
                    "unresolved nested reference has no matching manual-review row",
                    source_key=record_key,
                    field_path=field_path,
                    target_key=target_key,
                )
        for signature, count in sorted(unresolved_manual_signatures.items()):
            if unresolved_references[signature] != count:
                record_key, field_path, target_key = signature
                _issue(
                    report,
                    "errors",
                    "STALE_MANUAL_REFERENCE_REVIEW",
                    "manual-review row does not match an unresolved nested reference",
                    source_key=record_key,
                    field_path=field_path,
                    target_key=target_key,
                )

        relationship_rows = datasets.get("relationships.jsonl", [])
        unresolved_relationships: list[dict[str, str]] = []
        for line_number, relationship in relationship_rows:
            for endpoint in ("source_key", "target_key"):
                target_key = relationship.get(endpoint)
                if not isinstance(target_key, str) or target_key not in known_keys:
                    unresolved_relationships.append(
                        {
                            "relationship_key": str(relationship.get("external_key", "")),
                            "field": endpoint,
                            "target_key": str(target_key),
                        }
                    )
                    _issue(
                        report,
                        "errors",
                        "EXPLICIT_RELATIONSHIP_ENDPOINT_UNRESOLVED",
                        "explicit relationship endpoint does not resolve to a known key",
                        file="data/relationships.jsonl",
                        line=line_number,
                        source_key=str(relationship.get("external_key", "")),
                        field_path=endpoint,
                    )
        report["relationships"] = {
            "explicit_relationship_count": len(relationship_rows),
            "resolved_nested_reference_count": resolved_reference_count,
            "unresolved_nested_reference_count": sum(unresolved_references.values()),
            "actual_nested_reference_counts": {
                "record_key_references": resolved_reference_count
                + sum(unresolved_references.values()),
                "resolved_key_references": resolved_reference_count,
                "manual_review_key_references": sum(unresolved_references.values()),
            },
            "unresolved_nested_references": [
                {
                    "record_key": record_key,
                    "field_path": field_path,
                    "target_key": target_key,
                    "count": count,
                }
                for (record_key, field_path, target_key), count in sorted(
                    unresolved_references.items()
                )
            ],
            "unresolved_explicit_relationship_endpoints": unresolved_relationships,
            "source_artifact_reference_errors": source_artifact_reference_errors,
        }
        actual_reference_counts = {
            "record_key_references": resolved_reference_count + sum(unresolved_references.values()),
            "resolved_key_references": resolved_reference_count,
            "manual_review_key_references": sum(unresolved_references.values()),
        }
        export_validation = export_report.get("validation", {})
        export_refresh = export_report.get("bundle_refresh", {})
        exported_import_counts: Any = {}
        if isinstance(export_validation, dict):
            current_bundle_counts = export_validation.get("bundle_reference_counts")
            refresh_has_not_been_imported = (
                isinstance(export_refresh, dict)
                and export_refresh.get("database_contains_this_refresh") is False
            )
            if isinstance(current_bundle_counts, dict):
                exported_import_counts = current_bundle_counts
            elif not refresh_has_not_been_imported:
                # Older bundle reports store counters from a previous DB import here.
                exported_import_counts = export_validation.get("database_import", {})
        reference_count_mismatches: dict[str, dict[str, int]] = {}
        if isinstance(exported_import_counts, dict):
            for field_name, actual_count in actual_reference_counts.items():
                expected_count = exported_import_counts.get(field_name)
                if isinstance(expected_count, int) and expected_count != actual_count:
                    reference_count_mismatches[field_name] = {
                        "export_validation_report": expected_count,
                        "actual": actual_count,
                    }
        report["relationships"]["reference_count_mismatches"] = reference_count_mismatches
        for field_name, mismatch in sorted(reference_count_mismatches.items()):
            _issue(
                report,
                "errors",
                "NESTED_REFERENCE_COUNT_MISMATCH",
                "nested reference count differs from the included export report",
                field_path=field_name,
                expected=mismatch["export_validation_report"],
                actual=mismatch["actual"],
            )
        report["manual_review"] = {
            "row_count": len(manual_rows),
            "issue_type_counts": dict(
                sorted(Counter(row.get("issue_type", "") for row in manual_rows).items())
            ),
            "unresolved_reference_rows": sum(unresolved_manual_signatures.values()),
            "unresolved_record_key_count": len(
                {
                    row.get("record_key", "")
                    for row in manual_rows
                    if row.get("record_key") not in known_keys
                }
            ),
        }
        if report["manual_review"]["unresolved_record_key_count"]:
            _issue(
                report,
                "warnings",
                "MANUAL_REVIEW_KEYS_NOT_CANONICAL_RECORDS",
                "some manual-review rows refer to absent source or schema identifiers",
                count=report["manual_review"]["unresolved_record_key_count"],
            )
        report["counts"]["manual_review"] = len(manual_rows)
        report["counts"]["explicit_relationships"] = len(relationship_rows)

        normalized_text_has_olympiad_content = any(
            re.search(r"olymp|олимп", reader.read_bytes(path).decode("utf-8"), re.IGNORECASE)
            for path in dataset_paths
            if reader.file_size(path) is not None
        )
        olympiad_dataset_count = sum("olymp" in name.casefold() for name in datasets)
        coverage_report = export_report.get("coverage", {})
        if not isinstance(coverage_report, dict):
            coverage_report = {}
        applicant_rows_declared = coverage_report.get("personal_applicant_rows_retained")
        olympiad_data_declared = coverage_report.get("olympiad_data_included")
        report["sanitization"] = {
            "olympiad_datasets": olympiad_dataset_count,
            "normalized_olympiad_content_found": normalized_text_has_olympiad_content,
            "olympiad_data_declared": olympiad_data_declared,
            "applicant_personal_fields_found": any(
                issue["code"] == "APPLICANT_PERSONAL_FIELD_FORBIDDEN" for issue in report["errors"]
            ),
            "applicant_personal_rows_declared": applicant_rows_declared,
        }
        if normalized_text_has_olympiad_content and not any(
            issue["code"] == "OLYMPIAD_CONTENT_FORBIDDEN" for issue in report["errors"]
        ):
            _issue(
                report,
                "errors",
                "OLYMPIAD_CONTENT_FORBIDDEN",
                "normalized dataset contains excluded olympiad content",
            )
        if olympiad_data_declared is True:
            _issue(
                report,
                "errors",
                "OLYMPIAD_DATA_DECLARED",
                "export report declares that olympiad data were included",
            )
        if applicant_rows_declared is True:
            _issue(
                report,
                "errors",
                "APPLICANT_PERSONAL_ROWS_DECLARED",
                "export report declares that applicant personal rows were retained",
            )

        actual_dataset_counts = {
            name.removesuffix(".jsonl"): len(records) for name, records in datasets.items()
        }
        exported_counts = export_report.get("counts", {})
        count_mismatches: dict[str, dict[str, int]] = {}
        if isinstance(exported_counts, dict):
            for dataset_name, actual_count in actual_dataset_counts.items():
                expected_count = exported_counts.get(dataset_name)
                if isinstance(expected_count, int) and expected_count != actual_count:
                    count_mismatches[dataset_name] = {
                        "export_validation_report": expected_count,
                        "actual": actual_count,
                    }
            expected_total = exported_counts.get("jsonl_records_total")
            actual_total = sum(actual_dataset_counts.values())
            if isinstance(expected_total, int) and expected_total != actual_total:
                count_mismatches["jsonl_records_total"] = {
                    "export_validation_report": expected_total,
                    "actual": actual_total,
                }
        report["comparison_to_export_validation"] = {
            "export_validation_errors": export_report.get("validation", {}).get("errors"),
            "count_mismatches": count_mismatches,
            "expected_file_count": export_report.get("validation", {}).get("jsonl_files"),
            "actual_file_count": len(dataset_paths),
        }
        for dataset_name, mismatch in sorted(count_mismatches.items()):
            _issue(
                report,
                "errors",
                "EXPORT_COUNT_MISMATCH",
                "normalized row count differs from the included export report",
                dataset=dataset_name,
                expected=mismatch["export_validation_report"],
                actual=mismatch["actual"],
            )
        exported_validation = export_report.get("validation", {})
        if isinstance(exported_validation, dict):
            expected_files = exported_validation.get("jsonl_files")
            if isinstance(expected_files, int) and expected_files != len(dataset_paths):
                _issue(
                    report,
                    "errors",
                    "EXPORT_DATASET_COUNT_MISMATCH",
                    "normalized dataset file count differs from the included export report",
                    expected=expected_files,
                    actual=len(dataset_paths),
                )
            if exported_validation.get("errors"):
                _issue(
                    report,
                    "errors",
                    "EXPORT_VALIDATION_REPORTED_ERRORS",
                    "included export validation report contains errors",
                )
            expected_operators = exported_validation.get("requirement_tree_operator_nodes")
            if isinstance(expected_operators, dict):
                actual_operators = report["requirements"].get("operator_counts", {})
                operator_mismatches = {
                    operator: {
                        "export_validation_report": expected_operators.get(operator, 0),
                        "actual": actual_operators.get(operator, 0),
                    }
                    for operator in ("AND", "OR", "AT_LEAST")
                    if expected_operators.get(operator, 0) != actual_operators.get(operator, 0)
                }
                report["requirements"]["operator_count_mismatches"] = operator_mismatches
                for operator, mismatch in sorted(operator_mismatches.items()):
                    _issue(
                        report,
                        "errors",
                        "REQUIREMENT_OPERATOR_COUNT_MISMATCH",
                        "requirement operator count differs from the included export report",
                        field_path=operator,
                        expected=mismatch["export_validation_report"],
                        actual=mismatch["actual"],
                    )

        for severity in ("errors", "warnings"):
            report[severity].sort(
                key=lambda item: (
                    item.get("code", ""),
                    item.get("file", ""),
                    item.get("line", 0),
                    item.get("source_key", ""),
                    item.get("field_path", ""),
                )
            )
        report["valid"] = not report["errors"]
        logger.log(
            logging.INFO if report["valid"] else logging.ERROR,
            "bundle validation completed",
            extra={
                "event": "bundle.validation.completed",
                "phase": "complete",
                "digest": reader.input_digest,
                "record_count": report["counts"].get("normalized_records", 0),
                "error_code": report["errors"][0]["code"] if report["errors"] else None,
                "outcome": "valid" if report["valid"] else "invalid",
            },
        )
        return report


def render_validation_report(report: dict[str, Any]) -> bytes:
    """Serialize a stable UTF-8 JSON report with fixed separators and key order."""

    return (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_validation_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write validation evidence outside the inspected bundle."""

    destination = Path(output_path).expanduser()
    if destination.exists() and destination.is_dir():
        destination = destination / "validation-report.json"
    resolved_destination = destination.resolve(strict=False)
    source_path = Path(report["input"]["path"]).resolve(strict=True)
    if source_path.is_file() and resolved_destination == source_path:
        raise BundleInputError("validation report output cannot replace the input ZIP")
    if source_path.is_dir() and resolved_destination.is_relative_to(source_path):
        raise BundleInputError("validation report output cannot be written inside the input bundle")
    resolved_destination.parent.mkdir(parents=True, exist_ok=True)
    resolved_destination.write_bytes(render_validation_report(report))
    return resolved_destination
