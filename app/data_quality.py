from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingredient_names import normalize_name
from app.models import ConsumptionReview, InventoryAdjustment, PantryItem, ShoppingListItem
from app.units import normalize_unit


router = APIRouter(prefix="/api/v1/data-quality", tags=["data quality"])


def clock_now() -> datetime:
    return datetime.now(UTC)


def _proposal_rows(db: Session) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in db.scalars(
        select(ConsumptionReview.proposal_json).order_by(ConsumptionReview.id.desc()).limit(100)
    ):
        try:
            proposal = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(proposal, list):
            rows.extend(item for item in proposal if isinstance(item, dict))
    return rows


@router.get("/summary")
def data_quality_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    inventory = list(db.scalars(select(PantryItem)).all())
    shopping = list(
        db.scalars(
            select(ShoppingListItem).where(ShoppingListItem.status == "active")
        ).all()
    )
    normalized_counts: dict[tuple[str, str], int] = {}
    for item in inventory:
        key = (item.owner, item.normalized_name or normalize_name(item.name))
        normalized_counts[key] = normalized_counts.get(key, 0) + 1
    proposals = _proposal_rows(db)
    recent_cutoff = clock_now() - timedelta(days=30)
    return {
        "inventory_total": len(inventory),
        "inventory_unknown_quantity": sum(item.quantity is None for item in inventory),
        "inventory_missing_unit": sum(not str(item.unit or "").strip() for item in inventory),
        "inventory_unrecognized_unit": sum(
            bool(str(item.unit or "").strip()) and normalize_unit(item.unit) is None
            for item in inventory
        ),
        "duplicate_normalized_names": sum(count > 1 for count in normalized_counts.values()),
        "pending_consumption_reviews": db.scalar(
            select(func.count()).select_from(ConsumptionReview).where(
                ConsumptionReview.status == "pending"
            )
        ) or 0,
        "ambiguous_consumption_matches": sum(
            item.get("match_type") == "ambiguous" for item in proposals
        ),
        "unmatched_consumption_ingredients": sum(
            item.get("match_type") == "none" for item in proposals
        ),
        "incompatible_unit_matches": sum(
            bool(item.get("matched_pantry_item_id"))
            and not bool(item.get("quantity_compatible"))
            for item in proposals
        ),
        "active_shopping_items": len(shopping),
        "shopping_items_missing_quantity": sum(item.quantity is None for item in shopping),
        "shopping_items_missing_unit": sum(not str(item.unit or "").strip() for item in shopping),
        "recent_adjustment_count": db.scalar(
            select(func.count()).select_from(InventoryAdjustment).where(
                InventoryAdjustment.created_at >= recent_cutoff
            )
        ) or 0,
        "latest_checked_at": clock_now().isoformat(),
    }
