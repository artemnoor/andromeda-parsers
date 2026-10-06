from __future__ import annotations

from typing import Any

from ....capture import AdmissionOrderManifestEntry, parse_orders_manifest
from ....parser.admission_orders import iter_pdf_pages, parse_admission_order_document
from ....source_metadata import classify_order_document


def parse_order_sources(manifest_body: bytes, manifest_url: str, pdf_loader: Any) -> dict[str, list[dict[str, Any]]]:
    """Parse official final orders in memory; never return or persist applicant rows."""
    entries = parse_orders_manifest(manifest_body, manifest_url)
    documents: list[dict[str, Any]] = []
    statistics: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        try:
            body, artifact = pdf_loader(entry.requested_url, index)
        except Exception as exc:
            key = f"admission_result_source:bmstu:manifest:{index}"
            documents.append({
                "external_key": key,
                "title": entry.title,
                "source_url": entry.requested_url,
                "retrieved_at": None,
                "sha256": None,
                "stored": False,
                "omission_reason": "document contains personal applicant records; only aggregate parser observations retained",
                "capture_status": "failed",
            })
            manual_review.append({
                "record_key": key,
                "source_url": entry.requested_url,
                "issue_type": "final_order_source_unavailable",
                "details": f"{type(exc).__name__}: {exc}",
            })
            continue
        pages = iter_pdf_pages(body)
        metadata = classify_order_document(entry, pages)
        documents.append({
            "external_key": f"admission_result_source:bmstu:manifest:{index}",
            "title": entry.title,
            "source_url": entry.requested_url,
            "retrieved_at": artifact.retrieved_at,
            "sha256": artifact.sha256,
            "stored": False,
            "omission_reason": "document contains personal applicant records; only aggregate parser observations retained",
            "classification": {
                "document_kind": metadata.document_kind.value,
                "funding": metadata.funding.value,
                "stage": metadata.stage.value,
                "campus": metadata.campus.value,
                "admission_year": metadata.admission_year,
                "study_form": metadata.study_form,
            },
        })
        if metadata.campus.value == "unknown" and metadata.admission_year == 2026 and metadata.document_kind.value == "bachelor_specialist":
            manual_review.append({
                "record_key": documents[-1]["external_key"],
                "source_url": entry.requested_url,
                "issue_type": "order_document_campus_unresolved",
                "details": "This undergraduate/specialist order could not be classified as the Moscow head campus; applicant aggregates were not included in the Moscow statistics.",
            })
            continue
        if metadata.campus.value != "moscow" or metadata.admission_year != 2026 or metadata.document_kind.value != "bachelor_specialist":
            continue
        parsed = parse_admission_order_document(body, metadata)
        for observation in parsed.observations:
            statistics.append({
                "external_key": f"admission_statistic:bmstu:{observation.admission_year}:{observation.direction_code}:{observation.funding_type}:{metadata.stage.value}:{observation.competition_type.value}:{observation.status}:{observation.score if observation.score is not None else 'bvi'}",
                "direction_code": observation.direction_code,
                "admission_year": observation.admission_year,
                "study_form": observation.study_form,
                "funding_type": observation.funding_type,
                "admission_stage": metadata.stage.value,
                "competition_type": observation.competition_type.value,
                "status": observation.status,
                "score": int(observation.score) if observation.score is not None else None,
                "snapshot_date": None,
                "source_url": observation.source_url,
                "source_locator": {"page": observation.page, "row": observation.row},
            })
        if parsed.failed or parsed.warnings:
            manual_review.append({
                "record_key": documents[-1]["external_key"],
                "source_url": entry.requested_url,
                "issue_type": "final_order_parse_warning",
                "details": ";".join(parsed.warnings) if parsed.warnings else "parse_failed",
            })
    return {"source_documents": documents, "statistics": statistics, "manual_review": manual_review}


__all__ = ["parse_order_sources"]
