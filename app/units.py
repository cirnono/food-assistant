from __future__ import annotations

from typing import Any


_GROUPS = {
    "g": {"g", "gram", "grams", "克", "公克"},
    "kg": {"kg", "kilogram", "kilograms", "千克", "公斤"},
    "ml": {"ml", "milliliter", "milliliters", "millilitre", "millilitres", "毫升"},
    "l": {"l", "litre", "litres", "liter", "liters", "升"},
    "piece": {"个", "个装", "pcs", "pc", "piece", "pieces"},
    "枚": {"枚"},
    "tbsp": {"tbsp", "tablespoon", "tablespoons", "大勺", "汤匙"},
    "tsp": {"tsp", "teaspoon", "teaspoons", "小勺", "茶匙"},
}
_FAMILIES = {
    "g": "mass", "kg": "mass", "ml": "volume", "l": "volume",
    "piece": "count", "枚": "count", "tbsp": "volume-spoon", "tsp": "volume-spoon",
}
_ALIASES = {
    alias.casefold(): canonical
    for canonical, aliases in _GROUPS.items()
    for alias in aliases
}
_IMPRECISE = {"适量", "少许", "若干"}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().casefold().strip(".。")
    return cleaned or None


def normalize_unit(value: Any) -> str | None:
    """Canonicalize equivalent spelling without converting quantities."""
    cleaned = _clean(value)
    return _ALIASES.get(cleaned) if cleaned else None


def unit_family(value: Any) -> str | None:
    normalized = normalize_unit(value)
    return _FAMILIES.get(normalized) if normalized else None


def units_compatible(left: Any, right: Any) -> bool:
    left_clean, right_clean = _clean(left), _clean(right)
    if left_clean is None or right_clean is None:
        return left_clean is None and right_clean is None
    left_normalized, right_normalized = normalize_unit(left), normalize_unit(right)
    return bool(left_normalized and left_normalized == right_normalized)


def units_merge_compatible(left: Any, right: Any) -> bool:
    """Allow identical inventory labels to merge, but never vague quantities."""
    left_clean, right_clean = _clean(left), _clean(right)
    if units_compatible(left, right):
        return True
    return bool(
        left_clean
        and left_clean == right_clean
        and left_clean not in _IMPRECISE
    )


def unit_match_reason(left: Any, right: Any) -> str:
    left_clean, right_clean = _clean(left), _clean(right)
    if left_clean is None or right_clean is None:
        return "missing unit"
    left_normalized, right_normalized = normalize_unit(left), normalize_unit(right)
    if left_normalized is None or right_normalized is None:
        return "unsupported free-text unit"
    if left_normalized != right_normalized:
        return "incompatible unit family"
    return "exact raw unit" if left_clean == right_clean else "equivalent spelling"
