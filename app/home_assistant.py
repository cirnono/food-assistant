from __future__ import annotations

import asyncio
import json
import random
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cooking_history import record_cooked_recipe
from app.database import get_db
from app.inventory import inventory_summary
from app.models import (
    CookingSession,
    HomeAssistantSelection,
    HomeAssistantSelectionHistory,
)
from app.recommendations import build_recommendations, clear_recipe_detail_cache
from app.schemas import (
    CookingHistoryCreate,
    HomeAssistantFilters,
    HomeAssistantMarkCookedRequest,
    HomeAssistantNextRequest,
    HomeAssistantRefreshRequest,
)


router = APIRouter(prefix="/api/v1/home-assistant", tags=["home assistant"])
_owner_locks: dict[str, asyncio.Lock] = {}
_selection_modes = {"ready_now", "missing_one_or_two", "use_soon", "random_pick"}


def _owner_lock(owner: str) -> asyncio.Lock:
    return _owner_locks.setdefault(owner, asyncio.Lock())


def owner_lock(owner: str) -> asyncio.Lock:
    return _owner_lock(owner)


def _filters_dict(filters: HomeAssistantFilters) -> dict[str, Any]:
    return filters.model_dump()


def _filters_json(filters: HomeAssistantFilters) -> str:
    return json.dumps(_filters_dict(filters), ensure_ascii=False, sort_keys=True)


def _safe_snapshot(recipe: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "name",
        "slug",
        "score",
        "coverage_percent",
        "missing_ingredients",
        "expiring_inventory_matches",
        "score_reasons",
        "total_time_minutes",
        "category",
        "cuisine",
        "mealie_url",
    )
    return {key: recipe.get(key) for key in keys}


def _stored_snapshot(selection: HomeAssistantSelection) -> dict[str, Any] | None:
    if not selection.selected_payload_json:
        return None
    try:
        payload = json.loads(selection.selected_payload_json)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _get_selection(db: Session, owner: str) -> HomeAssistantSelection | None:
    return db.scalar(
        select(HomeAssistantSelection).where(HomeAssistantSelection.owner == owner)
    )


def _candidate_group(result: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if mode not in _selection_modes:
        raise HTTPException(status_code=422, detail="Unsupported recommendation mode")
    value = result.get(mode)
    return value if isinstance(value, list) else []


def _recent_selection_slugs(db: Session, owner: str) -> set[str]:
    statement = (
        select(HomeAssistantSelectionHistory.mealie_slug)
        .where(HomeAssistantSelectionHistory.owner == owner)
        .order_by(HomeAssistantSelectionHistory.selected_at.desc(), HomeAssistantSelectionHistory.id.desc())
        .limit(5)
    )
    return set(db.scalars(statement).all())


def _save_selection(
    db: Session,
    filters: HomeAssistantFilters,
    recipe: dict[str, Any] | None,
    *,
    seed: int | None,
) -> HomeAssistantSelection:
    selection = _get_selection(db, filters.owner)
    if selection is None:
        selection = HomeAssistantSelection(owner=filters.owner)
        db.add(selection)
    selection.mode = filters.mode
    selection.filters_json = _filters_json(filters)
    selection.seed = seed
    now = datetime.now(UTC)
    if recipe is None:
        selection.selected_slug = None
        selection.selected_name = None
        selection.selected_payload_json = None
        selection.selected_at = None
    else:
        snapshot = _safe_snapshot(recipe)
        selection.selected_slug = str(snapshot["slug"])
        selection.selected_name = str(snapshot["name"])
        selection.selected_payload_json = json.dumps(snapshot, ensure_ascii=False)
        selection.selected_at = now
        db.add(HomeAssistantSelectionHistory(
            owner=filters.owner,
            mealie_slug=selection.selected_slug,
            selected_at=now,
        ))
    db.flush()
    return selection


def _choose_next(
    db: Session,
    owner: str,
    candidates: list[dict[str, Any]],
    current_slug: str | None,
    seed: int,
) -> dict[str, Any] | None:
    recent = _recent_selection_slugs(db, owner)
    preferred = [
        recipe for recipe in candidates
        if recipe.get("slug") != current_slug and recipe.get("slug") not in recent
    ]
    alternatives = [recipe for recipe in candidates if recipe.get("slug") != current_slug]
    pool = preferred or alternatives or candidates
    return random.Random(seed).choice(pool) if pool else None


async def _recommendation_result(db: Session, filters: HomeAssistantFilters) -> dict[str, Any]:
    return await build_recommendations(
        db,
        limit=10_000,
        max_missing=filters.max_missing,
        max_total_time=filters.max_total_time,
        category=filters.category,
        cuisine=filters.cuisine,
        owner=filters.owner,
        use_expiring=True,
        randomize=False,
        seed=None,
        refresh_cache=False,
    )


async def select_next_for_owner(
    db: Session,
    filters: HomeAssistantFilters,
    *,
    commit: bool = True,
) -> HomeAssistantSelection:
    result = await _recommendation_result(db, filters)
    candidates = _candidate_group(result, filters.mode)
    current = _get_selection(db, filters.owner)
    seed = random.SystemRandom().randint(1, 2_147_483_647)
    chosen = _choose_next(
        db,
        filters.owner,
        candidates,
        current.selected_slug if current else None,
        seed,
    )
    if chosen is None:
        raise HTTPException(status_code=409, detail="No recipe candidates are available for this mode and filters")
    selection = _save_selection(db, filters, chosen, seed=seed)
    if commit:
        db.commit()
    return selection


def _inventory_payload(db: Session) -> dict[str, int]:
    summary = inventory_summary(db)
    return {
        "total": summary.total_items,
        "available": summary.available_items,
        "expiring": summary.expiring_within_3_days,
        "expired": summary.expired_items,
        "out_of_stock": summary.out_of_stock_items,
        "low_stock": summary.low_stock_items,
    }


def _active_cooking_payload(request: Request, db: Session, owner: str) -> dict[str, Any]:
    row = db.scalar(select(CookingSession).where(
        CookingSession.owner == owner,
        CookingSession.status == "active",
    ))
    if row is None:
        return {"status": "idle", "session_id": None, "cooking_url": None}
    try:
        snapshot = json.loads(row.recipe_snapshot_json)
        instructions = snapshot.get("instructions", [])
    except (TypeError, ValueError):
        instructions = []
    count = len(instructions)
    base_url = str(request.base_url).rstrip("/")
    return {
        "status": "active",
        "session_id": row.id,
        "recipe_name": row.recipe_name,
        "mealie_slug": row.mealie_slug,
        "current_step_index": row.current_step_index,
        "step_count": count,
        "progress_percent": round((row.current_step_index + 1) / count * 100, 1) if count else 0,
        "cooking_url": f"{base_url}/cook",
    }


async def _state(
    request: Request,
    db: Session,
    filters: HomeAssistantFilters,
    *,
    commit_selection: bool = True,
) -> dict[str, Any]:
    result = await _recommendation_result(db, filters)
    candidates = _candidate_group(result, filters.mode)
    candidate_slugs = {str(recipe.get("slug")) for recipe in candidates}
    selection = _get_selection(db, filters.owner)
    selected = None
    if (
        selection is not None
        and selection.mode == filters.mode
        and selection.filters_json == _filters_json(filters)
        and selection.selected_slug in candidate_slugs
    ):
        selected = _stored_snapshot(selection)
    elif candidates:
        selected = candidates[0]
        _save_selection(db, filters, selected, seed=None)
        if commit_selection:
            db.commit()
    elif selection is not None and selection.selected_slug is not None:
        _save_selection(db, filters, None, seed=None)
        if commit_selection:
            db.commit()

    base_url = str(request.base_url).rstrip("/")
    return {
        "status": "ok",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "owner": filters.owner,
        "inventory": _inventory_payload(db),
        "recommendations": {
            "ready_now_count": len(result["ready_now"]),
            "missing_one_or_two_count": len(result["missing_one_or_two"]),
            "use_soon_count": len(result["use_soon"]),
        },
        "selected_recipe": _safe_snapshot(selected) if selected else None,
        "active_cooking": _active_cooking_payload(request, db, filters.owner),
        "links": {
            "pantry": f"{base_url}/pantry",
            "recommendations": f"{base_url}/recommendations",
        },
    }


@router.get("/state")
async def home_assistant_state(
    request: Request,
    owner: str = Query("household", min_length=1, max_length=40),
    mode: str = Query("ready_now", pattern="^(ready_now|missing_one_or_two|use_soon|random_pick)$"),
    max_missing: int = Query(2, ge=0, le=50),
    max_total_time: int | None = Query(None, ge=1),
    category: str | None = Query(None, max_length=160),
    cuisine: str | None = Query(None, max_length=160),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    filters = HomeAssistantFilters(
        owner=owner,
        mode=mode,
        max_missing=max_missing,
        max_total_time=max_total_time,
        category=category,
        cuisine=cuisine,
    )
    async with _owner_lock(owner):
        return await _state(request, db, filters)


@router.post("/selection/next")
async def next_selection(
    request: Request,
    payload: HomeAssistantNextRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.confirm_owner != payload.owner:
        raise HTTPException(status_code=409, detail="confirm_owner must match owner")
    filters = HomeAssistantFilters(**payload.model_dump(exclude={"confirm_owner"}))
    async with _owner_lock(payload.owner):
        await select_next_for_owner(db, filters)
        return await _state(request, db, filters)


def _filters_from_selection(selection: HomeAssistantSelection) -> HomeAssistantFilters:
    try:
        payload = json.loads(selection.filters_json)
        return HomeAssistantFilters(**payload)
    except (TypeError, ValueError):
        return HomeAssistantFilters(owner=selection.owner, mode=selection.mode)


@router.post("/selection/mark-cooked")
async def mark_selection_cooked(
    request: Request,
    payload: HomeAssistantMarkCookedRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    async with _owner_lock(payload.owner):
        selection = _get_selection(db, payload.owner)
        if selection is None or selection.selected_slug != payload.confirm_slug:
            raise HTTPException(status_code=409, detail="confirm_slug does not match the current selection")
        filters = _filters_from_selection(selection)
        try:
            record_cooked_recipe(
                CookingHistoryCreate(
                    mealie_slug=selection.selected_slug,
                    recipe_name=selection.selected_name or selection.selected_slug,
                    cooked_at=date.today(),
                    owner=payload.owner,
                    servings=payload.servings,
                    rating=payload.rating,
                    notes=payload.notes,
                ),
                db,
                recent_window=timedelta(minutes=5),
            )
            if payload.select_next:
                result = await _recommendation_result(db, filters)
                candidates = _candidate_group(result, filters.mode)
                seed = random.SystemRandom().randint(1, 2_147_483_647)
                chosen = _choose_next(db, payload.owner, candidates, selection.selected_slug, seed)
                if chosen is None:
                    raise HTTPException(status_code=409, detail="Cooking was not recorded because no next recipe is available")
                _save_selection(db, filters, chosen, seed=seed)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return await _state(request, db, filters)


@router.post("/refresh")
async def refresh_home_assistant_state(
    request: Request,
    payload: HomeAssistantRefreshRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.refresh_recipe_cache:
        await clear_recipe_detail_cache()
    selection = _get_selection(db, payload.owner)
    filters = _filters_from_selection(selection) if selection else HomeAssistantFilters(owner=payload.owner)
    async with _owner_lock(payload.owner):
        return await _state(request, db, filters)
