from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.mealie_client import (
    decode_response,
    mealie_get,
    raise_for_mealie_error,
)
from app.models import PantryItem


router = APIRouter(
    prefix="/api/v1/recommendations",
    tags=["recommendations"],
)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        str(value),
    ).casefold()

    # 保留汉字和字母数字，移除空格、标点等差异。
    return re.sub(r"[\W_]+", "", text)


def extract_page_items(payload: Any) -> list[dict[str, Any]]:
    """
    Support both Mealie pagination response variants:
    {"items": [...]} and {"data": [...]}.
    """
    if isinstance(payload, list):
        return [
            item for item in payload
            if isinstance(item, dict)
        ]

    if not isinstance(payload, dict):
        return []

    for key in ("items", "data"):
        value = payload.get(key)

        if isinstance(value, list):
            return [
                item for item in value
                if isinstance(item, dict)
            ]

    return []


def extract_recipe_ingredients(
    recipe: dict[str, Any],
) -> list[dict[str, Any]]:
    for key in (
        "recipeIngredient",
        "recipe_ingredient",
        "ingredients",
    ):
        value = recipe.get(key)

        if isinstance(value, list):
            return [
                item for item in value
                if isinstance(item, dict)
            ]

    return []


def food_name_from_ingredient(
    ingredient: dict[str, Any],
) -> str:
    food = ingredient.get("food")

    if isinstance(food, dict):
        name = food.get("name")

        if isinstance(name, str) and name.strip():
            return name.strip()

    return ""


def ingredient_label(
    ingredient: dict[str, Any],
) -> str:
    food_name = food_name_from_ingredient(ingredient)

    if food_name:
        return food_name

    for key in (
        "display",
        "originalText",
        "original_text",
        "note",
    ):
        value = ingredient.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    return "未命名食材"


def ingredient_search_text(
    ingredient: dict[str, Any],
) -> str:
    values: list[str] = []

    food_name = food_name_from_ingredient(ingredient)

    if food_name:
        values.append(food_name)

    for key in (
        "display",
        "originalText",
        "original_text",
        "note",
    ):
        value = ingredient.get(key)

        if isinstance(value, str) and value.strip():
            values.append(value)

    return normalize_text(" ".join(values))


def is_probable_heading(
    ingredient: dict[str, Any],
) -> bool:
    """
    Skip obvious section headings such as '酱汁：' or 'Ingredients:'.
    """
    food_name = food_name_from_ingredient(ingredient)

    if food_name:
        return False

    label = ingredient_label(ingredient).strip()

    if not label:
        return True

    if label.endswith((":", "：")):
        return True

    title = ingredient.get("title")
    display = ingredient.get("display")
    note = ingredient.get("note")

    return bool(
        title
        and not display
        and not note
    )


def inventory_matches_ingredient(
    inventory_name: str,
    ingredient_text: str,
) -> bool:
    inventory_normalized = normalize_text(
        inventory_name
    )

    if len(inventory_normalized) < 2:
        return False

    if not ingredient_text:
        return False

    return (
        inventory_normalized in ingredient_text
        or ingredient_text in inventory_normalized
    )


async def fetch_recipe_detail(
    slug: str,
    semaphore: asyncio.Semaphore,
) -> tuple[dict[str, Any] | None, str | None]:
    async with semaphore:
        response = await mealie_get(
            f"/api/recipes/{slug}"
        )

    if not response.is_success:
        return (
            None,
            f"HTTP {response.status_code}",
        )

    payload = decode_response(response)

    if not isinstance(payload, dict):
        return (
            None,
            "Unexpected recipe response",
        )

    return payload, None


@router.get("/preview")
async def recommendation_preview(
    max_recipes: int = Query(
        default=50,
        ge=1,
        le=200,
        description=(
            "Maximum number of Mealie recipes "
            "to evaluate"
        ),
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=50,
        description=(
            "Maximum number of recommendations "
            "to return"
        ),
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    today = date.today()

    inventory_statement = (
        select(PantryItem)
        .where(
            or_(
                PantryItem.expires_at.is_(None),
                PantryItem.expires_at >= today,
            ),
            or_(
                PantryItem.quantity.is_(None),
                PantryItem.quantity > 0,
                PantryItem.is_staple.is_(True),
            ),
        )
        .order_by(PantryItem.name.asc())
    )

    inventory = list(
        db.scalars(inventory_statement).all()
    )

    list_response = await mealie_get(
        "/api/recipes",
        params={
            "page": 1,
            "perPage": max_recipes,
            "orderBy": "name",
            "orderDirection": "asc",
        },
    )

    raise_for_mealie_error(
        list_response,
        "Unable to retrieve Mealie recipes",
    )

    list_payload = decode_response(list_response)
    recipe_summaries = extract_page_items(
        list_payload
    )

    semaphore = asyncio.Semaphore(5)

    fetch_jobs: list[
        tuple[dict[str, Any], Any]
    ] = []

    for summary in recipe_summaries:
        slug = summary.get("slug")

        if not isinstance(slug, str) or not slug:
            continue

        fetch_jobs.append(
            (
                summary,
                fetch_recipe_detail(
                    slug,
                    semaphore,
                ),
            )
        )

    fetched = await asyncio.gather(
        *(job for _, job in fetch_jobs)
    )

    recommendations: list[dict[str, Any]] = []
    detail_errors: list[dict[str, str]] = []

    for (
        summary,
        (recipe, error),
    ) in zip(
        (summary for summary, _ in fetch_jobs),
        fetched,
        strict=True,
    ):
        slug = str(summary.get("slug", ""))

        if recipe is None:
            detail_errors.append(
                {
                    "slug": slug,
                    "error": error or "Unknown error",
                }
            )
            continue

        ingredients = [
            ingredient
            for ingredient in extract_recipe_ingredients(
                recipe
            )
            if not is_probable_heading(ingredient)
        ]

        matched: list[dict[str, Any]] = []
        missing: list[str] = []
        expiring_matches: list[str] = []

        for ingredient in ingredients:
            label = ingredient_label(ingredient)
            search_text = ingredient_search_text(
                ingredient
            )

            matching_items = [
                item
                for item in inventory
                if inventory_matches_ingredient(
                    item.name,
                    search_text,
                )
            ]

            if matching_items:
                matched.append(
                    {
                        "ingredient": label,
                        "inventory_items": [
                            item.name
                            for item in matching_items
                        ],
                    }
                )

                for item in matching_items:
                    days = item.days_until_expiry

                    if (
                        days is not None
                        and 0 <= days <= 3
                        and item.name
                        not in expiring_matches
                    ):
                        expiring_matches.append(
                            item.name
                        )
            else:
                missing.append(label)

        total = len(ingredients)
        matched_count = len(matched)

        coverage = (
            matched_count / total
            if total > 0
            else 0.0
        )

        # 第一版透明评分：
        # 食材覆盖率为主体，临期食材增加优先级。
        score = round(
            coverage * 100
            + len(expiring_matches) * 12,
            1,
        )

        recommendations.append(
            {
                "name": (
                    recipe.get("name")
                    or summary.get("name")
                    or slug
                ),
                "slug": slug,
                "total_ingredients": total,
                "matched_ingredient_count": (
                    matched_count
                ),
                "missing_ingredient_count": (
                    len(missing)
                ),
                "coverage_percent": round(
                    coverage * 100,
                    1,
                ),
                "expiring_inventory_matches": (
                    expiring_matches
                ),
                "matched_ingredients": matched,
                "missing_ingredients": missing,
                "score": score,
            }
        )

    recommendations.sort(
        key=lambda item: (
            -item["score"],
            item["missing_ingredient_count"],
            str(item["name"]),
        )
    )

    return {
        "matching_version": 1,
        "warning": (
            "This preview uses ingredient-name matching. "
            "Manual aliases and preference scoring are "
            "not enabled yet."
        ),
        "inventory_items_used": [
            item.name for item in inventory
        ],
        "inventory_count": len(inventory),
        "recipes_found": len(recipe_summaries),
        "recipes_evaluated": len(recommendations),
        "recipe_detail_errors": detail_errors,
        "recommendations": recommendations[:limit],
    }
