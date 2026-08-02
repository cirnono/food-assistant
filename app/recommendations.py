from __future__ import annotations

import asyncio
import random
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingredient_names import alias_map, canonicalize, normalize_name
from app.ingredient_policy import inventory_policy_for_food
from app.mealie_client import MEALIE_BASE_URL, decode_response, mealie_get, raise_for_mealie_error
from app.models import CookingHistory, PantryItem


router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])

SCORE = {"coverage": 100, "expiring": 15, "missing_main": -20, "missing_regular": -6, "recent": -25}
DETAIL_CONCURRENCY = 5
PAGE_SIZE = 100
TOOLS = {"锅", "炒锅", "烤箱", "刀", "菜刀", "砧板", "搅拌碗", "打蛋器", "料理机", "设备", "工具"}


def normalize_text(value: Any) -> str:
    return normalize_name(value)


def extract_page_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
    return []


def has_next_page(payload: Any, page: int, count: int) -> bool:
    if not isinstance(payload, dict):
        return count >= PAGE_SIZE
    if isinstance(payload.get("next"), (str, int)) or payload.get("next") is True:
        return True
    total_pages = payload.get("total_pages", payload.get("totalPages"))
    if isinstance(total_pages, int):
        return page < total_pages
    total = payload.get("total")
    return isinstance(total, int) and page * PAGE_SIZE < total if total is not None else count >= PAGE_SIZE


def extract_recipe_ingredients(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("recipeIngredient", "recipe_ingredient", "ingredients"):
        if isinstance(recipe.get(key), list):
            return [x for x in recipe[key] if isinstance(x, dict)]
    return []


def food_name_from_ingredient(ingredient: dict[str, Any]) -> str:
    food = ingredient.get("food")
    return str(food.get("name", "")).strip() if isinstance(food, dict) else ""


def ingredient_label(ingredient: dict[str, Any]) -> str:
    for value in (food_name_from_ingredient(ingredient), ingredient.get("display"), ingredient.get("originalText"), ingredient.get("original_text"), ingredient.get("note")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "未命名食材"


def ingredient_search_text(ingredient: dict[str, Any]) -> str:
    return normalize_name(" ".join(str(v) for v in (food_name_from_ingredient(ingredient), ingredient.get("display", ""), ingredient.get("originalText", ""), ingredient.get("note", "")) if v))


def is_probable_heading(ingredient: dict[str, Any]) -> bool:
    label = ingredient_label(ingredient)
    return not food_name_from_ingredient(ingredient) and (label.endswith((":", "：")) or bool(ingredient.get("title") and not ingredient.get("display") and not ingredient.get("note")))


def _extras(ingredient: dict[str, Any]) -> dict[str, Any]:
    value = ingredient.get("extras")
    return value if isinstance(value, dict) else {}


def ignored_ingredient(ingredient: dict[str, Any]) -> bool:
    extras = _extras(ingredient)
    label = ingredient_label(ingredient)
    normalized = normalize_name(food_name_from_ingredient(ingredient) or label)
    role = str(extras.get("role", ingredient.get("role", ""))).casefold()
    policy = str(extras.get("inventory_policy", ingredient.get("inventory_policy", ""))).casefold()
    return is_probable_heading(ingredient) or policy == "ignore" or role == "process" or inventory_policy_for_food(label) == "ignore" or any(normalize_name(tool) in normalized for tool in TOOLS)


def is_main_ingredient(ingredient: dict[str, Any]) -> bool:
    extras = _extras(ingredient)
    role = str(extras.get("role", ingredient.get("role", ""))).casefold()
    return role in {"main", "primary", "主料", "主食材"} or bool(extras.get("is_main", ingredient.get("is_main", False)))


def inventory_matches_ingredient(inventory_name: str, ingredient_text: str, aliases: dict[str, str] | None = None) -> bool:
    mapping = aliases or {}
    left = canonicalize(inventory_name, mapping)
    right = canonicalize(ingredient_text, mapping)
    return bool(left and right and (left == right or (len(left) >= 2 and left in right) or (len(right) >= 2 and right in left)))


async def fetch_recipe_detail(slug: str, semaphore: asyncio.Semaphore) -> tuple[dict[str, Any] | None, str | None]:
    async with semaphore:
        response = await mealie_get(f"/api/recipes/{slug}")
    if not response.is_success:
        return None, f"HTTP {response.status_code}"
    payload = decode_response(response)
    return (payload, None) if isinstance(payload, dict) else (None, "Unexpected recipe response")


async def fetch_all_summaries() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    page = 1
    while True:
        response = await mealie_get("/api/recipes", params={"page": page, "perPage": PAGE_SIZE, "orderBy": "name", "orderDirection": "asc"})
        raise_for_mealie_error(response, "Unable to retrieve Mealie recipes")
        payload = decode_response(response)
        items = extract_page_items(payload)
        result.extend(items)
        if not has_next_page(payload, page, len(items)) or not items:
            return result
        page += 1


def _text_value(recipe: dict[str, Any], key: str) -> str | None:
    value = recipe.get(key)
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, list):
        value = ", ".join(str(x.get("name", "")) if isinstance(x, dict) else str(x) for x in value)
    return str(value).strip() if value else None


def _minutes(recipe: dict[str, Any]) -> int | None:
    for key in ("totalTime", "total_time", "totalTimeMinutes", "total_time_minutes"):
        value = recipe.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    prep, perform = recipe.get("prepTime"), recipe.get("performTime")
    return int((prep or 0) + (perform or 0)) if isinstance(prep, (int, float)) and isinstance(perform, (int, float)) else None


async def build_recommendations(db: Session, *, limit: int, max_missing: int, max_total_time: int | None, category: str | None, cuisine: str | None, owner: str | None, use_expiring: bool, randomize: bool, seed: int | None) -> dict[str, Any]:
    today = date.today()
    inventory = list(db.scalars(select(PantryItem).where(or_(PantryItem.expires_at.is_(None), PantryItem.expires_at >= today), or_(PantryItem.quantity.is_(None), PantryItem.quantity > 0), *((PantryItem.owner == owner,) if owner else ())).order_by(PantryItem.name)).all())
    aliases = alias_map(db)
    summaries = await fetch_all_summaries()
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    cache: dict[str, tuple[dict[str, Any] | None, str | None]] = {}

    async def cached(slug: str) -> tuple[dict[str, Any] | None, str | None]:
        if slug not in cache:
            cache[slug] = await fetch_recipe_detail(slug, semaphore)
        return cache[slug]

    valid = [(s, str(s.get("slug", ""))) for s in summaries if s.get("slug")]
    details = await asyncio.gather(*(cached(slug) for _, slug in valid))
    recent_cutoff = today - timedelta(days=7)
    recent = set(db.scalars(select(CookingHistory.mealie_slug).where(CookingHistory.cooked_at >= recent_cutoff, *((CookingHistory.owner == owner,) if owner else ()))).all())
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for (summary, slug), (recipe, error) in zip(valid, details, strict=True):
        if recipe is None:
            errors.append({"slug": slug, "error": error or "Unknown error"})
            continue
        recipe_category = _text_value(recipe, "recipeCategory") or _text_value(recipe, "category")
        recipe_cuisine = _text_value(recipe, "recipeCuisine") or _text_value(recipe, "cuisine")
        total_time = _minutes(recipe)
        if category and category.casefold() not in (recipe_category or "").casefold():
            continue
        if cuisine and cuisine.casefold() not in (recipe_cuisine or "").casefold():
            continue
        if max_total_time is not None and total_time is not None and total_time > max_total_time:
            continue
        ingredients = [x for x in extract_recipe_ingredients(recipe) if not ignored_ingredient(x)]
        matched, missing, expiring, main_missing = [], [], [], 0
        for ingredient in ingredients:
            label, search = ingredient_label(ingredient), ingredient_search_text(ingredient)
            matches = [item for item in inventory if inventory_matches_ingredient(item.normalized_name or item.name, search, aliases)]
            if matches:
                matched.append({"ingredient": label, "inventory_items": [x.name for x in matches]})
                for item in matches:
                    if item.days_until_expiry is not None and 0 <= item.days_until_expiry <= 3 and item.name not in expiring:
                        expiring.append(item.name)
            else:
                missing.append(label)
                main_missing += int(is_main_ingredient(ingredient))
        if len(missing) > max_missing:
            continue
        coverage = len(matched) / len(ingredients) if ingredients else 1.0
        regular_missing = len(missing) - main_missing
        score = coverage * SCORE["coverage"] + (len(expiring) * SCORE["expiring"] if use_expiring else 0) + main_missing * SCORE["missing_main"] + regular_missing * SCORE["missing_regular"] + (SCORE["recent"] if slug in recent else 0)
        reasons = [f"库存覆盖 {round(coverage * 100, 1)}%"]
        if use_expiring and expiring:
            reasons.append(f"命中 {len(expiring)} 个三天内临期库存，+{len(expiring) * SCORE['expiring']} 分")
        if main_missing:
            reasons.append(f"缺少 {main_missing} 个主要食材，{main_missing * SCORE['missing_main']} 分")
        if regular_missing:
            reasons.append(f"缺少 {regular_missing} 个普通食材，{regular_missing * SCORE['missing_regular']} 分")
        if slug in recent:
            reasons.append("最近 7 天做过，-25 分")
        results.append({"name": recipe.get("name") or summary.get("name") or slug, "slug": slug, "score": round(score, 1), "coverage_percent": round(coverage * 100, 1), "matched_ingredients": matched, "missing_ingredients": missing, "expiring_inventory_matches": expiring, "score_reasons": reasons, "total_time_minutes": total_time, "category": recipe_category, "cuisine": recipe_cuisine, "mealie_url": f"{MEALIE_BASE_URL}/g/home/r/{slug}", "missing_ingredient_count": len(missing)})
    results.sort(key=lambda x: (-x["score"], x["missing_ingredient_count"], x["name"]))
    rng = random.Random(seed)
    random_results = list(results)
    rng.shuffle(random_results)
    if randomize:
        results = random_results
    return {"matching_version": 2, "score_weights": SCORE, "recipes_found": len(summaries), "recipes_evaluated": len(results), "recipe_detail_errors": errors, "ready_now": [x for x in results if not x["missing_ingredients"]][:limit], "missing_one_or_two": [x for x in results if 1 <= len(x["missing_ingredients"]) <= 2][:limit], "use_soon": [x for x in results if x["expiring_inventory_matches"]][:limit], "random_pick": random_results[:limit]}


@router.get("")
async def recommendations(limit: int = Query(10, ge=1, le=50), max_missing: int = Query(2, ge=0, le=50), max_total_time: int | None = Query(None, ge=1), category: str | None = None, cuisine: str | None = None, owner: str | None = None, use_expiring: bool = True, randomize: bool = False, seed: int | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    return await build_recommendations(db, limit=limit, max_missing=max_missing, max_total_time=max_total_time, category=category, cuisine=cuisine, owner=owner, use_expiring=use_expiring, randomize=randomize, seed=seed)


@router.get("/preview", deprecated=True)
async def recommendation_preview(max_recipes: int = Query(50, ge=1, le=200), limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)) -> dict[str, Any]:
    del max_recipes
    result = await build_recommendations(db, limit=limit, max_missing=50, max_total_time=None, category=None, cuisine=None, owner=None, use_expiring=True, randomize=False, seed=None)
    return {"matching_version": 1, "warning": "Legacy preview; use GET /api/v1/recommendations", "recommendations": (result["ready_now"] + result["missing_one_or_two"])[:limit], **{k: result[k] for k in ("recipes_found", "recipes_evaluated", "recipe_detail_errors")}}
