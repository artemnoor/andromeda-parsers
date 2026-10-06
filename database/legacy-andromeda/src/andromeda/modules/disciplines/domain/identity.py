from __future__ import annotations

import unicodedata
import re
from hashlib import sha256

from ....shared.contracts.ids import DisciplineId, ShortText


def normalize_discipline_name(source_name: str) -> ShortText:
    """Apply only lossless whitespace/case normalization.

    Punctuation, abbreviations and parenthetical qualifiers are deliberately
    kept, so visually similar but semantically uncertain subjects are not
    merged automatically.
    """

    normalized = " ".join(unicodedata.normalize("NFKC", source_name.replace("\xa0", " ")).casefold().split())
    if not normalized:
        raise ValueError("discipline source name must be non-empty")
    return normalized


def normalize_classification_name(source_name: str) -> ShortText:
    """Normalize safe spelling variants used only by taxonomy matching.

    The identity normalizer remains lossless so existing discipline IDs do not
    change. Taxonomy matching may safely fold ``ё``/``е`` and Unicode dash
    variants while retaining other source distinctions.
    """

    normalized = normalize_discipline_name(source_name)
    normalized = normalized.replace("ё", "е")
    normalized = re.sub(r"[‐‑‒–—―]", "-", normalized)
    return " ".join(normalized.split())


def discipline_id_for(normalized_name: str) -> DisciplineId:
    return f"discipline:{sha256(normalized_name.encode('utf-8')).hexdigest()[:16]}"


__all__ = ["discipline_id_for", "normalize_classification_name", "normalize_discipline_name"]
