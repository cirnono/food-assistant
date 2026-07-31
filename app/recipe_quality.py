from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.ai_recipes import (
    NormalizedIngredient,
    NormalizedRecipe,
    RecipeTimer,
)
from app.ingredient_policy import (
    canonical_food_name,
)
from app.recipe_semantics import (
    apply_recipe_semantics,
)


UNIT_ALIASES = {
    "g": "克",
    "gram": "克",
    "grams": "克",
    "kg": "千克",
    "ml": "毫升",
    "milliliter": "毫升",
    "milliliters": "毫升",
    "l": "升",
    "liter": "升",
    "liters": "升",
}

NUMBER_PATTERN = r"\d+(?:\.\d+)?"

UNIT_PATTERN = (
    r"ml|mL|ML|毫升|"
    r"g|G|克|"
    r"kg|KG|千克|"
    r"l|L|升"
)

EXACT_DURATION_PATTERN = re.compile(
    rf"(?<!\d)"
    rf"({NUMBER_PATTERN})"
    rf"\s*"
    rf"(秒钟?|分钟|小时)"
)

RANGE_DURATION_PATTERN = re.compile(
    rf"({NUMBER_PATTERN})"
    rf"\s*"
    rf"(?:-|–|—|~|～|至|到)"
    rf"\s*"
    rf"({NUMBER_PATTERN})"
    rf"\s*"
    rf"(秒钟?|分钟|小时)"
)

SERVINGS_PATTERN = re.compile(
    r"一份.{0,30}?"
    r"(?:够|可供|供)"
    r"\s*(\d+(?:\.\d+)?)"
    r"\s*个?人"
)

TOTAL_TIME_PATTERNS = [
    re.compile(
        r"约需\s*(\d+)\s*分钟"
    ),
    re.compile(
        r"总时长.{0,10}?"
        r"(\d+)\s*分钟"
    ),
    re.compile(
        r"从备料到出锅.{0,15}?"
        r"(\d+)\s*分钟"
    ),
]

QUANTITY_UNIT_PATTERN = re.compile(
    rf"({NUMBER_PATTERN})"
    rf"\s*"
    rf"({UNIT_PATTERN})",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class AmountMention:
    quantity: float
    unit: str
    original_text: str


STEP_INGREDIENT_RULES = {
    "食用油": {
        "aliases": (
            "食用油",
            "植物油",
            "色拉油",
        ),
        "mention_pattern": re.compile(
            r"(?:倒入|加入|放入|烧热|热)"
            r"\s*(?:约|适量|少许|少量)?"
            r"\s*(?:食用油|植物油|色拉油|油)"
        ),
    },
    "水": {
        "aliases": (
            "开水",
            "热水",
            "温水",
            "凉水",
            "冷水",
            "清水",
            "冰水",
            "水",
        ),
        "mention_pattern": re.compile(
            r"(?:倒入|加入|加|烧|准备)"
            r".{0,5}?"
            r"(?:开水|热水|温水|凉水|冷水|清水|冰水|水)"
        ),
    },
}


def _append_unique(
    values: list[str],
    value: str,
) -> None:
    if value not in values:
        values.append(value)


def _normalise_unit(
    value: str,
) -> str:
    raw = value.strip()

    return UNIT_ALIASES.get(
        raw.casefold(),
        raw,
    )


def _to_base_quantity(
    quantity: float,
    unit: str,
) -> tuple[float, str]:
    normalised = _normalise_unit(unit)

    if normalised == "升":
        return quantity * 1000, "毫升"

    if normalised == "千克":
        return quantity * 1000, "克"

    return quantity, normalised


def _duration_to_seconds(
    value: str,
    unit: str,
) -> int:
    number = float(value)

    if unit.startswith("秒"):
        seconds = number
    elif unit == "分钟":
        seconds = number * 60
    else:
        seconds = number * 3600

    return max(1, round(seconds))


def _spans_overlap(
    first: tuple[int, int],
    second: tuple[int, int],
) -> bool:
    return (
        first[0] < second[1]
        and second[0] < first[1]
    )


def _rebuild_instruction_timers(
    recipe: NormalizedRecipe,
    issues: list[str],
) -> None:
    """
    Treat instruction text as authoritative.

    Existing model-generated timers are discarded, then
    rebuilt only from explicit durations in the step text.
    """
    for instruction in recipe.instructions:
        text = instruction.text

        range_matches = list(
            RANGE_DURATION_PATTERN.finditer(text)
        )

        range_spans = [
            match.span()
            for match in range_matches
        ]

        # 正常时间范围由 recipe_semantics 重建为
        # range timer。它不再需要人工确认。
        timers: list[RecipeTimer] = []
        seen_seconds: set[int] = set()

        for match in EXACT_DURATION_PATTERN.finditer(
            text
        ):
            if any(
                _spans_overlap(
                    match.span(),
                    range_span,
                )
                for range_span in range_spans
            ):
                continue

            seconds = _duration_to_seconds(
                match.group(1),
                match.group(2),
            )

            if seconds in seen_seconds:
                continue

            timers.append(
                RecipeTimer(
                    name=(
                        f"步骤 "
                        f"{instruction.step_number} "
                        f"计时 {match.group(0)}"
                    ),
                    duration_seconds=seconds,
                )
            )

            seen_seconds.add(seconds)

        instruction.timers = timers


def _extract_amount_mentions(
    text: str,
    aliases: tuple[str, ...],
) -> list[AmountMention]:
    alias_pattern = "|".join(
        re.escape(alias)
        for alias in sorted(
            aliases,
            key=len,
            reverse=True,
        )
    )

    patterns = [
        re.compile(
            rf"(?:约|大约)?\s*"
            rf"(?P<quantity>{NUMBER_PATTERN})"
            rf"\s*"
            rf"(?P<unit>{UNIT_PATTERN})"
            rf"\s*"
            rf"(?P<alias>{alias_pattern})",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<alias>{alias_pattern})"
            rf"\s*"
            rf"(?:约|大约|共|总共|为|：|:|，|,)?"
            rf"\s*"
            rf"(?P<quantity>{NUMBER_PATTERN})"
            rf"\s*"
            rf"(?P<unit>{UNIT_PATTERN})",
            flags=re.IGNORECASE,
        ),
    ]

    results: list[AmountMention] = []
    used_spans: list[tuple[int, int]] = []

    for pattern in patterns:
        for match in pattern.finditer(text):
            span = match.span()

            if any(
                _spans_overlap(
                    span,
                    used_span,
                )
                for used_span in used_spans
            ):
                continue

            quantity, unit = _to_base_quantity(
                float(match.group("quantity")),
                match.group("unit"),
            )

            results.append(
                AmountMention(
                    quantity=quantity,
                    unit=unit,
                    original_text=match.group(0).strip(),
                )
            )

            used_spans.append(span)

    return results


def _ingredient_matches_concept(
    ingredient: NormalizedIngredient,
    canonical_name: str,
) -> bool:
    name = canonical_food_name(
        ingredient.food_name
    )

    if name == canonical_name:
        return True

    if canonical_name == "食用油":
        return name in {
            "食用油",
            "花生油",
            "菜籽油",
            "玉米油",
            "葵花籽油",
            "橄榄油",
            "芝麻油",
            "香油",
        }

    return False


def _find_existing_ingredient(
    recipe: NormalizedRecipe,
    canonical_name: str,
) -> NormalizedIngredient | None:
    for ingredient in recipe.ingredients:
        if _ingredient_matches_concept(
            ingredient,
            canonical_name,
        ):
            return ingredient

    return None


def _collect_step_ingredient_data(
    recipe: NormalizedRecipe,
    canonical_name: str,
    aliases: tuple[str, ...],
    mention_pattern: re.Pattern[str],
) -> tuple[list[AmountMention], bool]:
    mentions: list[AmountMention] = []
    used = False

    for instruction in recipe.instructions:
        text = instruction.text

        found = _extract_amount_mentions(
            text,
            aliases,
        )

        if found:
            mentions.extend(found)
            used = True

        if mention_pattern.search(text):
            used = True

    return mentions, used


def _apply_step_ingredient_rule(
    recipe: NormalizedRecipe,
    canonical_name: str,
    aliases: tuple[str, ...],
    mention_pattern: re.Pattern[str],
    issues: list[str],
    completion_notes: list[str],
) -> None:
    mentions, used = _collect_step_ingredient_data(
        recipe,
        canonical_name,
        aliases,
        mention_pattern,
    )

    if not used:
        return

    existing = _find_existing_ingredient(
        recipe,
        canonical_name,
    )

    grouped: dict[str, list[AmountMention]] = (
        defaultdict(list)
    )

    for mention in mentions:
        grouped[mention.unit].append(
            mention
        )

    if existing is not None:
        if (
            existing.quantity is not None
            and existing.unit is not None
            and len(grouped) == 1
        ):
            expected_unit = next(iter(grouped))
            expected_quantity = sum(
                mention.quantity
                for mention in grouped[
                    expected_unit
                ]
            )

            actual_quantity, actual_unit = (
                _to_base_quantity(
                    existing.quantity,
                    existing.unit,
                )
            )

            if (
                actual_unit == expected_unit
                and abs(
                    actual_quantity
                    - expected_quantity
                ) > 0.01
            ):
                _append_unique(
                    issues,
                    (
                        f"食材“{existing.food_name}”"
                        f"记录为 {actual_quantity:g}"
                        f"{actual_unit}，但步骤明确用量合计为 "
                        f"{expected_quantity:g}"
                        f"{expected_unit}"
                    ),
                )

        return

    if len(grouped) == 1:
        unit = next(iter(grouped))
        amount_mentions = grouped[unit]

        total_quantity = sum(
            mention.quantity
            for mention in amount_mentions
        )

        notes = [
            "根据步骤补全",
        ]

        if len(amount_mentions) > 1:
            notes.append(
                f"分 {len(amount_mentions)} 次使用"
            )

        if canonical_name == "水":
            notes.append(
                "按步骤要求处理水温"
            )

        original_values: list[str] = []

        for mention in amount_mentions:
            if (
                mention.original_text
                not in original_values
            ):
                original_values.append(
                    mention.original_text
                )

        recipe.ingredients.append(
            NormalizedIngredient(
                food_name=canonical_name,
                quantity=total_quantity,
                unit=unit,
                note="；".join(notes),
                original_text="；".join(
                    original_values
                ),
                optional=False,
            )
        )

        _append_unique(
            completion_notes,
            (
                f"已根据步骤补入"
                f"“{canonical_name} "
                f"{total_quantity:g}{unit}”"
            ),
        )

        return

    if len(grouped) > 1:
        _append_unique(
            issues,
            (
                f"步骤中“{canonical_name}”"
                "使用了无法直接合并的多种单位"
            ),
        )

        return

    recipe.ingredients.append(
        NormalizedIngredient(
            food_name=canonical_name,
            quantity=None,
            unit=None,
            note=(
                "步骤中提及但未注明用量；"
                "根据步骤补全"
            ),
            original_text=(
                f"步骤中提及{canonical_name}"
            ),
            optional=False,
        )
    )

    _append_unique(
        issues,
        (
            f"步骤使用了“{canonical_name}”，"
            "但没有明确用量"
        ),
    )


def _check_component_sums(
    recipe: NormalizedRecipe,
    issues: list[str],
) -> None:
    """
    Warn when one ingredient contains several component
    quantities but the structured total does not equal
    their sum.

    This is intentionally a warning rather than an
    automatic correction.
    """
    for ingredient in recipe.ingredients:
        if (
            ingredient.quantity is None
            or ingredient.unit is None
        ):
            continue

        matches = list(
            QUANTITY_UNIT_PATTERN.finditer(
                ingredient.original_text
            )
        )

        if len(matches) < 2:
            continue

        actual_quantity, actual_unit = (
            _to_base_quantity(
                ingredient.quantity,
                ingredient.unit,
            )
        )

        values: list[float] = []

        for match in matches:
            quantity, unit = _to_base_quantity(
                float(match.group(1)),
                match.group(2),
            )

            if unit == actual_unit:
                values.append(quantity)

        if len(values) < 2:
            continue

        expected_quantity = sum(values)

        if abs(
            actual_quantity
            - expected_quantity
        ) <= 0.01:
            continue

        _append_unique(
            issues,
            (
                f"食材“{ingredient.food_name}”"
                f"的分项数量合计为 "
                f"{expected_quantity:g}{actual_unit}，"
                f"但结构化总量为 "
                f"{actual_quantity:g}{actual_unit}"
            ),
        )


def apply_recipe_quality_gate(
    recipe: NormalizedRecipe,
    *,
    source_text: str,
    source_name: str,
    source_url: str,
    source_path: str,
    source_license: str | None,
) -> tuple[NormalizedRecipe, list[str]]:
    issues: list[str] = []
    blocking_issues: list[str] = []
    info_notes: list[str] = []
    completion_notes: list[str] = []

    known_prefixes = (
        "[系统校验]",
        "[系统补全]",
        "[必须修正]",
        "[需要确认]",
        "[信息提示]",
    )

    manual_warnings = [
        warning
        for warning in recipe.warnings
        if warning.startswith(
            "[人工审核]"
        )
    ]

    legacy_warnings = [
        warning
        for warning in recipe.warnings
        if not warning.startswith(
            "[人工审核]"
        )
        and not warning.startswith(
            known_prefixes
        )
    ]

    recipe.warnings = manual_warnings

    for warning in legacy_warnings:
        _append_unique(
            issues,
            warning,
        )

    recipe.source.source_name = source_name
    recipe.source.source_url = source_url
    recipe.source.source_path = source_path
    recipe.source.source_license = (
        source_license
    )

    cleaned_tags: list[str] = []

    for raw_tag in recipe.tags:
        tag = raw_tag.strip()

        if not tag:
            continue

        if tag not in cleaned_tags:
            cleaned_tags.append(tag)

    if (
        source_name == "程序员做饭指南"
        and "来源-HowToCook"
        not in cleaned_tags
    ):
        cleaned_tags.append(
            "来源-HowToCook"
        )

    recipe.tags = cleaned_tags[:12]

    for ingredient in recipe.ingredients:
        ingredient.food_name = (
            canonical_food_name(
                ingredient.food_name
            )
        )

        if (
            ingredient.note is not None
            and not ingredient.note.strip()
        ):
            ingredient.note = None

        if ingredient.unit is not None:
            raw_unit = ingredient.unit.strip()

            ingredient.unit = (
                _normalise_unit(raw_unit)
                if raw_unit
                else None
            )

        if (
            ingredient.unit == "瓣"
            and "蒜" not in ingredient.food_name
        ):
            _append_unique(
                blocking_issues,
                (
                    f"食材“{ingredient.food_name}”"
                    "使用了可疑单位“瓣”"
                ),
            )

    if recipe.servings is None:
        match = SERVINGS_PATTERN.search(
            source_text
        )

        if match:
            recipe.servings = float(
                match.group(1)
            )

    if recipe.total_time_minutes is None:
        for pattern in TOTAL_TIME_PATTERNS:
            match = pattern.search(
                source_text
            )

            if match:
                recipe.total_time_minutes = int(
                    match.group(1)
                )
                break

    semantic_quality = (
        apply_recipe_semantics(
            recipe
        )
    )

    blocking_issues.extend(
        semantic_quality.blocking
    )

    issues.extend(
        semantic_quality.confirmation
    )

    info_notes.extend(
        semantic_quality.info
    )

    completion_notes.extend(
        semantic_quality.completion
    )

    _check_component_sums(
        recipe,
        issues,
    )

    seen_names: set[str] = set()

    for ingredient in recipe.ingredients:
        normalized_name = (
            ingredient.food_name
            .strip()
            .casefold()
        )

        if normalized_name in seen_names:
            _append_unique(
                blocking_issues,
                (
                    "结构化食材表中重复出现"
                    f"“{ingredient.food_name}”"
                ),
            )

        seen_names.add(normalized_name)

    for note in completion_notes:
        recipe.warnings.append(
            f"[系统补全] {note}"
        )

    for note in info_notes:
        recipe.warnings.append(
            f"[信息提示] {note}"
        )

    for issue in issues:
        recipe.warnings.append(
            f"[需要确认] {issue}"
        )

    for issue in blocking_issues:
        recipe.warnings.append(
            f"[必须修正] {issue}"
        )

    actionable_issues = (
        blocking_issues
        + issues
    )

    recipe.review_required = bool(
        actionable_issues
    )

    if actionable_issues:
        recipe.recommendation = "review"
        recipe.import_score = min(
            recipe.import_score,
            79,
        )

    return recipe, actionable_issues
