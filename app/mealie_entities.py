from __future__ import annotations

import unicodedata
from typing import Any

from app.ai_recipes import NormalizedRecipe
from app.ingredient_policy import (
    inventory_policy_for_food,
)


COUNT_UNITS = {
    "个",
    "只",
    "瓣",
    "棵",
    "颗",
    "枚",
    "条",
    "片",
    "根",
    "朵",
    "包",
    "袋",
    "盒",
    "罐",
    "瓶",
    "碗",
    "杯",
    "勺",
}


def normalize_name(
    value: str,
) -> str:
    return (
        unicodedata.normalize(
            "NFKC",
            value,
        )
        .strip()
        .casefold()
    )


def unique_names(
    values: list[str],
) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for raw_value in values:
        value = raw_value.strip()

        if not value:
            continue

        key = normalize_name(value)

        if key in seen:
            continue

        seen.add(key)
        results.append(value)

    return results


def extract_items(
    value: Any,
) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [
            item
            for item in value
            if isinstance(item, dict)
        ]

    if isinstance(value, dict):
        items = value.get("items", [])

        if isinstance(items, list):
            return [
                item
                for item in items
                if isinstance(item, dict)
            ]

    return []


def slim_entity(
    kind: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    entity_id = value.get("id")
    name = value.get("name")

    if (
        not isinstance(entity_id, str)
        or not entity_id
        or not isinstance(name, str)
        or not name
    ):
        raise RuntimeError(
            f"Invalid Mealie {kind} entity: "
            f"{value!r}"
        )

    if kind in {
        "category",
        "tag",
    }:
        slug = value.get("slug")

        if (
            not isinstance(slug, str)
            or not slug
        ):
            raise RuntimeError(
                f"Mealie {kind} has no slug: "
                f"{value!r}"
            )

        result = {
            "id": entity_id,
            "name": name,
            "slug": slug,
        }

        group_id = value.get("groupId")

        if isinstance(group_id, str):
            result["groupId"] = group_id

        return result

    return {
        "id": entity_id,
        "name": name,
    }


async def find_exact_entity(
    writer: Any,
    *,
    kind: str,
    path: str,
    name: str,
) -> dict[str, Any] | None:
    response = await writer.request_json(
        "GET",
        path,
        params={
            "search": name,
            "page": 1,
            "perPage": 100,
        },
        expected_statuses={200},
    )

    target = normalize_name(name)

    exact_matches = [
        item
        for item in extract_items(response)
        if normalize_name(
            str(item.get("name", ""))
        ) == target
    ]

    if not exact_matches:
        return None

    exact_matches.sort(
        key=lambda item: str(
            item.get("id", "")
        )
    )

    return slim_entity(
        kind,
        exact_matches[0],
    )


def create_payload(
    *,
    kind: str,
    name: str,
) -> dict[str, Any]:
    if kind in {
        "category",
        "tag",
    }:
        return {
            "name": name,
        }

    if kind == "food":
        return {
            "name": name,
            "description": "",
            "extras": {
                "foodAssistantManaged": True,
                "inventoryPolicy": (
                    inventory_policy_for_food(
                        name
                    )
                ),
            },
            "aliases": [],
        }

    if kind == "unit":
        return {
            "name": name,
            "description": "",
            "fraction": (
                name not in COUNT_UNITS
            ),
            "abbreviation": name,
            "pluralAbbreviation": name,
            "useAbbreviation": False,
            "aliases": [],
        }

    raise ValueError(
        f"Unsupported entity kind: {kind}"
    )


async def resolve_named_entity(
    writer: Any,
    *,
    kind: str,
    path: str,
    name: str,
    create_missing: bool,
    summary: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    existing = await find_exact_entity(
        writer,
        kind=kind,
        path=path,
        name=name,
    )

    if existing is not None:
        summary["reused"].append(
            {
                "kind": kind,
                "name": name,
                "id": existing["id"],
            }
        )

        return existing

    if not create_missing:
        summary["missing"].append(
            {
                "kind": kind,
                "name": name,
            }
        )

        return None

    try:
        created = await writer.request_json(
            "POST",
            path,
            payload=create_payload(
                kind=kind,
                name=name,
            ),
            expected_statuses={
                200,
                201,
            },
        )

    except Exception:
        # 处理并发创建：创建请求失败后重新查询。
        existing = await find_exact_entity(
            writer,
            kind=kind,
            path=path,
            name=name,
        )

        if existing is None:
            raise

        summary["reused"].append(
            {
                "kind": kind,
                "name": name,
                "id": existing["id"],
                "resolved_after_create_error": True,
            }
        )

        return existing

    if not isinstance(created, dict):
        raise RuntimeError(
            f"Mealie {kind} creation did "
            "not return an object"
        )

    entity = slim_entity(
        kind,
        created,
    )

    summary["created"].append(
        {
            "kind": kind,
            "name": name,
            "id": entity["id"],
        }
    )

    return entity


async def resolve_recipe_entities(
    writer: Any,
    recipe: NormalizedRecipe,
    *,
    create_missing: bool,
) -> dict[str, Any]:
    summary: dict[
        str,
        list[dict[str, Any]],
    ] = {
        "created": [],
        "reused": [],
        "missing": [],
    }

    categories: list[dict[str, Any]] = []

    for name in unique_names(
        list(recipe.categories)
    ):
        entity = await resolve_named_entity(
            writer,
            kind="category",
            path=(
                "/api/organizers/categories"
            ),
            name=name,
            create_missing=create_missing,
            summary=summary,
        )

        if entity is not None:
            categories.append(entity)

    tags: list[dict[str, Any]] = []

    for name in unique_names(
        list(recipe.tags)
    ):
        entity = await resolve_named_entity(
            writer,
            kind="tag",
            path="/api/organizers/tags",
            name=name,
            create_missing=create_missing,
            summary=summary,
        )

        if entity is not None:
            tags.append(entity)

    foods: dict[
        str,
        dict[str, Any],
    ] = {}

    units: dict[
        str,
        dict[str, Any],
    ] = {}

    food_names = unique_names(
        [
            ingredient.food_name
            for ingredient
            in recipe.ingredients
        ]
    )

    unit_names = unique_names(
        [
            ingredient.unit
            for ingredient
            in recipe.ingredients
            if ingredient.unit
        ]
    )

    for name in food_names:
        entity = await resolve_named_entity(
            writer,
            kind="food",
            path="/api/foods",
            name=name,
            create_missing=create_missing,
            summary=summary,
        )

        if entity is not None:
            foods[name] = entity

    for name in unit_names:
        entity = await resolve_named_entity(
            writer,
            kind="unit",
            path="/api/units",
            name=name,
            create_missing=create_missing,
            summary=summary,
        )

        if entity is not None:
            units[name] = entity

    return {
        "categories": categories,
        "tags": tags,
        "foods": foods,
        "units": units,
        "summary": summary,
    }


def verify_native_structure(
    recipe: NormalizedRecipe,
    mealie_recipe: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    expected_categories = {
        normalize_name(name)
        for name in recipe.categories
    }

    actual_categories = {
        normalize_name(
            str(item.get("name", ""))
        )
        for item in mealie_recipe.get(
            "recipeCategory",
            [],
        )
        if isinstance(item, dict)
    }

    if (
        expected_categories
        != actual_categories
    ):
        errors.append(
            "native category set mismatch"
        )

    expected_tags = {
        normalize_name(name)
        for name in recipe.tags
    }

    actual_tags = {
        normalize_name(
            str(item.get("name", ""))
        )
        for item in mealie_recipe.get(
            "tags",
            [],
        )
        if isinstance(item, dict)
    }

    if expected_tags != actual_tags:
        errors.append(
            "native tag set mismatch"
        )

    mealie_ingredients = (
        mealie_recipe.get(
            "recipeIngredient",
            [],
        )
    )

    if (
        not isinstance(
            mealie_ingredients,
            list,
        )
        or len(mealie_ingredients)
        != len(recipe.ingredients)
    ):
        errors.append(
            "native ingredient count mismatch"
        )

    else:
        for index, (
            expected,
            actual,
        ) in enumerate(
            zip(
                recipe.ingredients,
                mealie_ingredients,
                strict=True,
            ),
            start=1,
        ):
            if not isinstance(actual, dict):
                errors.append(
                    f"ingredient {index} "
                    "is not an object"
                )
                continue

            food = actual.get("food")

            if not isinstance(food, dict):
                errors.append(
                    f"ingredient {index} "
                    "has no native food"
                )
            elif normalize_name(
                str(food.get("name", ""))
            ) != normalize_name(
                expected.food_name
            ):
                errors.append(
                    f"ingredient {index} "
                    "food mismatch"
                )

            unit = actual.get("unit")

            if expected.unit:
                if not isinstance(unit, dict):
                    errors.append(
                        f"ingredient {index} "
                        "has no native unit"
                    )
                elif normalize_name(
                    str(
                        unit.get(
                            "name",
                            "",
                        )
                    )
                ) != normalize_name(
                    expected.unit
                ):
                    errors.append(
                        f"ingredient {index} "
                        "unit mismatch"
                    )

    extras = mealie_recipe.get(
        "extras",
        {},
    )

    if not isinstance(extras, dict):
        errors.append(
            "extras is not an object"
        )
    else:
        raw_schema_version = extras.get(
            "foodAssistantSchemaVersion"
        )

        try:
            schema_version = int(
                raw_schema_version
            )
        except (
            TypeError,
            ValueError,
        ):
            schema_version = None

        if schema_version not in {
            2,
            3,
        }:
            errors.append(
                "foodAssistantSchemaVersion "
                f"is unsupported: "
                f"{raw_schema_version!r}"
            )

    return errors
