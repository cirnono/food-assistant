from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingredient_names import alias_map, canonicalize, normalize_name
from app.models import (
    ConsumptionReview,
    InventoryAdjustment,
    PantryItem,
    ShoppingListItem,
    utc_now,
)
from app.schemas import ConsumptionActionRequest, ConsumptionConfirmRequest
from app.units import normalize_unit, unit_family, unit_match_reason, units_compatible


router = APIRouter(prefix="/api/v1/consumption-reviews", tags=["consumption reviews"])


def build_consumption_proposal(
    db: Session, owner: str, snapshot: dict[str, Any]
) -> list[dict[str, Any]]:
    pantry = list(
        db.scalars(
            select(PantryItem).where(PantryItem.owner.in_({owner, "household"}))
        ).all()
    )
    aliases = alias_map(db)
    result: list[dict[str, Any]] = []
    claimed: dict[int, list[int]] = {}
    for index, ingredient in enumerate(snapshot.get("ingredients", [])):
        if ingredient.get("ignored"):
            continue
        name = str(ingredient.get("name") or ingredient.get("display") or "").strip()
        normalized = normalize_name(name)
        canonical = canonicalize(name, aliases)
        exact = [
            item
            for item in pantry
            if normalize_name(item.normalized_name or item.name) == normalized
        ]
        candidates = [
            item
            for item in pantry
            if canonicalize(item.normalized_name or item.name, aliases) == canonical
        ]
        match_type = (
            "none"
            if not candidates
            else "ambiguous"
            if len(candidates) > 1
            else "exact"
            if exact
            else "alias"
        )
        item = candidates[0] if len(candidates) == 1 else None
        quantity = ingredient.get("quantity")
        recipe_quantity = (
            float(quantity) if isinstance(quantity, (int, float)) else None
        )
        recipe_unit = ingredient.get("unit") or None
        compatible = bool(item and units_compatible(recipe_unit, item.unit))
        expired = bool(
            item and item.expires_at is not None and item.expires_at < date.today()
        )
        action = "manual"
        deduction = None
        reason = "No pantry match"
        if match_type == "ambiguous":
            reason = "Multiple pantry items match; choose one manually"
        elif item is not None:
            if expired:
                action, reason = "leave_unchanged", "Matched pantry item is expired"
            elif recipe_quantity is None:
                action, reason = "manual", "Recipe quantity is missing"
            elif item.quantity is None:
                action, reason = "manual", "Pantry quantity is unknown"
            elif not compatible:
                action, reason = "manual", "Units are incompatible"
            else:
                deduction = recipe_quantity
                action = "deduct" if recipe_quantity <= item.quantity else "manual"
                reason = (
                    "Exact quantity can be proposed"
                    if action == "deduct"
                    else "Recipe quantity exceeds pantry quantity"
                )
            claimed.setdefault(item.id, []).append(index)
        shopping_suggestions: list[dict[str, Any]] = []
        if item is not None and action == "deduct" and deduction is not None:
            quantity_after = item.quantity - deduction
            source = (
                "out_of_stock"
                if quantity_after == 0
                else "low_stock"
                if item.low_stock_threshold is not None
                and quantity_after <= item.low_stock_threshold
                else None
            )
            if source:
                shopping_suggestions.append(
                    {
                        "pantry_item_id": item.id,
                        "name": item.name,
                        "quantity_after": quantity_after,
                        "source": source,
                        "priority": "high" if source == "out_of_stock" else "normal",
                        "requires_opt_in": True,
                    }
                )
        result.append(
            {
                "recipe_ingredient_index": index,
                "recipe_ingredient_name": name,
                "recipe_quantity": recipe_quantity,
                "recipe_unit": recipe_unit,
                "recipe_unit_normalized": normalize_unit(recipe_unit),
                "matched_pantry_item_id": item.id if item else None,
                "matched_pantry_name": item.name if item else None,
                "pantry_quantity_before": item.quantity if item else None,
                "pantry_unit": item.unit if item else None,
                "pantry_unit_normalized": normalize_unit(item.unit) if item else None,
                "unit_family": unit_family(recipe_unit) or (unit_family(item.unit) if item else None),
                "unit_match_reason": unit_match_reason(recipe_unit, item.unit if item else None),
                "candidate_pantry_items": [
                    {
                        "id": x.id,
                        "name": x.name,
                        "quantity": x.quantity,
                        "unit": x.unit,
                        "is_expired": x.is_expired,
                    }
                    for x in candidates
                ],
                "match_type": match_type,
                "quantity_compatible": compatible,
                "suggested_action": action,
                "suggested_deduction": deduction,
                "requires_manual_confirmation": True,
                "reason": reason,
                "shopping_suggestions": shopping_suggestions,
            }
        )
    for item_id, indexes in claimed.items():
        if len(indexes) > 1:
            for row in result:
                if row["recipe_ingredient_index"] in indexes:
                    row["suggested_action"] = "manual"
                    row["suggested_deduction"] = None
                    row["reason"] = (
                        "Multiple recipe ingredients target the same pantry item"
                    )
                    row["pantry_item_conflict"] = True
    return result


def create_review_for_session(
    db: Session, session: Any, snapshot: dict[str, Any]
) -> ConsumptionReview:
    existing = db.scalar(
        select(ConsumptionReview).where(
            ConsumptionReview.cooking_session_id == session.id
        )
    )
    if existing:
        return existing
    row = ConsumptionReview(
        cooking_session_id=session.id,
        owner=session.owner,
        recipe_name=session.recipe_name,
        mealie_slug=session.mealie_slug,
        status="pending",
        proposal_json=json.dumps(
            build_consumption_proposal(db, session.owner, snapshot),
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    db.add(row)
    db.flush()
    return row


def _json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def review_payload(db: Session, row: ConsumptionReview) -> dict[str, Any]:
    adjustments = list(
        db.scalars(
            select(InventoryAdjustment)
            .where(InventoryAdjustment.consumption_review_id == row.id)
            .order_by(InventoryAdjustment.id)
        ).all()
    )
    return {
        "id": row.id,
        "cooking_session_id": row.cooking_session_id,
        "owner": row.owner,
        "recipe_name": row.recipe_name,
        "mealie_slug": row.mealie_slug,
        "status": row.status,
        "proposal": _json(row.proposal_json, []),
        "confirmed": _json(row.confirmed_json, None),
        "created_at": row.created_at,
        "confirmed_at": row.confirmed_at,
        "dismissed_at": row.dismissed_at,
        "updated_at": row.updated_at,
        "inventory_adjustments": [adjustment_payload(x) for x in adjustments],
    }


def adjustment_payload(row: InventoryAdjustment) -> dict[str, Any]:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "pantry_item_id",
            "consumption_review_id",
            "shopping_list_item_id",
            "owner",
            "adjustment_type",
            "quantity_before",
            "quantity_change",
            "quantity_after",
            "unit",
            "reason",
            "created_at",
            "reversed_at",
            "reversed_by_adjustment_id",
        )
    }


def _review(db: Session, review_id: int, owner: str | None = None) -> ConsumptionReview:
    row = db.get(ConsumptionReview, review_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Consumption review not found")
    if owner is not None and row.owner != owner:
        raise HTTPException(
            status_code=403, detail="Consumption review owner does not match"
        )
    return row


@router.get("")
def list_reviews(
    owner: str | None = None,
    status: str | None = Query(None, pattern="^(pending|confirmed|dismissed)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(ConsumptionReview)
    if owner:
        query = query.where(ConsumptionReview.owner == owner)
    if status:
        query = query.where(ConsumptionReview.status == status)
    rows = db.scalars(
        query.order_by(ConsumptionReview.id.desc()).offset(offset).limit(limit)
    ).all()
    return [review_payload(db, row) for row in rows]


@router.get("/pending")
def pending_reviews(
    owner: str = "household", db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ConsumptionReview)
        .where(ConsumptionReview.owner == owner, ConsumptionReview.status == "pending")
        .order_by(ConsumptionReview.id)
    ).all()
    return [review_payload(db, row) for row in rows]


@router.get("/{review_id}")
def read_review(
    review_id: int, owner: str | None = None, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return review_payload(db, _review(db, review_id, owner))


def _shopping_add(
    db: Session,
    *,
    item: PantryItem,
    review: ConsumptionReview,
    source: str,
    priority: str,
) -> ShoppingListItem:
    normalized = normalize_name(item.normalized_name or item.name)
    existing = db.scalar(
        select(ShoppingListItem).where(
            ShoppingListItem.owner == review.owner,
            ShoppingListItem.normalized_name == normalized,
            ShoppingListItem.status == "active",
            ShoppingListItem.unit == item.unit,
        )
    )
    if existing:
        if priority == "high":
            existing.priority = "high"
        return existing
    row = ShoppingListItem(
        owner=review.owner,
        name=item.name,
        normalized_name=normalized,
        quantity=None,
        unit=item.unit,
        status="active",
        priority=priority,
        source=source,
        pantry_item_id=item.id,
        consumption_review_id=review.id,
    )
    db.add(row)
    db.flush()
    return row


@router.post("/{review_id}/confirm")
def confirm_review(
    review_id: int, payload: ConsumptionConfirmRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    if payload.confirm_review_id != review_id:
        raise HTTPException(
            status_code=409, detail="confirm_review_id does not match URL"
        )
    review = _review(db, review_id, payload.owner)
    request_data = payload.model_dump(mode="json")
    if review.status == "confirmed":
        saved = _json(review.confirmed_json, {})
        if saved.get("request") == request_data:
            return saved["result"]
        raise HTTPException(
            status_code=409,
            detail="Consumption review was already confirmed with different data",
        )
    if review.status != "pending":
        raise HTTPException(status_code=409, detail="Consumption review is not pending")
    proposal = {
        x["recipe_ingredient_index"]: x for x in _json(review.proposal_json, [])
    }
    seen_pantry: set[int] = set()
    updated: list[PantryItem] = []
    adjustments: list[InventoryAdjustment] = []
    shopping: list[ShoppingListItem] = []
    low_results: list[dict[str, Any]] = []
    try:
        for requested in payload.items:
            if requested.recipe_ingredient_index not in proposal:
                raise HTTPException(
                    status_code=422,
                    detail="Recipe ingredient is not in the stable proposal",
                )
            candidate_ids = {
                candidate["id"]
                for candidate in proposal[requested.recipe_ingredient_index].get(
                    "candidate_pantry_items", []
                )
            }
            if requested.pantry_item_id not in candidate_ids:
                raise HTTPException(
                    status_code=409,
                    detail="Pantry item is not an exact or alias candidate in the stable proposal",
                )
            item = db.get(PantryItem, requested.pantry_item_id)
            if item is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Pantry item {requested.pantry_item_id} not found",
                )
            if item.owner not in {payload.owner, "household"}:
                raise HTTPException(
                    status_code=403, detail="Pantry item is outside the owner scope"
                )
            if requested.action == "leave_unchanged":
                continue
            if item.id in seen_pantry:
                raise HTTPException(
                    status_code=409,
                    detail="A pantry item cannot be adjusted twice in one review",
                )
            seen_pantry.add(item.id)
            before = item.quantity
            if requested.action == "deduct":
                if requested.quantity_used is None:
                    raise HTTPException(
                        status_code=422, detail="deduct requires quantity_used > 0"
                    )
                if before is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Cannot deduct an exact quantity from unknown pantry quantity",
                    )
                if not units_compatible(requested.unit, item.unit):
                    raise HTTPException(
                        status_code=409,
                        detail="Pantry and consumption units are incompatible",
                    )
                if requested.quantity_used > before:
                    raise HTTPException(
                        status_code=409, detail="quantity_used exceeds pantry quantity"
                    )
                after = before - requested.quantity_used
                adjustment_type = "consumption"
            else:
                after = 0.0
                adjustment_type = "consume_all"
            item.quantity = after
            adjustment = InventoryAdjustment(
                pantry_item_id=item.id,
                consumption_review_id=review.id,
                owner=review.owner,
                adjustment_type=adjustment_type,
                quantity_before=before,
                quantity_change=(after - before) if before is not None else None,
                quantity_after=after,
                unit=item.unit,
                reason=f"Confirmed consumption for {review.recipe_name}",
            )
            db.add(adjustment)
            db.flush()
            updated.append(item)
            adjustments.append(adjustment)
            state = (
                "out_of_stock"
                if after == 0
                else "low_stock"
                if item.low_stock_threshold is not None
                and after <= item.low_stock_threshold
                else None
            )
            low_results.append(
                {"pantry_item_id": item.id, "quantity_after": after, "state": state}
            )
            if requested.add_to_shopping_list_if_low and state:
                shopping.append(
                    _shopping_add(
                        db,
                        item=item,
                        review=review,
                        source=state,
                        priority="high" if state == "out_of_stock" else "normal",
                    )
                )
        result = {
            "review_id": review.id,
            "updated_pantry_items": [
                {"id": x.id, "name": x.name, "quantity": x.quantity, "unit": x.unit}
                for x in updated
            ],
            "inventory_adjustments": [adjustment_payload(x) for x in adjustments],
            "shopping_list_additions": [
                {"id": x.id, "name": x.name, "source": x.source, "priority": x.priority}
                for x in shopping
            ],
            "low_out_of_stock_results": low_results,
        }
        review.status = "confirmed"
        review.confirmed_at = utc_now()
        review.confirmed_json = json.dumps(
            {"request": request_data, "result": result},
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.post("/{review_id}/dismiss")
def dismiss_review(
    review_id: int, payload: ConsumptionActionRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    if payload.confirm_review_id != review_id:
        raise HTTPException(
            status_code=409, detail="confirm_review_id does not match URL"
        )
    row = _review(db, review_id, payload.owner)
    if row.status == "dismissed":
        return review_payload(db, row)
    if row.status != "pending":
        raise HTTPException(
            status_code=409, detail="Only pending reviews can be dismissed"
        )
    row.status = "dismissed"
    row.dismissed_at = utc_now()
    db.commit()
    return review_payload(db, row)


@router.post("/{review_id}/undo")
def undo_review(
    review_id: int, payload: ConsumptionActionRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    if payload.confirm_review_id != review_id:
        raise HTTPException(
            status_code=409, detail="confirm_review_id does not match URL"
        )
    review = _review(db, review_id, payload.owner)
    if review.status != "confirmed":
        raise HTTPException(
            status_code=409, detail="Only confirmed reviews can be undone"
        )
    confirmed = _json(review.confirmed_json, {})
    if confirmed.get("undone_at"):
        raise HTTPException(
            status_code=409, detail="Consumption review was already undone"
        )
    originals = list(
        db.scalars(
            select(InventoryAdjustment)
            .where(
                InventoryAdjustment.consumption_review_id == review.id,
                InventoryAdjustment.adjustment_type.in_({"consumption", "consume_all"}),
            )
            .order_by(InventoryAdjustment.id)
        ).all()
    )
    if any(x.reversed_at is not None for x in originals):
        raise HTTPException(
            status_code=409, detail="Consumption review was already undone"
        )
    shopping_ids = list(
        db.scalars(
            select(ShoppingListItem.id).where(
                ShoppingListItem.consumption_review_id == review.id
            )
        ).all()
    )
    reversals = []
    try:
        now = utc_now()
        for original in originals:
            item = (
                db.get(PantryItem, original.pantry_item_id)
                if original.pantry_item_id
                else None
            )
            if item is None:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot undo because a pantry item no longer exists",
                )
            if item.quantity != original.quantity_after:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot undo because pantry quantity changed after this review",
                )
            before = item.quantity
            item.quantity = original.quantity_before
            reversal = InventoryAdjustment(
                pantry_item_id=item.id,
                consumption_review_id=review.id,
                owner=review.owner,
                adjustment_type="reversal",
                quantity_before=before,
                quantity_change=(original.quantity_before - before)
                if before is not None and original.quantity_before is not None
                else None,
                quantity_after=original.quantity_before,
                unit=original.unit,
                reason=f"Reversal of inventory adjustment {original.id}",
            )
            db.add(reversal)
            db.flush()
            original.reversed_at = now
            original.reversed_by_adjustment_id = reversal.id
            reversals.append(reversal)
        confirmed["undone_at"] = now.isoformat()
        confirmed["reversal_adjustment_ids"] = [row.id for row in reversals]
        review.confirmed_json = json.dumps(
            confirmed, ensure_ascii=False, sort_keys=True
        )
        db.commit()
        return {
            "review_id": review.id,
            "reversal_adjustments": [adjustment_payload(x) for x in reversals],
            "shopping_item_ids_requiring_manual_review": shopping_ids,
        }
    except Exception:
        db.rollback()
        raise
