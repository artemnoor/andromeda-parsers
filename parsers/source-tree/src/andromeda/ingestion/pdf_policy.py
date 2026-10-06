"""Bounded PDF resource policy shared by university-specific parsers."""

from __future__ import annotations

from dataclasses import dataclass


class PdfResourceError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class PdfDependencyError(PdfResourceError):
    pass


@dataclass(frozen=True, slots=True)
class PdfResourcePolicy:
    max_bytes: int = 50_000_000
    max_pages: int = 500
    parser_timeout_seconds: float = 60.0
    max_text_characters: int = 12_000_000

    def __post_init__(self) -> None:
        if not 1_000_000 <= self.max_bytes <= 100_000_000:
            raise ValueError("max_bytes must be between 1 MB and 100 MB")
        if not 1 <= self.max_pages <= 2_000:
            raise ValueError("max_pages must be between 1 and 2000")
        if not 1 <= self.parser_timeout_seconds <= 300:
            raise ValueError("parser_timeout_seconds must be between 1 and 300")
        if not 100_000 <= self.max_text_characters <= 50_000_000:
            raise ValueError("max_text_characters must be between 100k and 50m")


DEFAULT_PDF_POLICY = PdfResourcePolicy()


def validate_pdf_payload(body: bytes, policy: PdfResourcePolicy = DEFAULT_PDF_POLICY) -> None:
    if not body:
        raise PdfResourceError("pdf_empty_body")
    if len(body) > policy.max_bytes:
        raise PdfResourceError("pdf_size_limit_exceeded")
    if not body.startswith(b"%PDF"):
        raise PdfResourceError("pdf_signature_invalid")


def validate_page_count(page_count: int, policy: PdfResourcePolicy = DEFAULT_PDF_POLICY) -> None:
    if page_count < 1:
        raise PdfResourceError("pdf_page_count_invalid")
    if page_count > policy.max_pages:
        raise PdfResourceError("pdf_page_limit_exceeded")


def validate_text_size(text: str, policy: PdfResourcePolicy = DEFAULT_PDF_POLICY) -> str:
    if len(text) > policy.max_text_characters:
        raise PdfResourceError("pdf_text_limit_exceeded")
    return text


__all__ = [
    "DEFAULT_PDF_POLICY",
    "PdfDependencyError",
    "PdfResourceError",
    "PdfResourcePolicy",
    "validate_page_count",
    "validate_pdf_payload",
    "validate_text_size",
]
