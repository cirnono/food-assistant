from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai_recipes import (
    NormalizedIngredient,
    NormalizedRecipe,
    RecipeTimer,
)
from app.ingredient_policy import (
    canonical_food_name,
)


NUMBER_PATTERN = r"\d+(?:\.\d+)?"

DURATION_UNIT_PATTERN = (
    r"秒钟?|分钟|小时"
)

EXACT_DURATION_PATTERN = re.compile(
    rf"(?<!\d)"
    rf"({NUMBER_PATTERN})"
    rf"\s*"
    rf"({DURATION_UNIT_PATTERN})"
)

RANGE_DURATION_PATTERN = re.compile(
    rf"({NUMBER_PATTERN})"
    rf"\s*"
    rf"(?:-|–|—|~|～|至|到)"
    rf"\s*"
    rf"({NUMBER_PATTERN})"
    rf"\s*"
    rf"({DURATION_UNIT_PATTERN})"
)

AMOUNT_UNIT_PATTERN = (
    r"毫升|ml|mL|克|g|G|"
    r"千克|kg|KG|升|l|L"
)

OIL_ALIASES = (
    "食用油",
    "植物油",
    "色拉油",
    "花生油",
    "菜籽油",
    "玉米油",
    "葵花籽油",
    "橄榄油",
)

WATER_ALIASES = (
    "冷水",
    "凉水",
    "清水",
    "温水",
    "热水",
    "开水",
    "冰水",
    "水",
)

SEASONING_NAMES = {
    "盐",
    "糖",
    "白糖",
    "酱油",
    "生抽",
    "老抽",
    "醋",
    "料酒",
    "味精",
    "鸡精",
    "蚝油",
    "胡椒粉",
    "小米椒",
}

COVERAGE_PATTERN = re.compile(
    r"淹没|没过|浸没|盖过|覆盖"
)

TO_TASTE_PATTERN = re.compile(
    r"按口味|依口味|酌量|调味"
)

AS_NEEDED_PATTERN = re.compile(
    r"适量|少许|少量|按需"
)


@dataclass
class SemanticQuality:
    blocking: list[str]
    confirmation: list[str]
    info: list[str]
    completion: list[str]


def append_unique(
    values: list[str],
    value: str,
) -> None:
    if value not in values:
        values.append(value)


def append_note(
    current: str | None,
    value: str,
) -> str:
    existing = (
        current.strip()
        if current
        else ""
    )

    if not existing:
        return value

    if value in existing:
        return existing

    return existing + "；" + value


def duration_to_seconds(
    value: str | float,
    unit: str,
) -> int:
    number = float(value)

    if unit.startswith("秒"):
        seconds = number
    elif unit == "分钟":
        seconds = number * 60
    else:
        seconds = number * 3600

    return max(
        1,
        round(seconds),
    )


def timer_key(
    timer: RecipeTimer,
) -> tuple:
    return (
        timer.kind,
        timer.duration_seconds,
        timer.duration_min_seconds,
        timer.duration_max_seconds,
    )


def rebuild_timers(
    recipe: NormalizedRecipe,
    quality: SemanticQuality,
) -> None:
    for instruction in recipe.instructions:
        text = instruction.text

        preserved = [
            timer
            for timer in instruction.timers
            if timer.source == "manual"
        ]

        preserved_keys = {
            timer_key(timer)
            for timer in preserved
        }

        timers = list(preserved)

        range_matches = list(
            RANGE_DURATION_PATTERN.finditer(
                text
            )
        )

        range_spans = [
            match.span()
            for match in range_matches
        ]

        for match in range_matches:
            minimum = duration_to_seconds(
                match.group(1),
                match.group(3),
            )

            maximum = duration_to_seconds(
                match.group(2),
                match.group(3),
            )

            key = (
                "range",
                None,
                minimum,
                maximum,
            )

            if key in preserved_keys:
                continue

            timers.append(
                RecipeTimer(
                    name=(
                        f"步骤 "
                        f"{instruction.step_number} "
                        "检查时间"
                    ),
                    kind="range",
                    duration_min_seconds=minimum,
                    duration_max_seconds=maximum,
                    source="automatic",
                    accepted=True,
                )
            )

        for match in (
            EXACT_DURATION_PATTERN.finditer(
                text
            )
        ):
            if any(
                match.start() < span[1]
                and span[0] < match.end()
                for span in range_spans
            ):
                continue

            seconds = duration_to_seconds(
                match.group(1),
                match.group(2),
            )

            key = (
                "fixed",
                seconds,
                None,
                None,
            )

            if key in preserved_keys:
                continue

            if any(
                timer_key(timer) == key
                for timer in timers
            ):
                continue

            timers.append(
                RecipeTimer(
                    name=(
                        f"步骤 "
                        f"{instruction.step_number} "
                        f"计时 {match.group(0)}"
                    ),
                    kind="fixed",
                    duration_seconds=seconds,
                    source="automatic",
                    accepted=True,
                )
            )

        for timer in timers:
            if timer.kind == "fixed":
                if not timer.duration_seconds:
                    append_unique(
                        quality.blocking,
                        (
                            f"步骤 "
                            f"{instruction.step_number}"
                            "存在没有时长的固定计时器"
                        ),
                    )

            elif timer.kind == "range":
                minimum = (
                    timer.duration_min_seconds
                )

                maximum = (
                    timer.duration_max_seconds
                )

                if (
                    minimum is None
                    or maximum is None
                    or minimum >= maximum
                ):
                    append_unique(
                        quality.blocking,
                        (
                            f"步骤 "
                            f"{instruction.step_number}"
                            "存在无效的范围计时器"
                        ),
                    )

        instruction.timers = timers


def normalise_unit(
    unit: str,
) -> str:
    value = unit.strip()

    aliases = {
        "ml": "毫升",
        "milliliter": "毫升",
        "g": "克",
        "kg": "千克",
        "l": "升",
    }

    return aliases.get(
        value.casefold(),
        value,
    )


def amount_mentions(
    text: str,
    aliases: tuple[str, ...],
) -> list[tuple[float, str]]:
    alias_pattern = "|".join(
        re.escape(value)
        for value in sorted(
            aliases,
            key=len,
            reverse=True,
        )
    )

    patterns = (
        re.compile(
            rf"(?P<quantity>{NUMBER_PATTERN})"
            rf"\s*"
            rf"(?P<unit>{AMOUNT_UNIT_PATTERN})"
            rf"\s*"
            rf"(?P<alias>{alias_pattern})",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<alias>{alias_pattern})"
            rf"\s*"
            rf"(?:约|大约|共|总共|为|：|:)?"
            rf"\s*"
            rf"(?P<quantity>{NUMBER_PATTERN})"
            rf"\s*"
            rf"(?P<unit>{AMOUNT_UNIT_PATTERN})",
            flags=re.IGNORECASE,
        ),
    )

    values: list[tuple[float, str]] = []
    used_spans: list[tuple[int, int]] = []

    for pattern in patterns:
        for match in pattern.finditer(text):
            span = match.span()

            if any(
                span[0] < old[1]
                and old[0] < span[1]
                for old in used_spans
            ):
                continue

            values.append(
                (
                    float(
                        match.group("quantity")
                    ),
                    normalise_unit(
                        match.group("unit")
                    ),
                )
            )

            used_spans.append(span)

    return values


def ingredient_matches(
    ingredient: NormalizedIngredient,
    canonical_name: str,
) -> bool:
    name = canonical_food_name(
        ingredient.food_name
    )

    if canonical_name == "食用油":
        return (
            name == "食用油"
            or name in OIL_ALIASES
        )

    if canonical_name == "水":
        return name in WATER_ALIASES

    return name == canonical_name


def find_ingredient(
    recipe: NormalizedRecipe,
    canonical_name: str,
) -> NormalizedIngredient | None:
    return next(
        (
            ingredient
            for ingredient in recipe.ingredients
            if ingredient_matches(
                ingredient,
                canonical_name,
            )
        ),
        None,
    )


def classify_existing_ingredients(
    recipe: NormalizedRecipe,
    quality: SemanticQuality,
) -> None:
    all_steps = "\n".join(
        instruction.text
        for instruction in recipe.instructions
    )

    for ingredient in recipe.ingredients:
        name = canonical_food_name(
            ingredient.food_name
        )

        ingredient.food_name = name

        if (
            ingredient.quantity_max
            is not None
        ):
            ingredient.amount_mode = "range"

        if (
            ingredient.amount_mode == "range"
            and (
                ingredient.quantity is None
                or ingredient.quantity_max is None
                or ingredient.quantity
                >= ingredient.quantity_max
            )
        ):
            append_unique(
                quality.blocking,
                (
                    f"食材“{name}”"
                    "的范围用量无效"
                ),
            )

        if (
            ingredient.amount_mode == "exact"
            and ingredient.quantity is None
        ):
            note = ingredient.note or ""

            if (
                TO_TASTE_PATTERN.search(note)
                or TO_TASTE_PATTERN.search(
                    all_steps
                )
            ):
                ingredient.amount_mode = (
                    "to_taste"
                )

            elif AS_NEEDED_PATTERN.search(
                note
            ):
                ingredient.amount_mode = (
                    "as_needed"
                )

            else:
                ingredient.amount_mode = (
                    "unspecified"
                )

        if (
            ingredient.role == "main"
            and name in SEASONING_NAMES
        ):
            ingredient.role = "seasoning"


def apply_process_ingredient(
    recipe: NormalizedRecipe,
    quality: SemanticQuality,
    *,
    canonical_name: str,
    aliases: tuple[str, ...],
) -> None:
    all_steps = "\n".join(
        instruction.text
        for instruction in recipe.instructions
    )

    if canonical_name == "食用油":
        used = bool(
            re.search(
                r"倒油|加油|放油|热油|"
                r"烧油|食用油|植物油",
                all_steps,
            )
        )
    else:
        used = any(
            alias in all_steps
            for alias in aliases
        )

    if not used:
        return

    mentions = amount_mentions(
        all_steps,
        aliases,
    )

    existing = find_ingredient(
        recipe,
        canonical_name,
    )

    grouped: dict[str, list[float]] = {}

    for quantity, unit in mentions:
        grouped.setdefault(
            unit,
            [],
        ).append(quantity)

    if mentions:
        if len(grouped) > 1:
            append_unique(
                quality.confirmation,
                (
                    f"步骤中“{canonical_name}”"
                    "出现多种无法直接合并的单位"
                ),
            )
            return

        unit = next(iter(grouped))
        total = sum(grouped[unit])

        if existing is None:
            recipe.ingredients.append(
                NormalizedIngredient(
                    food_name=canonical_name,
                    quantity=total,
                    unit=unit,
                    amount_mode="exact",
                    role="process",
                    note="根据步骤明确用量补全",
                    original_text=(
                        f"步骤中明确使用"
                        f"{canonical_name}"
                    ),
                )
            )

            return

        if (
            existing.quantity is not None
            and existing.unit is not None
        ):
            actual_unit = normalise_unit(
                existing.unit
            )

            if (
                actual_unit == unit
                and abs(
                    existing.quantity - total
                ) > 0.01
            ):
                append_unique(
                    quality.confirmation,
                    (
                        f"食材“{existing.food_name}”"
                        f"记录为 "
                        f"{existing.quantity:g}"
                        f"{actual_unit}，"
                        f"但步骤明确合计为 "
                        f"{total:g}{unit}"
                    ),
                )

        return

    coverage = (
        canonical_name == "水"
        and COVERAGE_PATTERN.search(
            all_steps
        )
    )

    mode = (
        "coverage"
        if coverage
        else "as_needed"
    )

    role = "process"

    semantic_note = (
        "以刚好淹没食材为准"
        if coverage
        else "按烹饪需要使用"
    )

    if existing is None:
        recipe.ingredients.append(
            NormalizedIngredient(
                food_name=canonical_name,
                quantity=None,
                quantity_max=None,
                unit=None,
                amount_mode=mode,
                role=role,
                note=semantic_note,
                original_text=(
                    f"步骤中提及"
                    f"{canonical_name}"
                ),
            )
        )

    else:
        generated_note = (
            existing.note
            and "根据步骤补全"
            in existing.note
        )

        if (
            existing.quantity is None
            or generated_note
        ):
            existing.quantity = None
            existing.quantity_max = None
            existing.unit = None
            existing.amount_mode = mode
            existing.role = role
            existing.note = append_note(
                existing.note,
                semantic_note,
            )


def apply_recipe_semantics(
    recipe: NormalizedRecipe,
) -> SemanticQuality:
    quality = SemanticQuality(
        blocking=[],
        confirmation=[],
        info=[],
        completion=[],
    )

    classify_existing_ingredients(
        recipe,
        quality,
    )

    apply_process_ingredient(
        recipe,
        quality,
        canonical_name="食用油",
        aliases=OIL_ALIASES,
    )

    apply_process_ingredient(
        recipe,
        quality,
        canonical_name="水",
        aliases=WATER_ALIASES,
    )

    rebuild_timers(
        recipe,
        quality,
    )

    return quality
