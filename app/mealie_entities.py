from __future__ import annotations

import re
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


async def _entity_pages(
    writer: Any,
    *,
    path: str,
    search: str | None,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    """
    Read every available Mealie entity page.

    Some Mealie organizer searches do not return an existing
    entity even though its database uniqueness constraint still
    applies. A paginated fallback prevents duplicate creation.
    """
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    per_page = 100

    for page in range(
        1,
        max_pages + 1,
    ):
        params: dict[str, Any] = {
            "page": page,
            "perPage": per_page,
        }

        if search:
            params["search"] = search

        response = await writer.request_json(
            "GET",
            path,
            params=params,
            expected_statuses={200},
        )

        page_items = [
            item
            for item in extract_items(response)
            if isinstance(item, dict)
        ]

        new_count = 0

        for item in page_items:
            entity_id = str(
                item.get("id", "")
            )

            if (
                entity_id
                and entity_id in seen_ids
            ):
                continue

            if entity_id:
                seen_ids.add(entity_id)

            results.append(item)
            new_count += 1

        if len(page_items) < per_page:
            break

        # 防止服务端忽略 page 参数，反复返回第一页。
        if new_count == 0:
            break

    return results


def _entity_group_id(
    value: dict[str, Any],
) -> str | None:
    group_id = (
        value.get("groupId")
        or value.get("group_id")
    )

    if isinstance(group_id, str):
        return group_id

    return None


def _normalize_identifier(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold().replace("-", "")
    return normalized or None


def _unique_conflict_hints(
    error: Exception,
) -> dict[str, str]:
    text = str(error)

    # Mealie/SQLite 常见参数排列：
    # id, group_id, name, slug, ...
    match = re.search(
        r"\[parameters:\s*\(\s*"
        r"'[^']*'\s*,\s*"
        r"'(?P<group_id>[^']*)'\s*,\s*"
        r"'(?P<name>[^']*)'"
        r"(?:\s*,\s*'(?P<slug>[^']*)')?",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return {}

    return {
        key: value
        for key, value
        in match.groupdict().items()
        if value
    }


def _is_unique_entity_conflict(
    error: Exception,
) -> bool:
    text = str(error).casefold()

    return (
        "unique constraint failed"
        in text
        or "already exists" in text
    )


async def _find_entity_in_collection(
    writer: Any,
    *,
    kind: str,
    path: str,
    name: str,
    slug: str | None = None,
    group_id: str | None = None,
) -> dict[str, Any] | None:
    items = await _entity_pages(
        writer,
        path=path,
        search=None,
    )

    target_name = normalize_name(name)
    target_slug = (
        slug.strip().casefold()
        if isinstance(slug, str)
        else None
    )

    matches: list[dict[str, Any]] = []

    for item in items:
        item_group_id = _entity_group_id(
            item
        )

        if (
            group_id
            and item_group_id
            and item_group_id != group_id
        ):
            continue

        item_name = normalize_name(
            str(item.get("name", ""))
        )

        name_matches = (
            item_name == target_name
        )

        slug_matches = False

        if (
            kind in {"category", "tag"}
            and target_slug
        ):
            item_slug = str(
                item.get("slug", "")
            ).strip().casefold()

            slug_matches = (
                item_slug == target_slug
            )

        if name_matches or slug_matches:
            matches.append(item)

    if not matches:
        return None

    matches.sort(
        key=lambda item: str(
            item.get("id", "")
        )
    )

    return slim_entity(
        kind,
        matches[0],
    )


class EntityResolver:
    """Resolve Mealie entities with one collection scan per kind."""

    def __init__(self, writer: Any) -> None:
        self.writer = writer
        self._collections: dict[str, list[dict[str, Any]]] = {}
        self._paths: dict[str, str] = {}

    async def collection(
        self,
        *,
        kind: str,
        path: str,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        self._paths[kind] = path

        if refresh or kind not in self._collections:
            self._collections[kind] = await _entity_pages(
                self.writer,
                path=path,
                search=None,
            )

        return self._collections[kind]

    def _find(
        self,
        *,
        kind: str,
        name: str,
        slug: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any] | None:
        target_name = normalize_name(name)
        target_slug = (
            normalize_name(slug)
            if isinstance(slug, str)
            else None
        )
        items = self._collections.get(kind, [])

        def group_matches(item: dict[str, Any]) -> bool:
            if group_id is None:
                return True
            return _normalize_identifier(
                _entity_group_id(item)
            ) == _normalize_identifier(group_id)

        name_matches: list[dict[str, Any]] = []
        slug_matches: list[dict[str, Any]] = []

        for item in items:
            if not group_matches(item):
                continue

            names = [item.get("name")]
            if kind in {"food", "unit"}:
                names.append(
                    item.get("name_normalized")
                    or item.get("nameNormalized")
                )

            if any(
                isinstance(value, str)
                and normalize_name(value) == target_name
                for value in names
            ):
                name_matches.append(item)
                continue

            if kind in {"category", "tag"} and target_slug:
                item_slug = item.get("slug")
                if (
                    isinstance(item_slug, str)
                    and normalize_name(item_slug) == target_slug
                ):
                    slug_matches.append(item)

        matches = name_matches or slug_matches
        if not matches:
            return None

        matches.sort(key=lambda item: str(item.get("id", "")))
        return slim_entity(kind, matches[0])

    async def find(
        self,
        *,
        kind: str,
        path: str,
        name: str,
        slug: str | None = None,
        group_id: str | None = None,
        refresh: bool = False,
    ) -> dict[str, Any] | None:
        await self.collection(kind=kind, path=path, refresh=refresh)
        return self._find(
            kind=kind,
            name=name,
            slug=slug,
            group_id=group_id,
        )

    def remember(
        self,
        *,
        kind: str,
        value: dict[str, Any],
    ) -> None:
        self._collections.setdefault(kind, []).append(value)


async def find_exact_entity(
    writer: Any,
    *,
    kind: str,
    path: str,
    name: str,
) -> dict[str, Any] | None:
    resolver = EntityResolver(writer)
    return await resolver.find(
        kind=kind,
        path=path,
        name=name,
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
    resolver: EntityResolver | None = None,
) -> dict[str, Any] | None:
    clean_name = unicodedata.normalize("NFKC", name).strip()
    resolver = resolver or EntityResolver(writer)
    summary.setdefault("created", [])
    summary.setdefault("reused", [])
    summary.setdefault("missing", [])
    summary.setdefault("recovered_after_conflict", [])

    existing = await resolver.find(
        kind=kind,
        path=path,
        name=clean_name,
    )

    if existing is not None:
        summary["reused"].append(
            {
                "kind": kind,
                "name": clean_name,
                "id": existing["id"],
            }
        )

        return existing

    if not create_missing:
        summary["missing"].append(
            {
                "kind": kind,
                "name": clean_name,
            }
        )

        return None

    try:
        created = await writer.request_json(
            "POST",
            path,
            payload=create_payload(
                kind=kind,
                name=clean_name,
            ),
            expected_statuses={
                200,
                201,
            },
        )

    except Exception as exc:
        if not _is_unique_entity_conflict(
            exc
        ):
            raise

        hints = _unique_conflict_hints(
            exc
        )

        conflict_name = (
            hints.get("name")
            or clean_name
        ).strip()

        conflict_slug = hints.get(
            "slug"
        )

        # food/unit 的第 4 个参数不一定是 slug，
        # 只有 organizer 实体才使用该提示。
        if kind not in {
            "category",
            "tag",
        }:
            conflict_slug = None

        recovered = await resolver.find(
            kind=kind,
            path=path,
            name=conflict_name,
            slug=conflict_slug,
            group_id=hints.get("group_id"),
            refresh=True,
        )

        # 再按调用方原始名称兜底。
        if (
            recovered is None
            and normalize_name(
                conflict_name
            )
            != normalize_name(
                clean_name
            )
        ):
            recovered = resolver._find(
                kind=kind,
                name=clean_name,
                slug=conflict_slug,
                group_id=hints.get("group_id"),
            )

        if recovered is None:
            raise

        recovered_summary = {
            "kind": kind,
            "name": clean_name,
            "id": recovered["id"],
        }
        summary["reused"].append(recovered_summary)
        summary["recovered_after_conflict"].append(recovered_summary)

        return recovered

    if not isinstance(created, dict):
        raise RuntimeError(
            f"Invalid created Mealie "
            f"{kind} response: {created!r}"
        )

    entity = slim_entity(
        kind,
        created,
    )
    resolver.remember(kind=kind, value=created)

    summary["created"].append(
        {
            "kind": kind,
            "name": clean_name,
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
        "recovered_after_conflict": [],
    }
    resolver = EntityResolver(writer)

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
            resolver=resolver,
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
            resolver=resolver,
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
            resolver=resolver,
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
            resolver=resolver,
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
    *,
    resolved_categories: list[dict[str, Any]] | None = None,
    resolved_tags: list[dict[str, Any]] | None = None,
) -> list[str]:
    errors: list[str] = []

    category_values = mealie_recipe.get("recipeCategory", [])
    if resolved_categories is None:
        expected_categories = {normalize_name(name) for name in recipe.categories}
        actual_categories = {
            normalize_name(str(item.get("name", "")))
            for item in category_values
            if isinstance(item, dict)
        }
    else:
        expected_categories = {
            str(item.get("id", "")) for item in resolved_categories
        }
        actual_categories = {
            str(item.get("id", ""))
            for item in category_values
            if isinstance(item, dict)
        }

    if (
        expected_categories
        != actual_categories
    ):
        errors.append(
            "native category set mismatch"
        )

    tag_values = mealie_recipe.get("tags", [])
    if resolved_tags is None:
        expected_tags = {normalize_name(name) for name in recipe.tags}
        actual_tags = {
            normalize_name(str(item.get("name", "")))
            for item in tag_values
            if isinstance(item, dict)
        }
    else:
        expected_tags = {str(item.get("id", "")) for item in resolved_tags}
        actual_tags = {
            str(item.get("id", ""))
            for item in tag_values
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
