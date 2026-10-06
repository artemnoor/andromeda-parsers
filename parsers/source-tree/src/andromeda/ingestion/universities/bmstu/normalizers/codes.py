from __future__ import annotations

from .text import normalize_text


def normalize_code(value: str) -> str:
    return normalize_text(value).replace("–", "-").replace("—", "-").replace("/", "-").replace(" ", "")
