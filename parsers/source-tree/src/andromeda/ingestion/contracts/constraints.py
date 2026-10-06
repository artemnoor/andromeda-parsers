"""Reusable scalar validators for ingestion source contracts."""

from __future__ import annotations

from pydantic import HttpUrl, TypeAdapter


HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


def http_url(value: str) -> HttpUrl:
    """Validate and normalize an official source URL at the contract boundary."""

    return HTTP_URL_ADAPTER.validate_python(value)


__all__ = ["http_url"]
