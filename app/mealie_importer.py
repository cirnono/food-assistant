from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.ai_recipes import NormalizedRecipe
from app.ingredient_policy import (
    inventory_policy_for_food,
)


MEALIE_BASE_URL = os.getenv(
    "MEALIE_BASE_URL",
    "http://host.docker.internal:9925",
).rstrip("/")

MEALIE_TIMEOUT_SECONDS = float(
    os.getenv(
        "MEALIE_TIMEOUT_SECONDS",
        "90",
    )
)


class MealieImportError(RuntimeError):
    pass


def read_mealie_token() -> str:
    environment_token = os.getenv("MEALIE_TOKEN", "").strip()
    if environment_token:
        return environment_token

    candidates: list[Path] = []

    configured_path = os.getenv(
        "MEALIE_TOKEN_FILE"
    )

    if configured_path:
        candidates.append(
            Path(configured_path)
        )

    candidates.extend(
        [
            Path(
                "/run/secrets/mealie_token"
            ),
            Path(
                "/secrets/mealie_token"
            ),
        ]
    )

    for path in candidates:
        if not path.is_file():
            continue

        token = path.read_text(
            encoding="utf-8"
        ).strip()

        if token:
            return token

    raise MealieImportError(
        "Mealie token is not configured or is empty"
    )


def build_import_key(
    *,
    source_id: int,
    source_recipe_id: int,
    source_content_sha256: str,
) -> str:
    return (
        f"{source_id}:"
        f"{source_recipe_id}:"
        f"{source_content_sha256}"
    )


def minutes_to_iso_duration(
    value: int | float | None,
) -> str | None:
    if value is None:
        return None

    total_seconds = round(
        float(value) * 60
    )

    if total_seconds <= 0:
        return None

    hours, remainder = divmod(
        total_seconds,
        3600,
    )

    minutes, seconds = divmod(
        remainder,
        60,
    )

    parts = ["PT"]

    if hours:
        parts.append(f"{hours}H")

    if minutes:
        parts.append(f"{minutes}M")

    if seconds:
        parts.append(f"{seconds}S")

    return "".join(parts)


def format_number(
    value: int | float,
) -> str:
    number = float(value)

    if number.is_integer():
        return str(int(number))

    return (
        f"{number:.3f}"
        .rstrip("0")
        .rstrip(".")
    )


def format_timer_duration(
    seconds: int,
) -> str:
    hours, remainder = divmod(
        int(seconds),
        3600,
    )

    minutes, remaining_seconds = divmod(
        remainder,
        60,
    )

    values: list[str] = []

    if hours:
        values.append(f"{hours} 小时")

    if minutes:
        values.append(f"{minutes} 分钟")

    if remaining_seconds:
        values.append(
            f"{remaining_seconds} 秒"
        )

    return " ".join(values) or "0 秒"


def ingredient_display(
    ingredient: Any,
) -> str:
    parts = [
        ingredient.food_name
    ]

    mode = getattr(
        ingredient,
        "amount_mode",
        "exact",
    )

    quantity_max = getattr(
        ingredient,
        "quantity_max",
        None,
    )

    if (
        mode == "range"
        and ingredient.quantity is not None
        and quantity_max is not None
    ):
        amount = (
            f"{format_number(
                ingredient.quantity
            )}–"
            f"{format_number(
                quantity_max
            )}"
        )

        if ingredient.unit:
            amount += ingredient.unit

        parts.append(amount)

    elif (
        mode == "exact"
        and ingredient.quantity is not None
    ):
        amount = format_number(
            ingredient.quantity
        )

        if ingredient.unit:
            amount += ingredient.unit

        parts.append(amount)

    elif mode == "as_needed":
        parts.append("适量")

    elif mode == "coverage":
        parts.append("按覆盖程度")

    elif mode == "to_taste":
        parts.append("按口味")

    elif mode == "unspecified":
        parts.append("用量未注明")

    value = " ".join(parts)

    role = getattr(
        ingredient,
        "role",
        "main",
    )

    role_labels = {
        "process": "工艺耗材",
        "seasoning": "调味料",
        "garnish": "装饰配料",
    }

    if role in role_labels:
        value += (
            f"【{role_labels[role]}】"
        )

    if ingredient.note:
        value += f"（{ingredient.note}）"

    if ingredient.optional:
        value += "【可选】"

    return value


def instruction_text(
    instruction: Any,
) -> str:
    text = instruction.text.strip()

    if not instruction.timers:
        return text

    timer_lines: list[str] = []

    for timer in instruction.timers:
        kind = getattr(
            timer,
            "kind",
            "fixed",
        )

        if kind == "range":
            minimum = getattr(
                timer,
                "duration_min_seconds",
                None,
            )

            maximum = getattr(
                timer,
                "duration_max_seconds",
                None,
            )

            if (
                minimum is None
                or maximum is None
            ):
                continue

            duration = (
                f"{format_timer_duration(
                    minimum
                )}–"
                f"{format_timer_duration(
                    maximum
                )}"
            )

        else:
            if timer.duration_seconds is None:
                continue

            duration = format_timer_duration(
                timer.duration_seconds
            )

        suffix = (
            ""
            if getattr(
                timer,
                "accepted",
                True,
            )
            else "（建议，未确认）"
        )

        timer_lines.append(
            f"- {timer.name}："
            f"{duration}{suffix}"
        )

    if not timer_lines:
        return text

    return (
        text
        + "\n\n"
        + "**计时器**\n"
        + "\n".join(timer_lines)
    )


def build_mealie_ingredients(
    recipe: NormalizedRecipe,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []

    for ingredient in recipe.ingredients:
        display = ingredient_display(
            ingredient
        )

        values.append(
            {
                "quantity": (
                    float(
                        ingredient.quantity
                    )
                    if ingredient.quantity
                    is not None
                    else 0.0
                ),
                "unit": None,
                "food": None,
                "referencedRecipe": None,
                "note": display,
                "display": display,
                "title": None,
                "originalText": (
                    ingredient.original_text
                    or display
                ),
                "referenceId": str(
                    uuid.uuid4()
                ),
            }
        )

    return values


def build_mealie_native_ingredients(
    recipe: NormalizedRecipe,
    *,
    foods: dict[str, dict[str, Any]],
    units: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []

    for ingredient in recipe.ingredients:
        food = foods.get(
            ingredient.food_name
        )

        if food is None:
            raise MealieImportError(
                "Missing resolved native food: "
                f"{ingredient.food_name}"
            )

        unit = None

        if ingredient.unit:
            unit = units.get(
                ingredient.unit
            )

            if unit is None:
                raise MealieImportError(
                    "Missing resolved native unit: "
                    f"{ingredient.unit}"
                )

        display = ingredient_display(
            ingredient
        )

        values.append(
            {
                "quantity": (
                    float(
                        ingredient.quantity
                    )
                    if (
                        ingredient.quantity
                        is not None
                        and getattr(
                            ingredient,
                            "amount_mode",
                            "exact",
                        ) == "exact"
                    )
                    else None
                ),
                "unit": unit,
                "food": food,
                "referencedRecipe": None,
                "note": (
                    ingredient.note
                    or ""
                ),
                "display": display,
                "title": None,
                "originalText": (
                    ingredient.original_text
                    or display
                ),
                "referenceId": str(
                    uuid.uuid4()
                ),
            }
        )

    return values


def build_mealie_instructions(
    recipe: NormalizedRecipe,
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(uuid.uuid4()),
            "title": (
                f"步骤 "
                f"{instruction.step_number}"
            ),
            "summary": "",
            "text": instruction_text(
                instruction
            ),
            "ingredientReferences": [],
        }
        for instruction
        in recipe.instructions
    ]


def build_mealie_extras(
    recipe: NormalizedRecipe,
    *,
    import_key: str,
    source_commit: str | None,
    source_content_sha256: str,
    schema_version: int = 1,
) -> dict[str, Any]:
    inventory_policies = {
        ingredient.food_name: (
            "ignore"
            if getattr(
                ingredient,
                "role",
                "main",
            ) == "process"
            else inventory_policy_for_food(
                ingredient.food_name
            )
        )
        for ingredient in recipe.ingredients
    }

    ingredient_semantics = [
        {
            "food_name": ingredient.food_name,
            "amount_mode": getattr(
                ingredient,
                "amount_mode",
                "exact",
            ),
            "quantity": ingredient.quantity,
            "quantity_max": getattr(
                ingredient,
                "quantity_max",
                None,
            ),
            "unit": ingredient.unit,
            "role": getattr(
                ingredient,
                "role",
                "main",
            ),
            "note": ingredient.note,
        }
        for ingredient in recipe.ingredients
    ]

    timers = [
        {
            "step_number": instruction.step_number,
            "timers": [
                timer.model_dump(
                    mode="json"
                )
                for timer in instruction.timers
            ],
        }
        for instruction in recipe.instructions
        if instruction.timers
    ]

    return {
        "foodAssistantManaged": True,
        "foodAssistantSchemaVersion": str(
            schema_version
        ),
        "foodAssistantImportKey": (
            import_key
        ),
        "foodAssistantSourceName": (
            recipe.source.source_name
        ),
        "foodAssistantSourcePath": (
            recipe.source.source_path
        ),
        "foodAssistantSourceCommit": (
            source_commit or ""
        ),
        "foodAssistantSourceSha256": (
            source_content_sha256
        ),
        "foodAssistantCuisine": (
            recipe.cuisine
        ),
        "foodAssistantCategories": (
            json.dumps(
                recipe.categories,
                ensure_ascii=False,
            )
        ),
        "foodAssistantTags": (
            json.dumps(
                recipe.tags,
                ensure_ascii=False,
            )
        ),
        "foodAssistantWarnings": (
            json.dumps(
                recipe.warnings,
                ensure_ascii=False,
            )
        ),
        "foodAssistantInventoryPolicies": (
            json.dumps(
                inventory_policies,
                ensure_ascii=False,
            )
        ),
        "foodAssistantIngredientSemantics": (
            json.dumps(
                ingredient_semantics,
                ensure_ascii=False,
            )
        ),
        "foodAssistantTimers": (
            json.dumps(
                timers,
                ensure_ascii=False,
            )
        ),
        "foodAssistantImportScore": (
            recipe.import_score
        ),
        "foodAssistantReviewRequired": (
            recipe.review_required
        ),
    }


def build_mealie_patch_payload(
    recipe: NormalizedRecipe,
    *,
    blank_recipe: dict[str, Any],
    import_key: str,
    source_url: str,
    source_commit: str | None,
    source_content_sha256: str,
    native_categories: (
        list[dict[str, Any]] | None
    ) = None,
    native_tags: (
        list[dict[str, Any]] | None
    ) = None,
    native_ingredients: (
        list[dict[str, Any]] | None
    ) = None,
) -> dict[str, Any]:
    servings = (
        float(recipe.servings)
        if recipe.servings is not None
        else 0.0
    )

    recipe.source.source_url = source_url

    return {
        "id": blank_recipe.get("id"),
        "userId": blank_recipe.get(
            "userId"
        ),
        "householdId": blank_recipe.get(
            "householdId"
        ),
        "groupId": blank_recipe.get(
            "groupId"
        ),

        "name": recipe.name,
        "slug": blank_recipe.get(
            "slug",
            "",
        ),
        "image": blank_recipe.get(
            "image"
        ),

        "recipeServings": servings,
        "recipeYieldQuantity": servings,
        "recipeYield": (
            f"{format_number(servings)} 人份"
            if servings > 0
            else None
        ),

        "totalTime": (
            minutes_to_iso_duration(
                recipe.total_time_minutes
            )
        ),
        "prepTime": (
            minutes_to_iso_duration(
                recipe.prep_time_minutes
            )
        ),
        "cookTime": (
            minutes_to_iso_duration(
                recipe.cook_time_minutes
            )
        ),
        "performTime": None,

        "description": recipe.description,

        "recipeCategory": (
            native_categories
            if native_categories
            is not None
            else []
        ),
        "tags": (
            native_tags
            if native_tags
            is not None
            else []
        ),
        "tools": [],

        "rating": None,
        "orgURL": source_url,

        "dateAdded": blank_recipe.get(
            "dateAdded"
        ),
        "dateUpdated": blank_recipe.get(
            "dateUpdated"
        ),
        "createdAt": blank_recipe.get(
            "createdAt"
        ),
        "lastMade": blank_recipe.get(
            "lastMade"
        ),

        "recipeIngredient": (
            native_ingredients
            if native_ingredients
            is not None
            else build_mealie_ingredients(
                recipe
            )
        ),
        "recipeInstructions": (
            build_mealie_instructions(
                recipe
            )
        ),

        "nutrition": blank_recipe.get(
            "nutrition"
        ),
        "settings": blank_recipe.get(
            "settings"
        ),

        "assets": blank_recipe.get(
            "assets",
            [],
        ),
        "notes": blank_recipe.get(
            "notes",
            [],
        ),

        "extras": build_mealie_extras(
            recipe,
            import_key=import_key,
            source_commit=source_commit,
            source_content_sha256=(
                source_content_sha256
            ),
            schema_version=(
                3
                if native_ingredients
                is not None
                else 1
            ),
        ),

        "comments": blank_recipe.get(
            "comments",
            [],
        ),
    }


def build_mealie_preview(
    recipe: NormalizedRecipe,
    *,
    import_key: str,
    source_url: str,
    source_commit: str | None,
    source_content_sha256: str,
) -> dict[str, Any]:
    return {
        "name": recipe.name,
        "source_url": source_url,
        "import_key": import_key,

        "servings": recipe.servings,
        "prep_time": (
            minutes_to_iso_duration(
                recipe.prep_time_minutes
            )
        ),
        "cook_time": (
            minutes_to_iso_duration(
                recipe.cook_time_minutes
            )
        ),
        "total_time": (
            minutes_to_iso_duration(
                recipe.total_time_minutes
            )
        ),

        "ingredients": [
            {
                "display": (
                    ingredient_display(
                        ingredient
                    )
                ),
                "inventory_policy": (
                    inventory_policy_for_food(
                        ingredient.food_name
                    )
                ),
            }
            for ingredient
            in recipe.ingredients
        ],

        "instructions": [
            {
                "title": (
                    f"步骤 "
                    f"{instruction.step_number}"
                ),
                "text": instruction_text(
                    instruction
                ),
            }
            for instruction
            in recipe.instructions
        ],

        "normalized_categories": (
            recipe.categories
        ),
        "normalized_tags": recipe.tags,

        "warnings": recipe.warnings,
        "review_required": (
            recipe.review_required
        ),

        "mealie_organizers_deferred": True,

        "extras": build_mealie_extras(
            recipe,
            import_key=import_key,
            source_commit=source_commit,
            source_content_sha256=(
                source_content_sha256
            ),
        ),
    }


def verify_mealie_recipe(
    recipe: NormalizedRecipe,
    *,
    mealie_recipe: dict[str, Any],
    import_key: str,
) -> None:
    errors: list[str] = []

    if (
        mealie_recipe.get("name")
        != recipe.name
    ):
        errors.append(
            "recipe name mismatch"
        )

    ingredients = mealie_recipe.get(
        "recipeIngredient"
    )

    if not isinstance(ingredients, list):
        errors.append(
            "recipeIngredient is not a list"
        )
    elif len(ingredients) != len(
        recipe.ingredients
    ):
        errors.append(
            "ingredient count mismatch: "
            f"expected={len(recipe.ingredients)}, "
            f"received={len(ingredients)}"
        )

    instructions = mealie_recipe.get(
        "recipeInstructions"
    )

    if not isinstance(
        instructions,
        list,
    ):
        errors.append(
            "recipeInstructions is not a list"
        )
    elif len(instructions) != len(
        recipe.instructions
    ):
        errors.append(
            "instruction count mismatch: "
            f"expected={len(recipe.instructions)}, "
            f"received={len(instructions)}"
        )

    extras = mealie_recipe.get(
        "extras"
    )

    if not isinstance(extras, dict):
        errors.append(
            "extras is not an object"
        )
    elif extras.get(
        "foodAssistantImportKey"
    ) != import_key:
        errors.append(
            "foodAssistantImportKey mismatch"
        )

    if errors:
        raise MealieImportError(
            "Mealie read-back verification "
            "failed: "
            + "; ".join(errors)
        )


class MealieWriter:
    def __init__(self) -> None:
        self.token = read_mealie_token()

        self.headers = {
            "Authorization": (
                f"Bearer {self.token}"
            ),
            "Accept": "application/json",
        }

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        params: dict[str, Any] | None = None,
        expected_statuses: set[int],
    ) -> Any:
        headers = dict(self.headers)

        if payload is not None:
            headers[
                "Content-Type"
            ] = "application/json"

        url = (
            f"{MEALIE_BASE_URL}"
            f"{path}"
        )

        try:
            async with httpx.AsyncClient(
                timeout=MEALIE_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=payload,
                    params=params,
                )

        except httpx.HTTPError as exc:
            raise MealieImportError(
                f"{method} {path} failed: "
                f"{exc.__class__.__name__}: "
                f"{exc}"
            ) from exc

        if (
            response.status_code
            not in expected_statuses
        ):
            body = response.text[:4000]

            raise MealieImportError(
                f"{method} {path} -> "
                f"HTTP {response.status_code}: "
                f"{body}"
            )

        if not response.content:
            return None

        try:
            return response.json()
        except ValueError as exc:
            raise MealieImportError(
                f"{method} {path} returned "
                "invalid JSON"
            ) from exc

    async def create_blank_recipe(
        self,
        name: str,
    ) -> str:
        value = await self.request_json(
            "POST",
            "/api/recipes",
            payload={"name": name},
            expected_statuses={201},
        )

        if (
            not isinstance(value, str)
            or not value
        ):
            raise MealieImportError(
                "POST /api/recipes did not "
                "return a valid slug"
            )

        return value

    async def get_recipe(
        self,
        slug: str,
    ) -> dict[str, Any]:
        value = await self.request_json(
            "GET",
            (
                "/api/recipes/"
                + quote(slug, safe="")
            ),
            expected_statuses={200},
        )

        if not isinstance(value, dict):
            raise MealieImportError(
                "Mealie recipe response is "
                "not an object"
            )

        return value

    async def patch_recipe(
        self,
        slug: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        value = await self.request_json(
            "PATCH",
            (
                "/api/recipes/"
                + quote(slug, safe="")
            ),
            payload=payload,
            expected_statuses={200},
        )

        if not isinstance(value, dict):
            raise MealieImportError(
                "Mealie PATCH response is "
                "not an object"
            )

        return value

    async def delete_recipe(
        self,
        slug: str,
    ) -> None:
        await self.request_json(
            "DELETE",
            (
                "/api/recipes/"
                + quote(slug, safe="")
            ),
            expected_statuses={
                200,
                204,
            },
        )
