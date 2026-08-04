from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.consumption import adjustment_payload, units_compatible
from app.database import get_db
from app.ingredient_names import alias_map, canonicalize, normalize_name
from app.models import InventoryAdjustment, PantryItem, ShoppingListItem, utc_now
from app.recommendations import (
    extract_recipe_ingredients,
    get_recipe_detail_cached,
    ignored_ingredient,
    ingredient_label,
)
from app.schemas import (
    ShoppingActionRequest,
    ShoppingCompleteRequest,
    ShoppingFromRecipeRequest,
    ShoppingListCreate,
    ShoppingListUpdate,
)


router = APIRouter(prefix="/api/v1/shopping-list", tags=["shopping list"])


def item_payload(row: ShoppingListItem) -> dict[str, Any]:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "owner",
            "name",
            "normalized_name",
            "quantity",
            "unit",
            "status",
            "priority",
            "source",
            "pantry_item_id",
            "consumption_review_id",
            "notes",
            "created_at",
            "completed_at",
            "dismissed_at",
            "updated_at",
        )
    }


def _item(db: Session, item_id: int, owner: str | None = None) -> ShoppingListItem:
    row = db.get(ShoppingListItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Shopping list item not found")
    if owner is not None and row.owner != owner:
        raise HTTPException(
            status_code=403, detail="Shopping list item owner does not match"
        )
    return row


def add_or_merge(db: Session, values: dict[str, Any]) -> tuple[ShoppingListItem, bool]:
    normalized = canonicalize(
        values.get("normalized_name") or values["name"], alias_map(db)
    )
    unit = values.get("unit") or None
    active_matches = list(
        db.scalars(
            select(ShoppingListItem).where(
                ShoppingListItem.owner == values["owner"],
                ShoppingListItem.normalized_name == normalized,
                ShoppingListItem.status == "active",
            )
        ).all()
    )
    existing = next(
        (item for item in active_matches if units_compatible(item.unit, unit)), None
    )
    if existing:
        incoming_quantity = values.get("quantity")
        if existing.quantity is not None and incoming_quantity is not None:
            existing.quantity += incoming_quantity
        elif existing.quantity is None and incoming_quantity is not None:
            existing.quantity = incoming_quantity
        if values.get("priority") == "high":
            existing.priority = "high"
        return existing, False
    row = ShoppingListItem(**{**values, "normalized_name": normalized, "unit": unit})
    db.add(row)
    db.flush()
    return row, True


@router.get("")
def list_items(
    owner: str | None = None,
    status_value: str | None = Query(
        None, alias="status", pattern="^(active|completed|dismissed)$"
    ),
    q: str | None = None,
    priority: str | None = Query(None, pattern="^(low|normal|high)$"),
    source: str | None = Query(
        None,
        pattern="^(manual|low_stock|out_of_stock|recipe_missing|consumption_review)$",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(ShoppingListItem)
    if owner:
        query = query.where(ShoppingListItem.owner == owner)
    query = query.where(ShoppingListItem.status == (status_value or "active"))
    if q:
        query = query.where(
            or_(
                ShoppingListItem.name.ilike(f"%{q}%"),
                ShoppingListItem.normalized_name.contains(normalize_name(q)),
            )
        )
    if priority:
        query = query.where(ShoppingListItem.priority == priority)
    if source:
        query = query.where(ShoppingListItem.source == source)
    priority_rank = case(
        (ShoppingListItem.priority == "high", 0),
        (ShoppingListItem.priority == "normal", 1),
        (ShoppingListItem.priority == "low", 2),
        else_=3,
    )
    rows = db.scalars(
        query.order_by(priority_rank, ShoppingListItem.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return [item_payload(x) for x in rows]


@router.post("", status_code=201)
def create_item(
    payload: ShoppingListCreate, db: Session = Depends(get_db)
) -> dict[str, Any]:
    row, created = add_or_merge(
        db,
        payload.model_dump(exclude={"pantry_item_id", "consumption_review_id"})
        | {
            "pantry_item_id": payload.pantry_item_id,
            "consumption_review_id": payload.consumption_review_id,
        },
    )
    db.commit()
    result = item_payload(row)
    result["created"] = created
    return result


@router.patch("/{item_id}")
def update_item(
    item_id: int, payload: ShoppingListUpdate, db: Session = Depends(get_db)
) -> dict[str, Any]:
    row = _item(db, item_id, payload.owner)
    if row.status != "active":
        raise HTTPException(
            status_code=409, detail="Only active shopping items can be edited"
        )
    updates = payload.model_dump(exclude_unset=True, exclude={"owner"})
    if not updates:
        raise HTTPException(status_code=400, detail="No fields supplied")
    for key, value in updates.items():
        setattr(row, key, value)
    if "name" in updates:
        row.normalized_name = normalize_name(row.name)
    db.commit()
    return item_payload(row)


@router.post("/{item_id}/complete")
def complete_item(
    item_id: int, payload: ShoppingCompleteRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    if payload.confirm_item_id != item_id:
        raise HTTPException(
            status_code=409, detail="confirm_item_id does not match URL"
        )
    row = _item(db, item_id, payload.owner)
    if row.status == "completed":
        return {
            "shopping_item": item_payload(row),
            "pantry_item": None,
            "inventory_adjustment": None,
            "already_completed": True,
        }
    if row.status != "active":
        raise HTTPException(
            status_code=409, detail="Only active items can be completed"
        )
    restock = payload.restock
    pantry: PantryItem | None = None
    adjustment: InventoryAdjustment | None = None
    try:
        if restock.mode == "existing":
            if restock.pantry_item_id is None:
                raise HTTPException(
                    status_code=422, detail="existing restock requires pantry_item_id"
                )
            pantry = db.get(PantryItem, restock.pantry_item_id)
            if pantry is None:
                raise HTTPException(status_code=404, detail="Pantry item not found")
            if pantry.owner not in {payload.owner, "household"}:
                raise HTTPException(
                    status_code=403, detail="Pantry item is outside owner scope"
                )
            if restock.quantity is None:
                raise HTTPException(
                    status_code=422, detail="Restock quantity is required"
                )
            if not units_compatible(restock.unit, pantry.unit):
                raise HTTPException(
                    status_code=409, detail="Restock and pantry units are incompatible"
                )
            before = pantry.quantity
            pantry.quantity = (
                restock.quantity if before is None else before + restock.quantity
            )
            pantry.purchased_at = restock.purchased_at
            pantry.expires_at = restock.expires_at
            pantry.opened = False
            pantry.opened_at = None
        elif restock.mode == "create":
            if restock.quantity is None:
                raise HTTPException(
                    status_code=422, detail="Restock quantity is required"
                )
            pantry = PantryItem(
                name=row.name,
                normalized_name=normalize_name(row.name),
                quantity=restock.quantity,
                unit=restock.unit,
                location=restock.location,
                purchased_at=restock.purchased_at,
                expires_at=restock.expires_at,
                owner=payload.owner,
            )
            db.add(pantry)
            db.flush()
            before = None
        elif restock.mode != "none":
            raise HTTPException(status_code=422, detail="Unsupported restock mode")
        if pantry is not None:
            row.pantry_item_id = pantry.id
            adjustment = InventoryAdjustment(
                pantry_item_id=pantry.id,
                shopping_list_item_id=row.id,
                owner=payload.owner,
                adjustment_type="restock",
                quantity_before=before,
                quantity_change=restock.quantity,
                quantity_after=pantry.quantity,
                unit=pantry.unit,
                reason=f"Shopping list completion: {row.name}",
            )
            db.add(adjustment)
            db.flush()
        row.status = "completed"
        row.completed_at = utc_now()
        row.dismissed_at = None
        db.commit()
        return {
            "shopping_item": item_payload(row),
            "pantry_item": (
                {
                    "id": pantry.id,
                    "name": pantry.name,
                    "quantity": pantry.quantity,
                    "unit": pantry.unit,
                }
                if pantry
                else None
            ),
            "inventory_adjustment": adjustment_payload(adjustment)
            if adjustment
            else None,
            "already_completed": False,
        }
    except Exception:
        db.rollback()
        raise


def _action(
    item_id: int, payload: ShoppingActionRequest, db: Session, target: str
) -> dict[str, Any]:
    if payload.confirm_item_id != item_id:
        raise HTTPException(
            status_code=409, detail="confirm_item_id does not match URL"
        )
    row = _item(db, item_id, payload.owner)
    if target == "dismissed":
        if row.status == "completed":
            raise HTTPException(
                status_code=409, detail="Completed item cannot be dismissed"
            )
        row.status = "dismissed"
        row.dismissed_at = utc_now()
    else:
        if row.status == "active":
            return item_payload(row)
        row.status = "active"
        row.dismissed_at = None
        row.completed_at = None
    db.commit()
    return item_payload(row)


@router.post("/{item_id}/dismiss")
def dismiss_item(
    item_id: int, payload: ShoppingActionRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return _action(item_id, payload, db, "dismissed")


@router.post("/{item_id}/restore")
def restore_item(
    item_id: int, payload: ShoppingActionRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return _action(item_id, payload, db, "active")


@router.delete("/{item_id}", status_code=204, response_class=Response)
def delete_item(
    item_id: int, owner: str = "household", db: Session = Depends(get_db)
) -> Response:
    row = _item(db, item_id, owner)
    if row.status == "active":
        raise HTTPException(
            status_code=409,
            detail="Active shopping items must be dismissed before deletion",
        )
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/from-recipe")
async def from_recipe(
    payload: ShoppingFromRecipeRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    if payload.confirm_slug != payload.mealie_slug:
        raise HTTPException(
            status_code=409, detail="confirm_slug does not match mealie_slug"
        )
    recipe, error = await get_recipe_detail_cached(payload.mealie_slug)
    if recipe is None:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to validate recipe: {error or 'unknown error'}",
        )
    aliases = alias_map(db)
    pantry = list(
        db.scalars(
            select(PantryItem).where(
                PantryItem.owner.in_({payload.owner, "household"}),
                or_(PantryItem.quantity.is_(None), PantryItem.quantity > 0),
            )
        ).all()
    )
    missing: dict[str, str] = {}
    for ingredient in extract_recipe_ingredients(recipe):
        if ignored_ingredient(ingredient):
            continue
        label = ingredient_label(ingredient)
        canonical = canonicalize(label, aliases)
        if not any(
            canonicalize(x.normalized_name or x.name, aliases) == canonical
            for x in pantry
        ):
            missing[canonical] = label
    selected = {canonicalize(x, aliases) for x in payload.selected_missing_ingredients}
    if not selected.issubset(missing):
        raise HTTPException(
            status_code=409,
            detail="Selected ingredients are not in the recipe's current missing set",
        )
    rows = []
    for canonical in selected:
        row, created = add_or_merge(
            db,
            {
                "owner": payload.owner,
                "name": missing[canonical],
                "normalized_name": canonical,
                "quantity": None,
                "unit": None,
                "status": "active",
                "priority": "normal",
                "source": "recipe_missing",
                "pantry_item_id": None,
                "consumption_review_id": None,
                "notes": f"Recipe: {payload.mealie_slug}",
            },
        )
        rows.append({**item_payload(row), "created": created})
    db.commit()
    return {"mealie_slug": payload.mealie_slug, "items": rows}
