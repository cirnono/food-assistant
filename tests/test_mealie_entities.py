from __future__ import annotations

from typing import Any

import pytest

from app.ai_recipes import NormalizedRecipe
from app.mealie_entities import (
    EntityResolver,
    find_exact_entity,
    resolve_named_entity,
    resolve_recipe_entities,
    verify_native_structure,
)


class FakeWriter:
    def __init__(
        self,
        pages: dict[str, list[list[dict[str, Any]]]],
        *,
        create_error: Exception | None = None,
        refreshed_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
    ) -> None:
        self.pages = pages
        self.refreshed_pages = refreshed_pages or pages
        self.create_error = create_error
        self.get_calls: list[tuple[str, int]] = []
        self.post_calls = 0
        self.refreshing = False

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        params: dict[str, Any] | None = None,
        expected_statuses: set[int],
    ) -> Any:
        del expected_statuses
        if method == "GET":
            page = int((params or {}).get("page", 1))
            self.get_calls.append((path, page))
            source = self.refreshed_pages if self.refreshing else self.pages
            values = source.get(path, [])
            result = values[page - 1] if page <= len(values) else []
            if page >= len(values):
                self.refreshing = True
            return {"items": result}

        assert method == "POST"
        self.post_calls += 1
        if self.create_error is not None:
            raise self.create_error
        assert isinstance(payload, dict)
        return {"id": f"created-{self.post_calls}", **payload}


def entity(index: int, name: str, **extra: Any) -> dict[str, Any]:
    return {"id": f"entity-{index}", "name": name, **extra}


@pytest.mark.asyncio
async def test_paginated_lookup_finds_entity_after_first_hundred() -> None:
    first_page = [entity(index, f"food-{index}") for index in range(100)]
    writer = FakeWriter({"/api/foods": [first_page, [entity(101, "target")]]})

    result = await find_exact_entity(
        writer, kind="food", path="/api/foods", name="target"
    )

    assert result == {"id": "entity-101", "name": "target"}
    assert writer.get_calls == [("/api/foods", 1), ("/api/foods", 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["tag", "category"])
async def test_organizer_slug_and_group_conflict_is_recovered(kind: str) -> None:
    path = f"/api/organizers/{kind}s"
    conflict = RuntimeError(
        "HTTP 400: UNIQUE constraint failed: values.slug, values.group_id "
        "[parameters: ('new-id', 'abcdef123456', 'different', 'shared-slug')]"
    )
    recovered = entity(
        1,
        "existing",
        slug="shared-slug",
        groupId="abcdef-123456",
    )
    writer = FakeWriter(
        {path: [[]]},
        create_error=conflict,
        refreshed_pages={path: [[recovered]]},
    )
    summary: dict[str, list[dict[str, Any]]] = {}

    result = await resolve_named_entity(
        writer,
        kind=kind,
        path=path,
        name="requested",
        create_missing=True,
        summary=summary,
    )

    assert result is not None
    assert result["id"] == "entity-1"
    assert summary["recovered_after_conflict"][0]["id"] == "entity-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,path", [("food", "/api/foods"), ("unit", "/api/units")])
async def test_named_entity_unique_conflict_is_recovered(kind: str, path: str) -> None:
    conflict = RuntimeError(
        f"HTTP 400: UNIQUE constraint failed: {kind}s.name, {kind}s.group_id "
        "[parameters: ('new-id', 'group-1', 'target')]"
    )
    writer = FakeWriter(
        {path: [[]]},
        create_error=conflict,
        refreshed_pages={path: [[entity(1, "target", groupId="group-1")]]},
    )
    summary: dict[str, list[dict[str, Any]]] = {}

    result = await resolve_named_entity(
        writer,
        kind=kind,
        path=path,
        name="target",
        create_missing=True,
        summary=summary,
    )

    assert result is not None
    assert result["id"] == "entity-1"
    assert len(summary["recovered_after_conflict"]) == 1


@pytest.mark.asyncio
async def test_nfkc_whitespace_and_name_normalized_match() -> None:
    writer = FakeWriter(
        {"/api/foods": [[entity(1, "display", name_normalized="ABC")]]}
    )
    resolver = EntityResolver(writer)

    result = await resolver.find(
        kind="food", path="/api/foods", name="  ＡＢＣ\u3000"
    )

    assert result == {"id": "entity-1", "name": "display"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [RuntimeError("HTTP 500: upstream unavailable"), RuntimeError("HTTP 401")],
)
async def test_non_unique_errors_are_not_swallowed(error: Exception) -> None:
    writer = FakeWriter({"/api/foods": [[]]}, create_error=error)

    with pytest.raises(RuntimeError, match=str(error)):
        await resolve_named_entity(
            writer,
            kind="food",
            path="/api/foods",
            name="target",
            create_missing=True,
            summary={},
        )


@pytest.mark.asyncio
async def test_recipe_resolution_scans_each_collection_once() -> None:
    pages = {
        "/api/organizers/categories": [[entity(1, "主菜", slug="main")]],
        "/api/organizers/tags": [[entity(2, "tag", slug="tag")]],
        "/api/foods": [[entity(3, "food-a"), entity(4, "food-b")]],
        "/api/units": [[entity(5, "g")]],
    }
    writer = FakeWriter(pages)
    recipe = NormalizedRecipe.model_validate(
        {
            "name": "test",
            "original_name": "test",
            "cuisine": "中餐",
            "categories": ["主菜"],
            "tags": ["tag"],
            "ingredients": [
                {"food_name": "food-a", "unit": "g", "original_text": "a"},
                {"food_name": "food-b", "unit": "g", "original_text": "b"},
            ],
            "instructions": [{"step_number": 1, "text": "cook"}],
            "source": {"source_path": "test.md"},
            "import_score": 100,
            "recommendation": "import",
        }
    )

    await resolve_recipe_entities(writer, recipe, create_missing=True)

    assert writer.get_calls == [
        ("/api/organizers/categories", 1),
        ("/api/organizers/tags", 1),
        ("/api/foods", 1),
        ("/api/units", 1),
    ]


def test_native_verification_accepts_resolved_organizer_ids() -> None:
    recipe = NormalizedRecipe.model_validate(
        {
            "name": "test",
            "original_name": "test",
            "cuisine": "中餐",
            "categories": ["主菜"],
            "tags": ["陕西菜"],
            "ingredients": [{"food_name": "food", "original_text": "food"}],
            "instructions": [{"step_number": 1, "text": "cook"}],
            "source": {"source_path": "test.md"},
            "import_score": 100,
            "recommendation": "import",
        }
    )
    mealie_recipe = {
        "recipeCategory": [{"id": "category-id", "name": "主菜"}],
        "tags": [{"id": "tag-id", "name": "山西菜"}],
        "recipeIngredient": [{"food": {"name": "food"}, "unit": None}],
        "extras": {"foodAssistantSchemaVersion": "3"},
    }

    errors = verify_native_structure(
        recipe,
        mealie_recipe,
        resolved_categories=[{"id": "category-id", "name": "主菜"}],
        resolved_tags=[{"id": "tag-id", "name": "山西菜"}],
    )

    assert errors == []
