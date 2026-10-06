"""Load validated Jev facts onto their typed rows in the active data release."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.engine import Engine

from academic_data_service.classification.jev import (
    JevClassificationError,
    _load_subjects,
    _read_jsonl,
)
from academic_data_service.classification.taxonomy import (
    CATEGORY_NAMES,
    MODEL_ID,
    PROMPT_VERSION,
    PROVIDER,
    TAXONOMY_KEY,
    TAXONOMY_VERSION,
    prompt_sha256,
)
from academic_data_service.infrastructure.database import (
    catalog_models as _catalog_models,  # noqa: F401
)
from academic_data_service.infrastructure.database import models as _lifecycle_models  # noqa: F401
from academic_data_service.infrastructure.database import (
    subject_classification_models as _subject_classification_models,  # noqa: F401
)
from academic_data_service.infrastructure.database.base import Base
from academic_data_service.infrastructure.database.connection import (
    create_service_engine,
    verify_server_identity,
)
from academic_data_service.settings import load_settings


class ClassificationImportError(RuntimeError):
    """A classification package or target release failed import checks."""


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ClassificationImportError("classification manifest is unreadable") from error
    if not isinstance(document, dict):
        raise ClassificationImportError("classification manifest must be a JSON object")
    return document


def _validate_package(
    bundle_path: Path, result_path: Path, manifest_path: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    manifest = _read_manifest(manifest_path)
    required = {
        "status": "complete",
        "taxonomy_key": TAXONOMY_KEY,
        "taxonomy_version": TAXONOMY_VERSION,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256(),
        "requested_model": MODEL_ID,
        "provider": PROVIDER,
        "failed_records": 0,
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            raise ClassificationImportError(f"manifest has unsupported {key}")
    data = result_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest.get("result_sha256"):
        raise ClassificationImportError("classification JSONL SHA-256 does not match manifest")
    if len(manifest.get("resolved_model_versions", [])) != 1:
        raise ClassificationImportError(
            "the Jev model version changed during the classification run"
        )
    subjects, bundle_digest = _load_subjects(bundle_path)
    if bundle_digest != manifest.get("source_input_sha256"):
        raise ClassificationImportError("source bundle contents changed after classification")
    if len(subjects) != manifest.get("expected_records"):
        raise ClassificationImportError(
            "source bundle count does not match the classification manifest"
        )
    source_by_key = {(row["subject_type"], row["subject_external_key"]): row for row in subjects}
    results = _read_jsonl(result_path)
    if len(results) != len(subjects) or manifest.get("completed_records") != len(subjects):
        raise ClassificationImportError("classification coverage is incomplete")
    result_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in results:
        identity = (row.get("subject_type"), row.get("subject_external_key"))
        if identity in result_by_key or identity not in source_by_key:
            raise ClassificationImportError("classification result keys are duplicated or unknown")
        source = source_by_key[identity]
        category_code = row.get("category_code")
        if (
            row.get("subject_name") != source["subject_name"]
            or row.get("input_sha256") != source["input_sha256"]
            or not isinstance(category_code, str)
            or row.get("category_name") != CATEGORY_NAMES.get(category_code)
        ):
            raise ClassificationImportError("a result does not match its source input or taxonomy")
        answer = row.get("jev_answer")
        if not isinstance(answer, dict) or answer.get("choice") != row["category_code"]:
            raise ClassificationImportError(
                "stored Jev answer does not match the selected category"
            )
        if answer.get("probabilities") != row.get("probabilities"):
            raise ClassificationImportError(
                "stored Jev probabilities do not match their normalized copy"
            )
        probabilities = row.get("probabilities")
        if not isinstance(probabilities, dict) or set(probabilities) != set(CATEGORY_NAMES):
            raise ClassificationImportError(
                "result must preserve probabilities for all 16 categories"
            )
        if (
            any(
                not isinstance(score, (int, float)) or not 0 <= score <= 1
                for score in probabilities.values()
            )
            or abs(sum(probabilities.values()) - 1.0) > 0.015
        ):
            raise ClassificationImportError("category probabilities are malformed")
        confidence = row.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
            or answer.get("confidence") != confidence
        ):
            raise ClassificationImportError("JeV confidence is invalid")
        if not isinstance(row.get("review_reasons"), list):
            raise ClassificationImportError("classification review reasons are malformed")
        if row.get("resolved_model_version") != manifest["resolved_model_versions"][0]:
            raise ClassificationImportError("result model version differs from the run manifest")
        result_by_key[identity] = row
    return manifest, subjects, result_by_key


def import_classifications(
    engine: Engine,
    bundle_path: Path,
    result_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    manifest, source_subjects, results = _validate_package(bundle_path, result_path, manifest_path)
    metadata = Base.metadata
    releases = metadata.tables["data_releases"]
    active = metadata.tables["active_data_release"]
    runs = metadata.tables["subject_classification_runs"]
    classifications = metadata.tables["subject_classifications"]

    with engine.begin() as connection:
        release = (
            connection.execute(
                select(
                    releases.c.id,
                    releases.c.source_bundle_sha256,
                    releases.c.release_key,
                    active.c.release_id,
                )
                .select_from(active.join(releases, active.c.release_id == releases.c.id))
                .where(active.c.slot_key == "active")
            )
            .mappings()
            .one_or_none()
        )
        if release is None:
            raise ClassificationImportError("the target database has no active data release")
        release_id = release["release_id"]
        source_digest = release["source_bundle_sha256"]
        if source_digest != manifest.get("source_release_digest"):
            raise ClassificationImportError(
                "classified source release is not the active database release"
            )

        subjects_by_type: dict[str, list[dict[str, Any]]] = {
            "catalog_course": [],
            "curriculum_item": [],
        }
        for subject in source_subjects:
            subjects_by_type[subject["subject_type"]].append(subject)
        resolved_ids: dict[tuple[str, str], Any] = {}
        for subject_type, rows in subjects_by_type.items():
            table_name = (
                "catalog_courses" if subject_type == "catalog_course" else "curriculum_items"
            )
            table = metadata.tables[table_name]
            name_column = (
                table.c.name if subject_type == "catalog_course" else table.c.discipline_name
            )
            db_rows = connection.execute(
                select(table.c.id, table.c.external_key, name_column.label("subject_name")).where(
                    table.c.release_id == release_id
                )
            ).mappings()
            by_key = {row["external_key"]: row for row in db_rows}
            input_keys = {row["subject_external_key"] for row in rows}
            if input_keys != set(by_key):
                raise ClassificationImportError(
                    f"{table_name} source keys do not exactly match active release rows"
                )
            for source in rows:
                db_row = by_key[source["subject_external_key"]]
                if db_row["subject_name"] != source["subject_name"]:
                    raise ClassificationImportError(
                        "source title differs from the active release for "
                        f"{source['subject_external_key']}"
                    )
                key = (subject_type, source["subject_external_key"])
                resolved_ids[key] = db_row["id"]

        run_key = f"classification:{TAXONOMY_KEY}:{TAXONOMY_VERSION}:{manifest['result_sha256']}"
        existing = (
            connection.execute(
                select(runs.c.id, runs.c.result_sha256, runs.c.classified_count).where(
                    runs.c.release_id == release_id, runs.c.external_key == run_key
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if existing["result_sha256"] != manifest["result_sha256"]:
                raise ClassificationImportError(
                    "classification run key conflicts with stored facts"
                )
            return {
                "status": "already_imported",
                "release_key": release["release_key"],
                "run_key": run_key,
                "classified_count": existing["classified_count"],
                "result_sha256": existing["result_sha256"],
            }

        run_id = uuid4()
        version = manifest["resolved_model_versions"][0]
        usage = {"reported": manifest.get("usage_totals") or {}}
        if manifest.get("uncaptured_prior_response_count"):
            usage["uncaptured_prior_response_count"] = manifest["uncaptured_prior_response_count"]
            usage["uncaptured_prior_response_note"] = manifest.get("uncaptured_prior_response_note")
        run_row = {
            "id": run_id,
            "release_id": release_id,
            "external_key": run_key,
            "taxonomy_key": TAXONOMY_KEY,
            "taxonomy_version": TAXONOMY_VERSION,
            "provider": PROVIDER,
            "requested_model": MODEL_ID,
            "resolved_model_version": version,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": prompt_sha256(),
            "source_bundle_sha256": source_digest,
            "source_input_sha256": manifest["source_input_sha256"],
            "result_sha256": manifest["result_sha256"],
            "status": "complete",
            "expected_count": len(results),
            "classified_count": len(results),
            "failed_count": 0,
            "cost_rub": Decimal(str(manifest["total_cost_rub"]))
            if manifest.get("total_cost_rub") is not None
            else None,
            "usage": usage,
            "started_at": datetime.fromisoformat(manifest["started_at"]),
            "completed_at": datetime.fromisoformat(manifest["completed_at"]),
        }
        connection.execute(insert(runs).values(run_row))
        category_counts: Counter[str] = Counter()
        output_rows = []
        for source in source_subjects:
            identity = (source["subject_type"], source["subject_external_key"])
            result = results[identity]
            category_code = result["category_code"]
            category_counts[category_code] += 1
            answer = result["jev_answer"]
            review_status = "needs_review" if result["review_reasons"] else "classified"
            output_rows.append(
                {
                    "id": uuid4(),
                    "release_id": release_id,
                    "run_id": run_id,
                    "catalog_course_id": resolved_ids[identity]
                    if source["subject_type"] == "catalog_course"
                    else None,
                    "curriculum_item_id": resolved_ids[identity]
                    if source["subject_type"] == "curriculum_item"
                    else None,
                    "taxonomy_key": TAXONOMY_KEY,
                    "taxonomy_version": TAXONOMY_VERSION,
                    "category_code": category_code,
                    "input_sha256": source["input_sha256"],
                    "confidence": Decimal(str(result["confidence"])),
                    "probabilities": result["probabilities"],
                    "jev_answer": answer,
                    "review_reasons": result["review_reasons"],
                    "review_status": review_status,
                }
            )
        for offset in range(0, len(output_rows), 500):
            connection.execute(insert(classifications), output_rows[offset : offset + 500])
        return {
            "status": "imported",
            "release_key": release["release_key"],
            "run_key": run_key,
            "classified_count": len(output_rows),
            "catalog_course_count": len(subjects_by_type["catalog_course"]),
            "curriculum_item_count": len(subjects_by_type["curriculum_item"]),
            "needs_review_count": sum(
                1 for row in output_rows if row["review_status"] == "needs_review"
            ),
            "category_counts": dict(sorted(category_counts.items())),
            "cost_rub": manifest.get("total_cost_rub"),
            "result_sha256": manifest["result_sha256"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    arguments = parser.parse_args(argv)
    engine = None
    try:
        settings = load_settings()
        engine = create_service_engine(settings)
        with engine.connect() as connection:
            identity = verify_server_identity(connection, settings)
            if identity["database_name"] != "academic_data_2026":
                raise ClassificationImportError("refusing to import outside academic_data_2026")
        report = import_classifications(
            engine, arguments.bundle, arguments.results, arguments.manifest
        )
    except (ClassificationImportError, JevClassificationError, ValueError, OSError) as error:
        print(f"classification import failed: {error}", file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
