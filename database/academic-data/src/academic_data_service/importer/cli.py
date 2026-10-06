"""Argument-parser helpers for offline bundle commands."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from academic_data_service.importer.bundle import (
    validate_bundle,
    write_validation_report,
)
from academic_data_service.importer.persistence import run_bundle_import

logger = logging.getLogger("academic_data_service.bundle")


def add_bundle_commands(groups: Any) -> None:
    """Register the bundle command group without adding any network or DB options."""

    bundle = groups.add_parser("bundle", help="validate or stage an existing offline bundle")
    actions = bundle.add_subparsers(dest="bundle_action", required=True)
    validate = actions.add_parser("validate", help="validate normalized bundle files offline")
    validate.add_argument("--input", required=True, help="bundle directory or ZIP archive")
    validate.add_argument(
        "--output",
        help="optional JSON report path (an existing directory receives validation-report.json)",
    )
    importer = actions.add_parser("import", help="map or commit a sanitized bundle offline")
    importer.add_argument("--input", required=True, help="bundle directory or ZIP archive")
    mode = importer.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and map without opening a database connection",
    )
    mode.add_argument(
        "--commit",
        action="store_true",
        help="persist and activate a release in the dedicated service DB",
    )
    importer.add_argument(
        "--output",
        help="optional JSON report path (an existing directory receives import-report.json)",
    )


def execute_bundle_validation(
    input_path: str | Path, output_path: str | Path | None = None
) -> tuple[dict[str, Any], Path | None]:
    """Validate the supplied bundle and optionally write its deterministic report."""

    report = validate_bundle(input_path)
    written_path: Path | None = None
    if output_path is not None:
        written_path = write_validation_report(report, output_path)
        logger.info(
            "bundle validation report written",
            extra={
                "event": "bundle.validation.report_written",
                "phase": "output",
                "relative_file": str(written_path),
                "digest": report["input"]["digest"],
                "outcome": "valid" if report["valid"] else "invalid",
            },
        )
    return report, written_path


def execute_bundle_import(
    input_path: str | Path,
    *,
    commit: bool,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run explicit dry-run or commit mode for an already-parsed bundle."""

    return run_bundle_import(
        str(input_path),
        commit=commit,
        output_path=str(output_path) if output_path is not None else None,
    )
