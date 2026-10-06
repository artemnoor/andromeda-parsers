"""Resumable one-choice-per-record Jev classification over normalized exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from academic_data_service.classification.taxonomy import (
    CATEGORY_NAMES,
    CHOICE_CRITERIA,
    CONFIDENCE_REVIEW_THRESHOLD,
    MODEL_ID,
    PROBABILITY_MARGIN_REVIEW_THRESHOLD,
    PROMPT_VERSION,
    PROVIDER,
    QUESTION_INSTRUCTIONS,
    TAXONOMY_KEY,
    TAXONOMY_STATE,
    TAXONOMY_VERSION,
    prompt_sha256,
)

API_URL = "https://polza.ai/api/v1/systemone"
DATASET_FILENAMES = {
    "catalog_course": "courses.jsonl",
    "curriculum_item": "curriculum_items.jsonl",
}


class JevClassificationError(RuntimeError):
    """The source, API response, or resumable output failed validation."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise JevClassificationError(
                        f"invalid JSON in {path.name} at line {line_number}"
                    ) from error
                if not isinstance(value, dict):
                    raise JevClassificationError(f"non-object JSON row in {path.name}")
                records.append(value)
    except OSError as error:
        raise JevClassificationError(f"cannot read source dataset {path.name}") from error
    return records


def _load_subjects(bundle_path: Path) -> tuple[list[dict[str, Any]], str]:
    subjects: list[dict[str, Any]] = []
    try:
        programs = {
            row.get("external_key"): row
            for row in _read_jsonl(bundle_path / "data" / "educational_programs.jsonl")
        }
        departments = {
            row.get("external_key"): row
            for row in _read_jsonl(bundle_path / "data" / "departments.jsonl")
        }
        directions = {
            row.get("external_key"): row
            for row in _read_jsonl(bundle_path / "data" / "directions.jsonl")
        }
        for subject_type, filename in DATASET_FILENAMES.items():
            rows = _read_jsonl(bundle_path / "data" / filename)
            for source in rows:
                subject = _build_subject(source, subject_type)
                program = programs.get(subject["program_key"])
                if program is not None:
                    direction = directions.get(program.get("direction_key"), {})
                    department = departments.get(program.get("department_key"), {})
                    context = subject["context"]
                    context.update(
                        {
                            key: value
                            for key, value in {
                                "direction_code": direction.get("code"),
                                "direction_name": direction.get("name"),
                                "department_code": department.get("code"),
                                "department_name": department.get("name"),
                                "program_code": program.get("code"),
                                "program_name": program.get("name"),
                                "profile_description": (program.get("description") or "")[:250]
                                or None,
                            }.items()
                            if value not in (None, "")
                        }
                    )
                    input_record = {
                        "subject_type": subject["subject_type"],
                        "subject_external_key": subject["subject_external_key"],
                        "subject_name": subject["subject_name"],
                        "context": context,
                    }
                    subject["input_sha256"] = _sha256(_canonical_json(input_record).encode("utf-8"))
                subjects.append(subject)
        source_filenames = [
            "data/courses.jsonl",
            "data/curriculum_items.jsonl",
            "data/departments.jsonl",
            "data/directions.jsonl",
            "data/educational_programs.jsonl",
        ]
        bundle_digest = hashlib.sha256()
        for filename in source_filenames:
            file_digest = _sha256((bundle_path / filename).read_bytes())
            bundle_digest.update(filename.encode("utf-8"))
            bundle_digest.update(b"\0")
            bundle_digest.update(file_digest.encode("ascii"))
            bundle_digest.update(b"\n")
        return subjects, bundle_digest.hexdigest()
    except Exception as error:
        if isinstance(error, JevClassificationError):
            raise
        raise JevClassificationError("the normalized source bundle is invalid") from error


def _build_subject(row: dict[str, Any], subject_type: str) -> dict[str, Any]:
    external_key = row.get("external_key")
    if not isinstance(external_key, str) or not external_key:
        raise JevClassificationError(f"{subject_type} has no external_key")
    if subject_type == "catalog_course":
        subject_name = row.get("name")
        context = {
            "direction_code": row.get("direction_code"),
            "direction_name": row.get("direction_name"),
            "department_code": row.get("department_code"),
            "department_name": row.get("department_name"),
            "program_code": row.get("profile_code") or row.get("program_code"),
            "program_name": row.get("profile_name") or row.get("program_name"),
            "catalog_description": row.get("description"),
        }
        program_key = row.get("profile_key") or row.get("program_key")
    elif subject_type == "curriculum_item":
        subject_name = row.get("discipline")
        context = {
            "direction_code": row.get("direction_code"),
            "direction_name": row.get("direction_name"),
            "department": row.get("department"),
            "faculty": row.get("faculty"),
            "program_code": row.get("program_profile_code") or row.get("program_code"),
            "program_name": row.get("program_profile"),
            "semester": row.get("semester"),
            "control_form": row.get("assessment_type"),
        }
        program_key = row.get("program_key")
    else:
        raise JevClassificationError("unsupported subject type")
    if not isinstance(subject_name, str) or not subject_name.strip():
        raise JevClassificationError(f"{subject_type} {external_key!r} has no subject name")
    context = {key: value for key, value in context.items() if value not in (None, "")}
    input_record = {
        "subject_type": subject_type,
        "subject_external_key": external_key,
        "subject_name": subject_name.strip(),
        "context": context,
    }
    return {
        **input_record,
        "program_key": program_key,
        "input_sha256": _sha256(_canonical_json(input_record).encode("utf-8")),
    }


def _read_partial_results(
    output_path: Path, manifest_path: Path, expected: dict[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    if not output_path.exists() and not manifest_path.exists():
        return {}
    if not output_path.exists() or not manifest_path.exists():
        raise JevClassificationError(
            "resume files are incomplete; move both files aside before restarting"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise JevClassificationError("cannot read classification run manifest") from error
    for expected_key, value in expected.items():
        if manifest.get(expected_key) != value:
            raise JevClassificationError(f"resume manifest does not match current {expected_key}")
    completed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_jsonl(output_path):
        subject_type = row.get("subject_type")
        subject_external_key = row.get("subject_external_key")
        if not isinstance(subject_type, str) or not isinstance(subject_external_key, str):
            raise JevClassificationError("classification checkpoint has invalid subject keys")
        identity = (subject_type, subject_external_key)
        if identity in completed or row.get("category_code") not in CATEGORY_NAMES:
            raise JevClassificationError(
                "classification checkpoint contains duplicate or invalid rows"
            )
        completed[identity] = row
    return completed


def _write_manifest(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_canonical_json(document) + "\n", encoding="utf-8")
    temporary.replace(path)


def _classify_batch(
    batch: list[dict[str, Any]], api_key: str, timeout_seconds: int
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    state_records = []
    questions: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(batch):
        question_key = f"subject_{index:03d}"
        state_records.append(
            {
                "question_key": question_key,
                "subject_type": row["subject_type"],
                "subject_external_key": row["subject_external_key"],
                "subject_name": row["subject_name"],
                "context": row["context"],
            }
        )
        questions[question_key] = {
            "type": "choice",
            "instructions": QUESTION_INSTRUCTIONS.format(question_key=question_key),
            "criteria": CHOICE_CRITERIA,
        }
    request_body = {
        "model": MODEL_ID,
        "state": {"taxonomy": TAXONOMY_STATE, "source_records": state_records},
        "questions": questions,
    }
    request = urllib.request.Request(
        API_URL,
        data=_canonical_json(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "andromeda-academic-data/subject-classification-v1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # Do not relay the request headers, body, or provider response (which can
        # include account identifiers) into logs.
        raise JevClassificationError(f"Jev API returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
        raise JevClassificationError(f"Jev API request failed ({type(error).__name__})") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise JevClassificationError("Jev API response did not contain typed answers")
    answers = payload["answers"]
    if set(answers) != set(questions):
        raise JevClassificationError("Jev response did not answer every per-record question")
    model_version = payload.get("model")
    if not isinstance(model_version, str) or not model_version:
        raise JevClassificationError("Jev response did not identify the resolved model version")
    usage = payload.get("usage") or {}
    if not isinstance(usage, dict):
        raise JevClassificationError("Jev usage block is malformed")
    return answers, model_version, usage


def classify_bundle(
    bundle_path: Path,
    output_path: Path,
    *,
    release_digest: str,
    batch_size: int = 16,
    timeout_seconds: int = 90,
    retry_count: int = 5,
) -> dict[str, Any]:
    if not 1 <= batch_size <= 32:
        raise JevClassificationError("batch size must be in the range 1..32")
    if len(release_digest) != 64 or any(c not in "0123456789abcdef" for c in release_digest):
        raise JevClassificationError("release digest must be a 64-character lowercase SHA-256")
    api_key = os.getenv("POLZA_AI_API_KEY")
    if not api_key:
        raise JevClassificationError("POLZA_AI_API_KEY is not set")
    subjects, bundle_digest = _load_subjects(bundle_path)
    unique_keys = {(row["subject_type"], row["subject_external_key"]) for row in subjects}
    if len(unique_keys) != len(subjects):
        raise JevClassificationError("the source bundle contains duplicate subject external keys")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output_path.with_suffix(".manifest.json")
    expected_manifest = {
        "source_input_sha256": bundle_digest,
        "source_release_digest": release_digest,
        "taxonomy_key": TAXONOMY_KEY,
        "taxonomy_version": TAXONOMY_VERSION,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256(),
        "requested_model": MODEL_ID,
        "expected_records": len(subjects),
    }
    completed = _read_partial_results(output_path, manifest_path, expected_manifest)
    manifest: dict[str, Any] = {
        **expected_manifest,
        "provider": PROVIDER,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "completed_records": len(completed),
        "failed_records": 0,
        "request_count": 0,
        "total_cost_rub": 0.0,
        "usage_totals": {},
    }
    if completed:
        # A resumed manifest carries the already incurred billing and request
        # totals; output rows intentionally contain just per-subject answers.
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            {
                "started_at": old.get("started_at", manifest["started_at"]),
                "request_count": old.get("request_count", 0),
                "total_cost_rub": old.get("total_cost_rub", 0.0),
                "usage_totals": old.get("usage_totals", {}),
                "failed_response_count": old.get("failed_response_count", 0),
                "failed_response_cost_rub": old.get("failed_response_cost_rub", 0.0),
                "failed_response_usage_totals": old.get("failed_response_usage_totals", {}),
                "failed_transport_attempt_count": old.get("failed_transport_attempt_count", 0),
                "uncaptured_prior_response_count": old.get("uncaptured_prior_response_count", 0),
                "uncaptured_prior_response_note": old.get("uncaptured_prior_response_note"),
            }
        )
    _write_manifest(manifest_path, manifest)

    pending = [
        row
        for row in subjects
        if (row["subject_type"], row["subject_external_key"]) not in completed
    ]
    total_batches = (len(pending) + batch_size - 1) // batch_size
    for batch_number, start in enumerate(range(0, len(pending), batch_size), 1):
        batch = pending[start : start + batch_size]
        attempt = 0
        while True:
            response_received = False
            usage: dict[str, Any] = {}
            try:
                answers, model_version, usage = _classify_batch(batch, api_key, timeout_seconds)
                response_received = True
                validated_results = [
                    _validate_choice_answer(answers[f"subject_{index:03d}"])
                    for index in range(len(batch))
                ]
                break
            except JevClassificationError as error:
                if response_received:
                    manifest["failed_response_count"] = manifest.get("failed_response_count", 0) + 1
                    cost = usage.get("cost_rub")
                    if isinstance(cost, (int, float)):
                        manifest["total_cost_rub"] += float(cost)
                        manifest["failed_response_cost_rub"] = manifest.get(
                            "failed_response_cost_rub", 0.0
                        ) + float(cost)
                    for key, value in usage.items():
                        if isinstance(value, (int, float)):
                            failed_usage = manifest.setdefault("failed_response_usage_totals", {})
                            failed_usage[key] = failed_usage.get(key, 0) + value
                    _write_manifest(manifest_path, manifest)
                else:
                    manifest["failed_transport_attempt_count"] = (
                        manifest.get("failed_transport_attempt_count", 0) + 1
                    )
                    _write_manifest(manifest_path, manifest)
                attempt += 1
                if attempt > retry_count:
                    manifest.update(
                        {
                            "status": "failed",
                            "failed_records": len(batch),
                            "last_error": str(error),
                            "failed_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    _write_manifest(manifest_path, manifest)
                    raise
                time.sleep(min(60, 2**attempt))
        prior_versions = set(manifest.get("resolved_model_versions", []))
        if prior_versions and model_version not in prior_versions:
            manifest.update(
                {
                    "status": "failed",
                    "failed_records": len(batch),
                    "last_error": "resolved Jev model version changed during this run",
                    "failed_at": datetime.now(UTC).isoformat(),
                }
            )
            _write_manifest(manifest_path, manifest)
            raise JevClassificationError(
                "resolved Jev model version changed; refusing to mix versions in one run"
            )
        results = []
        for index, row in enumerate(batch):
            result = validated_results[index]
            results.append(
                {
                    "subject_type": row["subject_type"],
                    "subject_external_key": row["subject_external_key"],
                    "subject_name": row["subject_name"],
                    "input_sha256": row["input_sha256"],
                    "category_code": result["category_code"],
                    "category_name": CATEGORY_NAMES[result["category_code"]],
                    "confidence": result["confidence"],
                    "probabilities": result["probabilities"],
                    "jev_answer": result["jev_answer"],
                    "review_reasons": result["review_reasons"],
                    "resolved_model_version": model_version,
                }
            )
        # Write the whole response batch before publishing its checkpoint.
        with output_path.open("a", encoding="utf-8", newline="") as output:
            for result in results:
                output.write(_canonical_json(result) + "\n")
            output.flush()
            os.fsync(output.fileno())
        manifest["request_count"] += 1
        manifest["completed_records"] += len(results)
        cost = usage.get("cost_rub")
        if isinstance(cost, (int, float)):
            manifest["total_cost_rub"] += float(cost)
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                manifest["usage_totals"][key] = manifest["usage_totals"].get(key, 0) + value
        manifest["resolved_model_versions"] = sorted(
            set(manifest.get("resolved_model_versions", [])) | {model_version}
        )
        manifest["updated_at"] = datetime.now(UTC).isoformat()
        _write_manifest(manifest_path, manifest)
        print(
            f"batch {batch_number}/{total_batches}: "
            f"{manifest['completed_records']}/{len(subjects)} classified; "
            f"Jev cost {manifest['total_cost_rub']:.8f} RUB",
            flush=True,
        )

    if manifest["completed_records"] != len(subjects):
        raise JevClassificationError("classification coverage is incomplete")
    _add_conflict_review_flags(output_path)
    result_bytes = output_path.read_bytes()
    manifest.update(
        {
            "status": "complete",
            "completed_at": datetime.now(UTC).isoformat(),
            "result_sha256": _sha256(result_bytes),
            "result_records": len(subjects),
            "failed_records": 0,
        }
    )
    _write_manifest(manifest_path, manifest)
    return manifest


def _validate_choice_answer(answer: Any) -> dict[str, Any]:
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise JevClassificationError("Jev returned a non-choice answer")
    code = answer.get("choice")
    confidence = answer.get("confidence")
    probabilities = answer.get("probabilities")
    if code not in CATEGORY_NAMES:
        raise JevClassificationError("Jev selected a category outside the user taxonomy")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise JevClassificationError("Jev returned invalid confidence")
    if not isinstance(probabilities, dict) or set(probabilities) != set(CATEGORY_NAMES):
        raise JevClassificationError("Jev did not return probabilities for all 16 categories")
    if any(
        not isinstance(value, (int, float)) or not 0 <= value <= 1
        for value in probabilities.values()
    ):
        raise JevClassificationError("Jev returned invalid category probabilities")
    if abs(sum(probabilities.values()) - 1.0) > 0.015:
        raise JevClassificationError("Jev category probabilities do not sum to approximately one")
    probability_values = cast(dict[str, float], probabilities)
    highest_probability = max(probability_values.values())
    reasons = []
    if probability_values[code] < highest_probability - 1e-8:
        reasons.append("jev_choice_not_highest_probability")
    ordered = sorted(probabilities.values(), reverse=True)
    if confidence < CONFIDENCE_REVIEW_THRESHOLD:
        reasons.append(f"jev_confidence_below_{CONFIDENCE_REVIEW_THRESHOLD:.2f}")
    if len(ordered) > 1 and ordered[0] - ordered[1] < PROBABILITY_MARGIN_REVIEW_THRESHOLD:
        reasons.append("close_category_probabilities")
    return {
        "category_code": code,
        "confidence": float(confidence),
        "probabilities": {key: float(value) for key, value in probabilities.items()},
        "jev_answer": answer,
        "review_reasons": sorted(reasons),
    }


def _add_conflict_review_flags(output_path: Path) -> None:
    rows = _read_jsonl(output_path)
    assignments: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        normalized_name = " ".join(row["subject_name"].casefold().split())
        assignments[(row["subject_type"], normalized_name)].add(row["category_code"])
    with output_path.open("w", encoding="utf-8", newline="") as output:
        for row in rows:
            reasons = list(row.get("review_reasons", []))
            normalized_name = " ".join(row["subject_name"].casefold().split())
            if len(assignments[(row["subject_type"], normalized_name)]) > 1:
                reasons.append("same_name_records_received_different_jev_categories")
            row["review_reasons"] = sorted(set(reasons))
            output.write(_canonical_json(row) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-digest", required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=5)
    arguments = parser.parse_args(argv)
    try:
        manifest = classify_bundle(
            arguments.bundle,
            arguments.output,
            release_digest=arguments.release_digest,
            batch_size=arguments.batch_size,
            timeout_seconds=arguments.timeout,
            retry_count=arguments.retries,
        )
    except JevClassificationError as error:
        print(f"classification failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "classified_records": manifest["completed_records"],
                "requests": manifest["request_count"],
                "cost_rub": manifest["total_cost_rub"],
                "resolved_model_versions": manifest.get("resolved_model_versions", []),
                "result_sha256": manifest.get("result_sha256"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
