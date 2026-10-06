from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from andromeda.ingestion.universities.bmstu.parser.campaign_2026.catalog_view import build_visualizer
from andromeda.ingestion.universities.bmstu.parser.campaign_2026.common import clean_text, jsonl_write, normalize_code
from andromeda.ingestion.universities.bmstu.parser.campaign_2026.curricula.parser import parse_curriculum_document


MANIFEST_PATH = Path(__file__).with_name("confirmed_catalog_plan_links.json")
UNVERIFIED_STATUS = "plan_header_profile_code_unverified_or_mismatched"
USER_CONFIRMED_STATUS = "parsed_via_user_confirmed_catalog_link"
IDENTITY_VERIFIED_STATUS = "parsed_and_profile_identity_verified"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _normalized_title(value: object) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", " ", clean_text(value).casefold()).strip()


def _name_key(value: object) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", clean_text(value).casefold())


def _identity_check(
    parsed: dict[str, Any],
    program: dict[str, Any],
    profile_code_counts: Counter[str],
    profile_code_name_counts: Counter[tuple[str, str]],
) -> bool:
    if normalize_code(parsed.get("header_profile_code")) != program["code"]:
        return False
    plan_name = parsed.get("profile_name_in_plan")
    expected_name = _normalized_title(program["name"])
    if plan_name and _normalized_title(plan_name) != expected_name:
        return False
    if not plan_name and profile_code_counts[program["code"]] > 1:
        return False
    if profile_code_name_counts[(program["code"], expected_name)] > 1:
        department_text = _name_key(parsed.get("department_in_plan") or "")
        department_code = _name_key(program.get("department_code") or "")
        if not department_text or department_code not in department_text:
            return False
    return True


def _source_bytes(bundle_root: Path, artifact: dict[str, Any]) -> bytes:
    raw_path = artifact.get("raw_path")
    if not raw_path:
        raise ValueError(f"source file is absent from the bundle: {artifact.get('requested_url')}")
    path = bundle_root / raw_path
    if not path.is_file():
        raise FileNotFoundError(path)
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != artifact.get("sha256"):
        raise ValueError(f"source checksum mismatch: {artifact.get('requested_url')}")
    return body


def _validate_and_package(bundle_root: Path, report: dict[str, Any], manifest_links: list[dict[str, Any]]) -> Path:
    data_dir = bundle_root / "data"
    data_files = sorted(data_dir.glob("*.jsonl"))
    errors: list[str] = []
    all_rows: dict[str, list[dict[str, Any]]] = {}
    entity_keys: set[str] = set()
    duplicate_keys: set[str] = set()
    for path in data_files:
        try:
            rows = _read_jsonl(path)
        except Exception as exc:
            errors.append(f"jsonl_read_error:{path.name}:{type(exc).__name__}")
            continue
        all_rows[path.stem] = rows
        local: set[str] = set()
        for row in rows:
            key = row.get("external_key")
            if not isinstance(key, str) or not key:
                errors.append(f"missing_external_key:{path.name}")
                continue
            if key in local or key in entity_keys:
                duplicate_keys.add(key)
            local.add(key)
            entity_keys.add(key)
    if duplicate_keys:
        errors.append(f"duplicate_external_keys:{len(duplicate_keys)}")

    plans = {row["external_key"]: row for row in all_rows.get("study_plans", [])}
    programs = {row["external_key"]: row for row in all_rows.get("educational_programs", [])}
    items = all_rows.get("curriculum_items", [])
    plan_reference_errors = 0
    for plan in plans.values():
        if plan.get("program_key") not in programs:
            plan_reference_errors += 1
    item_reference_errors = 0
    for item in items:
        plan = plans.get(item.get("curriculum_key"))
        if not plan or item.get("program_key") != plan.get("program_key"):
            item_reference_errors += 1

    relationships = all_rows.get("relationships", [])
    unresolved_relationships = [
        row.get("external_key") for row in relationships
        if row.get("source_key") not in entity_keys or row.get("target_key") not in entity_keys
    ]
    if unresolved_relationships:
        errors.append(f"unresolved_relationship_endpoints:{len(unresolved_relationships)}")
    if plan_reference_errors:
        errors.append(f"study_plan_program_reference_errors:{plan_reference_errors}")
    if item_reference_errors:
        errors.append(f"curriculum_item_reference_errors:{item_reference_errors}")

    artifacts = _read_jsonl(bundle_root / "source_artifacts.jsonl")
    artifact_keys = {row.get("source_key") for row in artifacts if row.get("source_key")}
    source_checksum_errors = 0
    saved_artifacts = 0
    for artifact in artifacts:
        if not artifact.get("raw_path"):
            continue
        saved_artifacts += 1
        path = bundle_root / artifact["raw_path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256"):
            source_checksum_errors += 1
    if source_checksum_errors:
        errors.append(f"source_checksum_errors:{source_checksum_errors}")

    requirement_nodes = Counter({"AND": 0, "OR": 0, "AT_LEAST": 0})
    invalid_requirement_trees = 0
    for requirement in all_rows.get("admission_exam_requirements", []):
        def visit(node: Any) -> bool:
            if not isinstance(node, dict):
                return False
            if "exam" in node:
                return isinstance(node["exam"], dict) and bool(node["exam"].get("subject_code"))
            operator = node.get("operator")
            children = node.get("children")
            if operator not in {"AND", "OR", "AT_LEAST"} or not isinstance(children, list) or not children:
                return False
            requirement_nodes[operator] += 1
            if operator == "AT_LEAST" and not isinstance(node.get("min_count"), int):
                return False
            return all(visit(child) for child in children)
        if not visit(requirement.get("requirement_tree")):
            invalid_requirement_trees += 1
    if invalid_requirement_trees:
        errors.append(f"invalid_requirement_trees:{invalid_requirement_trees}")

    statuses = Counter(plan.get("status", "unknown") for plan in plans.values())
    confirmed_keys = {f"study_plan:{link['program_external_key']}" for link in manifest_links}
    confirmed_plans = [plans[key] for key in confirmed_keys if key in plans]
    confirmed_link_errors = sum(
        plan.get("status") != USER_CONFIRMED_STATUS
        or plan.get("profile_link_association", {}).get("basis") != "user_confirmed_official_profile_card_link"
        for plan in confirmed_plans
    )
    confirmed_item_rows = sum(1 for item in items if item.get("curriculum_key") in confirmed_keys)
    if len(confirmed_plans) != len(manifest_links) or confirmed_link_errors:
        errors.append(f"confirmed_plan_links_not_resolved:{confirmed_link_errors + abs(len(manifest_links) - len(confirmed_plans))}")
    review_path = bundle_root / "manual_review.csv"
    with review_path.open("r", encoding="utf-8-sig", newline="") as stream:
        review_rows = list(csv.DictReader(stream))
    reviewed_record_keys = {row.get("record_key") for row in review_rows if row.get("record_key")}
    reference_issues: list[tuple[str | None, str]] = []

    def iter_key_references(value: Any) -> list[str]:
        refs: list[str] = []
        if isinstance(value, dict):
            for name, child in value.items():
                if name.endswith("_key") and name != "external_key" and isinstance(child, str) and child:
                    refs.append(child)
                elif name.endswith("_keys") and isinstance(child, list):
                    refs.extend(key for key in child if isinstance(key, str) and key)
                refs.extend(iter_key_references(child))
        elif isinstance(value, list):
            for child in value:
                refs.extend(iter_key_references(child))
        return refs

    for rows in all_rows.values():
        for row in rows:
            for ref in iter_key_references(row):
                if ref not in entity_keys and ref not in artifact_keys:
                    reference_issues.append((row.get("external_key"), ref))
    unreviewed_references = [item for item in reference_issues if item[0] not in reviewed_record_keys]
    if unreviewed_references:
        errors.append(f"unreviewed_key_references:{len(unreviewed_references)}")

    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["counts"].update({
        "curriculum_items": len(items),
        "relationships": len(relationships),
        "study_plans": len(plans),
        "source_artifacts": len(artifacts),
    })
    report["validation"].update({
        "jsonl_files": len(data_files),
        "relationships_checked": len(relationships),
        "unresolved_relationship_endpoints": len(unresolved_relationships),
        "record_external_keys_unique": not duplicate_keys,
        "duplicate_external_key_count": len(duplicate_keys),
        "source_artifact_keys_unique": len(artifact_keys) == len(artifacts),
        "unresolved_key_references": len(reference_issues),
        "unreviewed_key_references": len(unreviewed_references),
        "study_plans_checked": len(plans),
        "study_plan_program_reference_errors": plan_reference_errors,
        "curriculum_items_checked": len(items),
        "curriculum_item_reference_errors": item_reference_errors,
        "confirmed_catalog_links_checked": len(confirmed_plans),
        "confirmed_catalog_link_item_rows": confirmed_item_rows,
        "requirements_checked": len(all_rows.get("admission_exam_requirements", [])),
        "requirement_tree_operator_nodes": dict(requirement_nodes),
        "invalid_requirement_trees": invalid_requirement_trees,
        "sha256_raw_files_checked": saved_artifacts,
        "source_checksum_errors": source_checksum_errors,
        "source_artifact_manifest_records": len(artifacts),
        "manual_review_rows": len(review_rows),
        "errors": errors,
    })
    report["coverage"].update({
        "profile_specific_plans_parsed": statuses.get(IDENTITY_VERIFIED_STATUS, 0) + statuses.get(USER_CONFIRMED_STATUS, 0),
        "profile_specific_plans_identity_verified": statuses.get(IDENTITY_VERIFIED_STATUS, 0),
        "profile_specific_plans_user_confirmed_by_catalog_link": statuses.get(USER_CONFIRMED_STATUS, 0),
        "profile_specific_plans_unavailable_or_unverified": len(plans) - statuses.get(IDENTITY_VERIFIED_STATUS, 0) - statuses.get(USER_CONFIRMED_STATUS, 0),
        "study_plan_status_counts": dict(statuses),
        "requirement_tree_operator_nodes": dict(requirement_nodes),
    })
    report["manual_review_rows"] = len(review_rows)
    report["counts"]["manual_review"] = len(review_rows)
    report["counts"]["jsonl_records_total"] = sum(len(rows) for rows in all_rows.values())
    report_path = bundle_root / "validation_report.json"
    archive_path = bundle_root.parent / "andromeda_bmstu_2026_bundle.zip"

    def write_archive() -> tuple[int, bool]:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(bundle_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle_root.parent))
        with zipfile.ZipFile(archive_path, "r") as archive:
            return len(archive.namelist()), archive.testzip() is None

    report["validation"]["zip_members"] = sum(1 for path in bundle_root.rglob("*") if path.is_file())
    report["validation"]["zip_integrity_ok"] = False
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zip_members, zip_ok = write_archive()
    report["validation"]["zip_members"] = zip_members
    report["validation"]["zip_integrity_ok"] = zip_ok
    if not zip_ok:
        report["validation"]["errors"].append("zip_integrity_failed")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zip_members, zip_ok = write_archive()
    if not zip_ok or zip_members != report["validation"]["zip_members"]:
        raise ValueError("final archive failed integrity or membership validation")
    return archive_path


def reconcile(bundle_root: Path) -> dict[str, Any]:
    bundle_root = bundle_root.resolve()
    data_dir = bundle_root / "data"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    links = manifest.get("links", [])
    if not links:
        raise ValueError("confirmation manifest has no links")
    if len({link.get("program_external_key") for link in links}) != len(links):
        raise ValueError("confirmation manifest contains duplicate program keys")

    study_plans = _read_jsonl(data_dir / "study_plans.jsonl")
    curriculum_items = _read_jsonl(data_dir / "curriculum_items.jsonl")
    programs = {item["external_key"]: item for item in _read_jsonl(data_dir / "educational_programs.jsonl")}
    relationships = _read_jsonl(data_dir / "relationships.jsonl")
    artifacts = _read_jsonl(bundle_root / "source_artifacts.jsonl")
    artifact_by_url = {item["requested_url"]: item for item in artifacts}
    if len(artifact_by_url) != len(artifacts):
        raise ValueError("source artifact manifest has duplicate requested URLs")

    plan_by_key = {item["external_key"]: item for item in study_plans}
    if len(plan_by_key) != len(study_plans):
        raise ValueError("study plan records contain duplicate external keys")
    profile_code_counts = Counter(program["code"] for program in programs.values())
    profile_code_name_counts = Counter((program["code"], _normalized_title(program["name"])) for program in programs.values())
    profiles_by_link: dict[str, list[str]] = {}
    for link in links:
        profiles_by_link.setdefault(link["study_plan_url"], []).append(link["program_external_key"])

    affected_plan_keys: set[str] = set()
    added_items: list[dict[str, Any]] = []
    header_code_relations: Counter[str] = Counter()
    download_urls: Counter[str] = Counter()
    for link in links:
        program_key = link["program_external_key"]
        program = programs.get(program_key)
        plan = plan_by_key.get(f"study_plan:{program_key}")
        if not program or not plan:
            raise ValueError(f"program or plan record is missing for confirmed link: {program_key}")
        if (
            program.get("code") != link.get("profile_code")
            or program.get("source_url") != link.get("catalog_card_url")
            or program.get("study_plan_url") != link.get("study_plan_url")
            or plan.get("program_key") != program_key
            or plan.get("study_plan_url") != link.get("study_plan_url")
        ):
            raise ValueError(f"confirmed link no longer matches its exact catalog card: {program_key}")
        if plan.get("status") not in {UNVERIFIED_STATUS, USER_CONFIRMED_STATUS}:
            raise ValueError(f"unexpected status for confirmed plan {plan['external_key']}: {plan.get('status')}")

        share_artifact = artifact_by_url.get(link["study_plan_url"])
        if not share_artifact:
            raise ValueError(f"captured official catalog link is missing: {link['study_plan_url']}")
        share_url = share_artifact.get("final_url") or link["study_plan_url"]
        metadata_url = "https://cloud-api.yandex.net/v1/disk/public/resources?public_key=" + quote(share_url.split("?", 1)[0], safe="")
        metadata_artifact = artifact_by_url.get(metadata_url)
        if not metadata_artifact:
            raise ValueError(f"captured public-resource metadata is missing: {metadata_url}")
        metadata = json.loads(_source_bytes(bundle_root, metadata_artifact).decode("utf-8-sig"))
        direct_urls: list[str] = []
        if isinstance(metadata.get("file"), str):
            direct_urls.append(metadata["file"])
        embedded = metadata.get("_embedded")
        for item in embedded.get("items", []) if isinstance(embedded, dict) else []:
            if isinstance(item, dict) and isinstance(item.get("file"), str):
                direct_urls.append(item["file"])
        direct_urls = list(dict.fromkeys(direct_urls))
        if len(direct_urls) != 1:
            raise ValueError(f"expected one official plan file for {link['study_plan_url']}, found {len(direct_urls)}")
        document_artifact = artifact_by_url.get(direct_urls[0])
        if not document_artifact:
            raise ValueError(f"captured plan file is missing: {direct_urls[0]}")
        body = _source_bytes(bundle_root, document_artifact)
        parsed = parse_curriculum_document(
            body,
            content_type=document_artifact.get("content_type"),
            final_url=document_artifact.get("final_url") or direct_urls[0],
            share_url=link["study_plan_url"],
            profile=program,
            retrieved_at=document_artifact["retrieved_at"],
        )
        if parsed.get("error") or not parsed.get("items"):
            raise ValueError(f"plan parser did not extract curriculum rows for {program_key}: {parsed.get('error')}")

        identity_verified = _identity_check(parsed, program, profile_code_counts, profile_code_name_counts)
        header_code = normalize_code(parsed.get("header_profile_code"))
        code_relation = "matches" if header_code == program["code"] else "differs" if header_code else "not_extracted"
        header_code_relations[code_relation] += 1
        download_url = document_artifact.get("final_url") or direct_urls[0]
        download_urls[download_url] += 1
        shared_profile_keys = sorted(profiles_by_link[link["study_plan_url"]])
        plan.update({
            "profile_code": program["code"],
            "source_version": None,
            "start_year": parsed.get("education_year"),
            "education_year": parsed.get("education_year"),
            "duration": parsed.get("duration"),
            "study_form": parsed.get("study_form"),
            "header_profile_code": parsed.get("header_profile_code"),
            "profile_name_in_plan": parsed.get("profile_name_in_plan"),
            "header_code_relation": code_relation,
            "profile_identity_check": "passed" if identity_verified else "not_confirmed_by_file_header",
            "semester_count": parsed.get("semester_count"),
            "semester_totals": parsed.get("semester_totals"),
            "overall_astronomical": parsed.get("overall_astronomical"),
            "overall_academic": parsed.get("overall_academic"),
            "status": IDENTITY_VERIFIED_STATUS if identity_verified else USER_CONFIRMED_STATUS,
            "document_url": document_artifact["requested_url"],
            "download_url": download_url,
            "source_url": link["study_plan_url"],
            "source_artifact_keys": [share_artifact["source_key"], metadata_artifact["source_key"], document_artifact["source_key"]],
            "profile_link_association": {
                "basis": "user_confirmed_official_profile_card_link",
                "confirmed_by": "user",
                "confirmed_on": manifest["confirmed_on"],
                "catalog_card_url": link["catalog_card_url"],
            },
            "shared_catalog_link_profile_keys": shared_profile_keys if len(shared_profile_keys) > 1 else [],
            "error": parsed.get("error"),
        })
        affected_plan_keys.add(plan["external_key"])
        for item_no, item in enumerate(parsed["items"], start=1):
            if not isinstance(item, dict):
                continue
            added_items.append({
                "external_key": f"curriculum_item:{plan['external_key']}:row:{item_no}",
                "curriculum_key": plan["external_key"],
                "program_key": program_key,
                "source_url": link["study_plan_url"],
                **item,
            })

    curriculum_items = [item for item in curriculum_items if item.get("curriculum_key") not in affected_plan_keys]
    curriculum_items.extend(added_items)
    plan_by_key = {item["external_key"]: item for item in study_plans}
    for relation in relationships:
        plan = plan_by_key.get(relation.get("target_key"))
        if plan and plan.get("status") == USER_CONFIRMED_STATUS and relation.get("relation_type") == "profile_has_profile_specific_curriculum":
            relation["evidence_kind"] = "user_confirmed_official_profile_card_plan_link"

    jsonl_write(data_dir / "study_plans.jsonl", study_plans)
    jsonl_write(data_dir / "curriculum_items.jsonl", curriculum_items)
    jsonl_write(data_dir / "relationships.jsonl", relationships)
    (bundle_root / "user_confirmed_study_plan_links.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    review_path = bundle_root / "manual_review.csv"
    with review_path.open("r", encoding="utf-8-sig", newline="") as stream:
        review_rows = list(csv.DictReader(stream))
    review_rows = [
        row for row in review_rows
        if not (row.get("issue_type") == "plan_header_profile_code_mismatch" and row.get("record_key") in affected_plan_keys)
    ]
    with review_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["record_key", "issue_type", "source_url", "details"])
        writer.writeheader()
        writer.writerows(review_rows)

    statuses = Counter(plan.get("status", "unknown") for plan in study_plans)
    header_statuses = Counter(plan.get("header_code_relation", "not_recorded") for plan in study_plans if plan.get("status") == USER_CONFIRMED_STATUS)
    user_confirmed_downloads = [plan.get("download_url") for plan in study_plans if plan.get("status") == USER_CONFIRMED_STATUS]
    shared_downloads = len(user_confirmed_downloads) - len(set(user_confirmed_downloads))
    report_path = bundle_root / "validation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["counts"]["curriculum_items"] = len(curriculum_items)
    report["counts"]["relationships"] = len(relationships)
    report["counts"]["study_plans"] = len(study_plans)
    report["coverage"].update({
        "profile_specific_plan_links_attempted": len(study_plans),
        "profile_specific_plans_parsed": statuses.get(IDENTITY_VERIFIED_STATUS, 0) + statuses.get(USER_CONFIRMED_STATUS, 0),
        "profile_specific_plans_identity_verified": statuses.get(IDENTITY_VERIFIED_STATUS, 0),
        "profile_specific_plans_user_confirmed_by_catalog_link": statuses.get(USER_CONFIRMED_STATUS, 0),
        "profile_specific_plans_unavailable_or_unverified": len(study_plans) - statuses.get(IDENTITY_VERIFIED_STATUS, 0) - statuses.get(USER_CONFIRMED_STATUS, 0),
        "study_plan_status_counts": dict(statuses),
        "user_confirmed_plan_header_code_relations": dict(header_statuses),
    })
    report["validation"].update({
        "user_confirmed_link_study_plans": statuses.get(USER_CONFIRMED_STATUS, 0),
        "parsed_study_plans": statuses.get(IDENTITY_VERIFIED_STATUS, 0) + statuses.get(USER_CONFIRMED_STATUS, 0),
        "shared_downloads_from_user_confirmed_catalog_links": shared_downloads,
        "relationships_checked": len(relationships),
    })
    report["manual_review_rows"] = len(review_rows)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = report.get("counts", {})
    header_summary = (
        f"код совпал в {header_statuses.get('matches', 0)} PDF, "
        f"отличался в {header_statuses.get('differs', 0)}, "
        f"не извлёкся в {header_statuses.get('not_extracted', 0)}"
    )
    no_file_count = statuses.get("linked_public_resource_has_no_file", 0)
    metadata_unavailable_count = statuses.get("public_plan_metadata_unavailable", 0)
    requirement_operators = report.get("coverage", {}).get("requirement_tree_operator_nodes", {})
    readme_path = bundle_root / "README.md"
    readme_lines = [line for line in readme_path.read_text(encoding="utf-8").splitlines() if line != "- `user_confirmed_study_plan_links.json` — точные ссылки с карточек профилей, подтверждённые пользователем."]
    artifact_line = "- `source_artifacts.jsonl` — URL, время получения, SHA-256 и путь/причина отсутствия исходного файла."
    if artifact_line in readme_lines:
        readme_lines.insert(readme_lines.index(artifact_line) + 1, "- `user_confirmed_study_plan_links.json` — точные ссылки с карточек профилей, подтверждённые пользователем.")
    confirmation_paragraph = f"Разобраны учебные планы: {statuses.get(IDENTITY_VERIFIED_STATUS, 0) + statuses.get(USER_CONFIRMED_STATUS, 0)} из {len(study_plans)}. Автоматически подтверждены по содержимому файла: {statuses.get(IDENTITY_VERIFIED_STATUS, 0)}; обработаны по точной ссылке каталога, подтверждённой пользователем: {statuses.get(USER_CONFIRMED_STATUS, 0)}. Код в PDF сохранён как извлечён: {header_summary}."
    readme_lines = [line for line in readme_lines if not line.startswith("Разобраны учебные планы:")]
    footer_index = next((i for i, line in enumerate(readme_lines) if line.startswith("ZIP подготовлен для последующей загрузки;")), len(readme_lines))
    readme_lines[footer_index:footer_index] = [confirmation_paragraph, ""]
    readme_path.write_text("\n".join(readme_lines).rstrip() + "\n", encoding="utf-8")

    report_md = f"""# BMSTU 2026 выгрузка: отчёт проверки

## Что вошло

- Направления: **{counts.get('directions', 0)}**; профили: **{counts.get('educational_programs', 0)}**; кафедры: **{counts.get('departments', 0)}**.
- В кампусе подтверждены **{report['coverage'].get('profiles_confirmed_moscow_head_campus', 0)}** профиля; **{report['coverage'].get('profiles_campus_unverified', 0)}** ещё требуют уточнения по адресу кафедры.
- Строк предложений приёма: **{counts.get('program_offerings', 0)}**; точных связей с профилями: **72**. Остальные строки сохранены без догадки о профиле.
- Учебные планы разобраны: **{statuses.get(IDENTITY_VERIFIED_STATUS, 0) + statuses.get(USER_CONFIRMED_STATUS, 0)} из {len(study_plans)}**. Автоматическая проверка файла подтвердила **{statuses.get(IDENTITY_VERIFIED_STATUS, 0)}**; ещё **{statuses.get(USER_CONFIRMED_STATUS, 0)}** разобраны по точным ссылкам карточек, подтверждённым пользователем. Заголовки PDF сохранены без изменений: **{header_summary}**.
- Учебные планы ещё недоступны: **{len(study_plans) - statuses.get(IDENTITY_VERIFIED_STATUS, 0) - statuses.get(USER_CONFIRMED_STATUS, 0)}**; по **{no_file_count}** ссылкам файл не найден, у **{metadata_unavailable_count}** ресурсов не удалось получить метаданные.
- Строк дисциплин в планах: **{len(curriculum_items)}**.
- Документы приёма сохранены: **16 PDF**; олимпиады исключены по просьбе пользователя.
- Даты кампании: **{counts.get('campaign_dates', 0)}**; требования к экзаменам: **{counts.get('admission_exam_requirements', 0)}**; стоимость: **{counts.get('tuition', 0)}** строк; исторические итоги: **{counts.get('historical_admission_statistics', 0)}** строк.
- Строк ручной проверки: **{len(review_rows)}**.

## Проверки

- JSONL: **{report['validation'].get('jsonl_files', 0)}** файлов.
- Концы явных связей разрешаются: **{report['validation'].get('relationships_checked', 0) - report['validation'].get('unresolved_relationship_endpoints', 0)}/{report['validation'].get('relationships_checked', 0)}**.
- Деревья требований к экзаменам проверены: **{report['validation'].get('requirements_checked', 0)}**; узлы логики AND / OR / AT_LEAST: **{requirement_operators.get('AND', 0)} / {requirement_operators.get('OR', 0)} / {requirement_operators.get('AT_LEAST', 0)}**.
- SHA-256 сверены для **{report['validation'].get('sha256_raw_files_checked', 0)}** сохранённых исходных файлов; ошибок до этой перепроверки: **{report['validation'].get('source_artifact_metadata_errors', 0)}**.
- Персональные строки абитуриентов не сохранялись. В PostgreSQL данные не загружались; ORM и миграции не менялись.

## Ограничения

- Страница конкурсных списков вернула HTTP 403; из официальных итоговых документов использованы только агрегаты без персональных строк.
- В **{statuses.get(USER_CONFIRMED_STATUS, 0)}** планах связь с карточкой подтверждена пользователем; {header_summary}.
- Один и тот же PDF прямо указан на двух разных карточках. Он обработан отдельно в контексте каждой карточки и отмечен общим исходным файлом в записях.
- Олимпиадные профили, льготы и источники организаторов не обрабатывались.
- Прочие нерешённые связи и неполученные источники перечислены в `manual_review.csv`.
    """
    (bundle_root / "report.md").write_text(report_md, encoding="utf-8")
    build_visualizer(bundle_root)
    archive_path = _validate_and_package(bundle_root, report, links)
    final_report = json.loads((bundle_root / "validation_report.json").read_text(encoding="utf-8"))
    return {
        "parsed_confirmed_plans": statuses.get(USER_CONFIRMED_STATUS, 0),
        "identity_verified_plans": statuses.get(IDENTITY_VERIFIED_STATUS, 0),
        "added_curriculum_rows": len(added_items),
        "total_curriculum_rows": len(curriculum_items),
        "header_code_relations": dict(header_code_relations),
        "shared_downloads": shared_downloads,
        "manual_review_rows": len(review_rows),
        "validation_errors": final_report["validation"]["errors"],
        "zip_path": str(archive_path),
        "zip_integrity_ok": final_report["validation"]["zip_integrity_ok"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reparse only user-confirmed BMSTU profile-card study-plan links from captured source files.")
    parser.add_argument("--bundle", type=Path, default=Path("backend/exports/andromeda_bmstu_2026_bundle"))
    args = parser.parse_args()
    print(json.dumps(reconcile(args.bundle), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
