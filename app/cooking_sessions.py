from __future__ import annotations

import json
import math
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cooking_history import record_cooked_recipe
from app.database import get_db
from app.home_assistant import (
    _filters_from_selection,
    owner_lock,
    select_next_for_owner,
)
from app.ingredient_names import alias_map
from app.models import (
    CookingSession,
    CookingTimer,
    HomeAssistantSelection,
    PantryItem,
)
from app.recommendations import (
    MEALIE_BASE_URL,
    get_recipe_detail_cached,
    ingredient_label,
    inventory_matches_ingredient,
)
from app.schemas import (
    CookingHistoryCreate,
    CookingSessionActionRequest,
    CookingSessionFinishRequest,
    CookingSessionSetStepRequest,
    CookingSessionStartRequest,
    CookingSessionToggleIngredientRequest,
    CookingTimerCreateRequest,
    HomeAssistantFilters,
)


router = APIRouter(prefix="/api/v1/cooking-sessions", tags=["cooking sessions"])
HOME_ASSISTANT_KITCHEN_URL = os.environ.get("HOME_ASSISTANT_KITCHEN_URL", "").strip()


def clock_now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _snapshot(session: CookingSession) -> dict[str, Any]:
    try:
        value = json.loads(session.recipe_snapshot_json)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Cooking session snapshot is invalid") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=500, detail="Cooking session snapshot is invalid")
    return value


def _instructions(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    raw: Any = []
    for key in ("recipeInstructions", "instructions"):
        if isinstance(recipe.get(key), list):
            raw = recipe[key]
            break
    result = []
    for item in raw:
        if isinstance(item, str):
            title, text = None, item.strip()
        elif isinstance(item, dict):
            title_value = item.get("title") or item.get("name")
            title = str(title_value).strip() if title_value else None
            text_value = item.get("text") or item.get("summary") or item.get("display")
            text = str(text_value).strip() if text_value else ""
        else:
            continue
        if text:
            result.append({"title": title, "text": text})
    return result


def _ingredients(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    raw: Any = []
    for key in ("recipeIngredient", "recipe_ingredient", "ingredients"):
        if isinstance(recipe.get(key), list):
            raw = recipe[key]
            break
    result = []
    for item in raw:
        if isinstance(item, str):
            result.append({"name": item.strip(), "display": item.strip(), "quantity": None, "unit": None, "note": None})
            continue
        if not isinstance(item, dict):
            continue
        unit_value = item.get("unit")
        unit = unit_value.get("name") if isinstance(unit_value, dict) else unit_value
        name = ingredient_label(item)
        result.append({
            "name": name,
            "display": item.get("display") or item.get("originalText") or name,
            "quantity": item.get("quantity", item.get("quantityValue")),
            "unit": str(unit).strip() if unit else None,
            "note": item.get("note"),
        })
    return result


def build_recipe_snapshot(recipe: dict[str, Any], slug: str) -> dict[str, Any]:
    instructions = _instructions(recipe)
    if not instructions:
        raise HTTPException(status_code=422, detail="Recipe has no valid instructions")
    total_time = None
    for key in ("totalTime", "total_time", "totalTimeMinutes", "total_time_minutes"):
        if isinstance(recipe.get(key), (int, float)):
            total_time = int(recipe[key])
            break
    def text_value(*keys: str) -> str | None:
        for key in keys:
            value = recipe.get(key)
            if isinstance(value, dict):
                value = value.get("name")
            if value:
                return str(value)
        return None
    return {
        "name": str(recipe.get("name") or slug),
        "slug": slug,
        "ingredients": _ingredients(recipe),
        "instructions": instructions,
        "total_time": total_time,
        "category": text_value("recipeCategory", "category"),
        "cuisine": text_value("recipeCuisine", "cuisine"),
        "mealie_url": f"{MEALIE_BASE_URL}/g/home/r/{slug}",
    }


def _active(db: Session, owner: str) -> CookingSession | None:
    return db.scalar(select(CookingSession).where(
        CookingSession.owner == owner,
        CookingSession.status == "active",
    ))


def _session(db: Session, session_id: int, owner: str) -> CookingSession:
    row = db.get(CookingSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Cooking session not found")
    if row.owner != owner:
        raise HTTPException(status_code=403, detail="Cooking session owner does not match")
    return row


def _confirmed_session(db: Session, session_id: int, payload: CookingSessionActionRequest) -> CookingSession:
    if payload.confirm_session_id != session_id:
        raise HTTPException(status_code=409, detail="confirm_session_id does not match")
    return _session(db, session_id, payload.owner)


def _require_active(row: CookingSession) -> None:
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Cooking session is not active")


def _checked(row: CookingSession) -> set[int]:
    try:
        return {int(value) for value in json.loads(row.checked_ingredients_json)}
    except (TypeError, ValueError):
        return set()


def _timer_remaining(timer: CookingTimer, now: datetime) -> int:
    if timer.state == "running" and timer.deadline_at is not None:
        return max(0, math.ceil((_utc(timer.deadline_at) - now).total_seconds()))
    if timer.state == "paused":
        return max(0, int(timer.remaining_seconds or 0))
    return 0


def _materialize_timer(timer: CookingTimer, now: datetime) -> bool:
    if timer.state == "running" and timer.deadline_at is not None and _utc(timer.deadline_at) <= now:
        timer.state = "finished"
        timer.remaining_seconds = 0
        timer.finished_at = now
        return True
    return False


def _timer_payload(timer: CookingTimer, now: datetime) -> dict[str, Any]:
    deadline = _utc(timer.deadline_at)
    return {
        "id": timer.id,
        "cooking_session_id": timer.cooking_session_id,
        "label": timer.label,
        "state": timer.state,
        "duration_seconds": timer.duration_seconds,
        "remaining_seconds": _timer_remaining(timer, now),
        "deadline_at": deadline.isoformat() if deadline else None,
        "is_overdue": bool(deadline and deadline <= now),
        "started_at": _utc(timer.started_at),
        "paused_at": _utc(timer.paused_at),
        "finished_at": _utc(timer.finished_at),
        "cancelled_at": _utc(timer.cancelled_at),
    }


def _timers(db: Session, session_id: int, *, materialize: bool = True) -> list[CookingTimer]:
    rows = list(db.scalars(select(CookingTimer).where(
        CookingTimer.cooking_session_id == session_id
    ).order_by(CookingTimer.id)).all())
    changed = False
    now = clock_now()
    if materialize:
        changed = any(_materialize_timer(timer, now) for timer in rows)
    if changed:
        db.commit()
    return rows


def session_payload(db: Session, row: CookingSession) -> dict[str, Any]:
    snapshot = _snapshot(row)
    now = clock_now()
    timers = _timers(db, row.id)
    return {
        "id": row.id,
        "owner": row.owner,
        "mealie_slug": row.mealie_slug,
        "recipe_name": row.recipe_name,
        "recipe": snapshot,
        "status": row.status,
        "current_step_index": row.current_step_index,
        "checked_ingredient_indexes": sorted(_checked(row)),
        "servings": row.servings,
        "started_at": _utc(row.started_at),
        "completed_at": _utc(row.completed_at),
        "cancelled_at": _utc(row.cancelled_at),
        "timers": [_timer_payload(timer, now) for timer in timers],
        "inventory_consumption_preview": inventory_consumption_preview(db, snapshot),
    }


def inventory_consumption_preview(db: Session, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = list(db.scalars(select(PantryItem)).all())
    aliases = alias_map(db)
    result = []
    for ingredient in snapshot.get("ingredients", []):
        name = str(ingredient.get("name") or ingredient.get("display") or "")
        matches = [item for item in inventory if inventory_matches_ingredient(item.name, name, aliases)]
        result.append({
            "recipe_ingredient": name,
            "inventory_items": [item.name for item in matches],
            "has_exact_quantity": bool(matches and all(item.quantity is not None for item in matches)),
            "safe_to_decrement": False,
            "requires_manual_confirmation": True,
        })
    return result


@router.post("/start", status_code=201)
async def start_session(payload: CookingSessionStartRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    async with owner_lock(payload.owner):
        existing = _active(db, payload.owner)
        if existing:
            raise HTTPException(status_code=409, detail={"message": "Owner already has an active cooking session", "session_id": existing.id})
        slug = payload.mealie_slug
        if slug is None:
            selection = db.scalar(select(HomeAssistantSelection).where(HomeAssistantSelection.owner == payload.owner))
            slug = selection.selected_slug if selection else None
        if not slug:
            raise HTTPException(status_code=409, detail="No recipe slug or current HA selection is available")
        if payload.confirm_slug != slug:
            raise HTTPException(status_code=409, detail="confirm_slug does not match mealie_slug")
        recipe, error = await get_recipe_detail_cached(slug)
        if recipe is None:
            raise HTTPException(status_code=502, detail=f"Unable to load recipe detail: {error or 'unknown error'}")
        snapshot = build_recipe_snapshot(recipe, slug)
        row = CookingSession(
            owner=payload.owner,
            mealie_slug=slug,
            recipe_name=snapshot["name"],
            recipe_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
            status="active",
            current_step_index=0,
            checked_ingredients_json="[]",
            servings=payload.servings,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            active = _active(db, payload.owner)
            raise HTTPException(status_code=409, detail={"message": "Owner already has an active cooking session", "session_id": active.id if active else None}) from exc
        db.refresh(row)
        return session_payload(db, row)


@router.get("/active")
def read_active_session(owner: str = Query("household", min_length=1, max_length=40), db: Session = Depends(get_db)) -> dict[str, Any] | None:
    row = _active(db, owner)
    return session_payload(db, row) if row else None


@router.get("/active-state")
def active_state(request: Request, owner: str = Query("household", min_length=1, max_length=40), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _active(db, owner)
    if row is None:
        return {"status": "idle", "owner": owner, "session": None, "timers": [], "next_timer": None}
    snapshot = _snapshot(row)
    instructions = snapshot["instructions"]
    timer_rows = _timers(db, row.id)
    now = clock_now()
    timers = [_timer_payload(timer, now) for timer in timer_rows]
    running = [timer for timer in timers if timer["state"] in {"running", "paused"}]
    running.sort(key=lambda timer: timer["remaining_seconds"])
    step_count = len(instructions)
    return {
        "status": "active",
        "owner": owner,
        "session": {
            "id": row.id,
            "recipe_name": row.recipe_name,
            "mealie_slug": row.mealie_slug,
            "current_step_index": row.current_step_index,
            "step_count": step_count,
            "current_step": instructions[row.current_step_index]["text"],
            "progress_percent": round((row.current_step_index + 1) / step_count * 100, 1),
            "cooking_url": f"{str(request.base_url).rstrip('/')}/cook",
            "started_at": _utc(row.started_at),
        },
        "timers": timers,
        "next_timer": running[0] if running else None,
        "links": {
            "cooking": f"{str(request.base_url).rstrip('/')}/cook",
        },
    }


@router.get("/{session_id}")
def read_session(session_id: int, owner: str = Query("household", min_length=1, max_length=40), db: Session = Depends(get_db)) -> dict[str, Any]:
    return session_payload(db, _session(db, session_id, owner))


def _step_update(db: Session, row: CookingSession, index: int) -> dict[str, Any]:
    _require_active(row)
    count = len(_snapshot(row)["instructions"])
    if not 0 <= index < count:
        raise HTTPException(status_code=422, detail="Step index is out of range")
    row.current_step_index = index
    db.commit()
    return session_payload(db, row)


@router.post("/{session_id}/next-step")
async def next_step(session_id: int, payload: CookingSessionActionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    async with owner_lock(payload.owner):
        row = _confirmed_session(db, session_id, payload)
        return _step_update(db, row, row.current_step_index + 1)


@router.post("/{session_id}/previous-step")
async def previous_step(session_id: int, payload: CookingSessionActionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    async with owner_lock(payload.owner):
        row = _confirmed_session(db, session_id, payload)
        return _step_update(db, row, row.current_step_index - 1)


@router.post("/{session_id}/set-step")
async def set_step(session_id: int, payload: CookingSessionSetStepRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    async with owner_lock(payload.owner):
        return _step_update(db, _confirmed_session(db, session_id, payload), payload.step_index)


@router.post("/{session_id}/toggle-ingredient")
async def toggle_ingredient(session_id: int, payload: CookingSessionToggleIngredientRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    async with owner_lock(payload.owner):
        row = _confirmed_session(db, session_id, payload)
        _require_active(row)
        count = len(_snapshot(row)["ingredients"])
        if not 0 <= payload.ingredient_index < count:
            raise HTTPException(status_code=422, detail="Ingredient index is out of range")
        checked = _checked(row)
        if payload.ingredient_index in checked:
            checked.remove(payload.ingredient_index)
        else:
            checked.add(payload.ingredient_index)
        row.checked_ingredients_json = json.dumps(sorted(checked))
        db.commit()
        return session_payload(db, row)


@router.post("/{session_id}/finish")
async def finish_session(session_id: int, payload: CookingSessionFinishRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    async with owner_lock(payload.owner):
        row = _confirmed_session(db, session_id, payload)
        _require_active(row)
        now = clock_now()
        try:
            for timer in _timers(db, row.id, materialize=False):
                if timer.state in {"running", "paused"}:
                    timer.state = "finished"
                    timer.remaining_seconds = 0
                    timer.deadline_at = None
                    timer.finished_at = now
            marker = f"cooking_session:{row.id}"
            record_cooked_recipe(CookingHistoryCreate(
                    mealie_slug=row.mealie_slug,
                    recipe_name=row.recipe_name,
                    cooked_at=date.today(),
                    owner=row.owner,
                    servings=row.servings,
                    notes=marker,
                ), db, idempotency_notes=marker)
            row.status = "completed"
            row.completed_at = now
            if payload.select_next:
                selection = db.scalar(select(HomeAssistantSelection).where(HomeAssistantSelection.owner == row.owner))
                filters = _filters_from_selection(selection) if selection else HomeAssistantFilters(owner=row.owner)
                await select_next_for_owner(db, filters, commit=False)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return session_payload(db, row)


@router.post("/{session_id}/cancel")
async def cancel_session(session_id: int, payload: CookingSessionActionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    async with owner_lock(payload.owner):
        row = _confirmed_session(db, session_id, payload)
        _require_active(row)
        now = clock_now()
        for timer in _timers(db, row.id, materialize=False):
            if timer.state in {"running", "paused"}:
                timer.state = "cancelled"
                timer.deadline_at = None
                timer.cancelled_at = now
        row.status = "cancelled"
        row.cancelled_at = now
        db.commit()
        return session_payload(db, row)


def _timer(db: Session, row: CookingSession, timer_id: int) -> CookingTimer:
    timer = db.get(CookingTimer, timer_id)
    if timer is None or timer.cooking_session_id != row.id:
        raise HTTPException(status_code=404, detail="Cooking timer not found")
    return timer


@router.post("/{session_id}/timers", status_code=201)
async def create_timer(session_id: int, payload: CookingTimerCreateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    async with owner_lock(payload.owner):
        row = _confirmed_session(db, session_id, payload)
        _require_active(row)
        count = db.scalar(select(func.count()).select_from(CookingTimer).where(
            CookingTimer.cooking_session_id == row.id,
            CookingTimer.state != "cancelled",
        )) or 0
        if count >= 8:
            raise HTTPException(status_code=409, detail="A cooking session supports at most 8 non-cancelled timers")
        now = clock_now()
        timer = CookingTimer(
            cooking_session_id=row.id,
            label=payload.label,
            state="running" if payload.start_immediately else "paused",
            duration_seconds=payload.duration_seconds,
            deadline_at=now + timedelta(seconds=payload.duration_seconds) if payload.start_immediately else None,
            remaining_seconds=None if payload.start_immediately else payload.duration_seconds,
            started_at=now if payload.start_immediately else None,
            paused_at=now if not payload.start_immediately else None,
        )
        db.add(timer)
        db.commit()
        db.refresh(timer)
        return _timer_payload(timer, now)


async def _timer_action(session_id: int, timer_id: int, payload: CookingSessionActionRequest, action: str, db: Session) -> dict[str, Any]:
    async with owner_lock(payload.owner):
        row = _confirmed_session(db, session_id, payload)
        timer = _timer(db, row, timer_id)
        now = clock_now()
        _materialize_timer(timer, now)
        if action == "pause":
            if timer.state == "paused":
                return _timer_payload(timer, now)
            if timer.state != "running":
                raise HTTPException(status_code=409, detail="Only a running timer can be paused")
            timer.remaining_seconds = _timer_remaining(timer, now)
            timer.deadline_at = None
            timer.state = "paused"
            timer.paused_at = now
        elif action == "resume":
            if timer.state == "running":
                return _timer_payload(timer, now)
            if timer.state != "paused":
                raise HTTPException(status_code=409, detail="Only a paused timer can be resumed")
            remaining = max(1, int(timer.remaining_seconds or 0))
            timer.deadline_at = now + timedelta(seconds=remaining)
            timer.remaining_seconds = None
            timer.state = "running"
            timer.started_at = timer.started_at or now
            timer.paused_at = None
        elif action == "finish":
            if timer.state == "finished":
                return _timer_payload(timer, now)
            if timer.state == "cancelled":
                raise HTTPException(status_code=409, detail="Cancelled timer cannot be finished")
            timer.state = "finished"
            timer.deadline_at = None
            timer.remaining_seconds = 0
            timer.finished_at = now
        elif action == "cancel":
            if timer.state == "cancelled":
                return _timer_payload(timer, now)
            timer.state = "cancelled"
            timer.deadline_at = None
            timer.cancelled_at = now
        db.commit()
        return _timer_payload(timer, now)


@router.post("/{session_id}/timers/{timer_id}/pause")
async def pause_timer(session_id: int, timer_id: int, payload: CookingSessionActionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return await _timer_action(session_id, timer_id, payload, "pause", db)


@router.post("/{session_id}/timers/{timer_id}/resume")
async def resume_timer(session_id: int, timer_id: int, payload: CookingSessionActionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return await _timer_action(session_id, timer_id, payload, "resume", db)


@router.post("/{session_id}/timers/{timer_id}/finish")
async def finish_timer(session_id: int, timer_id: int, payload: CookingSessionActionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return await _timer_action(session_id, timer_id, payload, "finish", db)


@router.post("/{session_id}/timers/{timer_id}/cancel")
async def cancel_timer(session_id: int, timer_id: int, payload: CookingSessionActionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return await _timer_action(session_id, timer_id, payload, "cancel", db)


@router.delete("/{session_id}/timers/{timer_id}", status_code=204, response_class=Response)
async def delete_timer(session_id: int, timer_id: int, owner: str = Query("household"), confirm_session_id: int = Query(..., gt=0), db: Session = Depends(get_db)) -> Response:
    payload = CookingSessionActionRequest(owner=owner, confirm_session_id=confirm_session_id)
    async with owner_lock(owner):
        row = _confirmed_session(db, session_id, payload)
        timer = _timer(db, row, timer_id)
        if timer.state not in {"finished", "cancelled"}:
            raise HTTPException(status_code=409, detail="Only finished or cancelled timers can be deleted")
        db.delete(timer)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
