from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngredientAlias


BUILTIN_ALIASES = {
    "西红柿": "番茄",
    "马铃薯": "土豆",
    "小葱": "葱",
    "香葱": "葱",
}


def normalize_name(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def alias_map(db: Session) -> dict[str, str]:
    aliases = {
        normalize_name(alias): normalize_name(canonical)
        for alias, canonical in BUILTIN_ALIASES.items()
    }
    for row in db.scalars(select(IngredientAlias)).all():
        aliases[row.normalized_alias] = normalize_name(row.canonical_name)
    return aliases


def canonicalize(value: Any, aliases: dict[str, str]) -> str:
    normalized = normalize_name(value)
    if normalized in aliases:
        return aliases[normalized]
    for alias in sorted(aliases, key=len, reverse=True):
        if alias and alias in normalized:
            normalized = normalized.replace(alias, aliases[alias])
    return normalized
