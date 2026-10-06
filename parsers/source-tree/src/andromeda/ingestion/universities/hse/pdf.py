from __future__ import annotations

import io

from andromeda.ingestion.pdf_policy import PdfResourceError, validate_page_count, validate_pdf_payload, validate_text_size


def is_pdf(body: bytes, content_type: str | None = None, url: str = "") -> bool:
    return body.startswith(b"%PDF") or "pdf" in (content_type or "").casefold() or url.casefold().split("?", 1)[0].endswith(".pdf")


def extract_pdf_text(body: bytes) -> str:
    validate_pdf_payload(body)
    try:
        import fitz  # type: ignore[import-untyped]

        document = fitz.open(stream=body, filetype="pdf")
        try:
            validate_page_count(document.page_count)
            return validate_text_size("\n\n".join(page.get_text("text", sort=True) or "" for page in document).strip())
        finally:
            document.close()
    except PdfResourceError:
        raise
    except Exception:
        pass
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(body)) as document:
            validate_page_count(len(document.pages))
            pages = [page.extract_text(x_tolerance=1, y_tolerance=3) or "" for page in document.pages]
        return validate_text_size("\n\n".join(pages).strip())
    except PdfResourceError:
        raise
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        validate_page_count(len(reader.pages))
        return validate_text_size("\n\n".join(page.extract_text() or "" for page in reader.pages).strip())
    except PdfResourceError:
        raise
    except Exception:
        return ""


__all__ = ["extract_pdf_text", "is_pdf"]
