from __future__ import annotations

import unicodedata


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value.replace("\xa0", " ")).strip().split())
