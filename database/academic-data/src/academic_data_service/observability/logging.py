"""Configurable JSON logs with an allow-list of safe context fields."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

SERVICE_LOGGER_NAME = "academic_data_service"
ALLOWED_CONTEXT_FIELDS = frozenset(
    {
        "event",
        "service_version",
        "request_id",
        "method",
        "route",
        "status_code",
        "elapsed_ms",
        "exception_type",
        "contract_version",
        "database_host",
        "database_name",
        "migration_revision",
        "phase",
        "relative_file",
        "line_number",
        "source_key",
        "record_count",
        "digest",
        "error_code",
        "warning_code",
        "outcome",
        "reason_code",
        "pool_size",
        "pool_checked_out",
        "pool_overflow",
        "pool_max_overflow",
        "request_timeout_seconds",
        "root_path",
        "input_digest",
        "release_key",
        "release_id",
        "batch_id",
        "mapper_version",
        "table",
        "dataset",
        "chunk_ordinal",
        "chunk_count",
        "chunk_size",
        "source_key",
        "sqlstate",
        "constraint_name",
        "database_table",
        "database_column",
        "database_exception_type",
        "failure_code",
        "failure_reason",
        "inserted_count",
        "skipped_count",
        "database_connection_opened",
        "network_requests",
    }
)


class JsonLogFormatter(logging.Formatter):
    """Serialize fixed and allow-listed fields; arbitrary extras are ignored."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ALLOWED_CONTEXT_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level_name: str | None = None) -> logging.Logger:
    """Configure the service logger once and return it."""
    logger = logging.getLogger(SERVICE_LOGGER_NAME)
    configured_level = (level_name or os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, configured_level, None)
    if not isinstance(level, int) or configured_level not in {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }:
        level = logging.INFO

    logger.setLevel(level)
    logger.propagate = False
    if not any(isinstance(handler.formatter, JsonLogFormatter) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    for existing_handler in logger.handlers:
        existing_handler.setLevel(level)
    return logger
