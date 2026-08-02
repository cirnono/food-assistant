from __future__ import annotations

from datetime import date, timedelta

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PantryItem
from app.ingredient_names import normalize_name
from app.schemas import (
    InventorySummary,
    PantryItemCreate,
    PantryItemRead,
    PantryItemUpdate,
)


router = APIRouter(
    prefix="/api/v1/inventory",
    tags=["inventory"],
)


def get_item_or_404(
    db: Session,
    item_id: int,
) -> PantryItem:
    item = db.get(PantryItem, item_id)

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pantry item not found",
        )

    return item


@router.get(
    "/summary",
    response_model=InventorySummary,
)
def inventory_summary(
    db: Session = Depends(get_db),
) -> InventorySummary:
    today = date.today()
    three_days_later = today + timedelta(days=3)

    total_items = db.scalar(
        select(func.count()).select_from(PantryItem)
    ) or 0

    expired_items = db.scalar(
        select(func.count())
        .select_from(PantryItem)
        .where(PantryItem.expires_at < today)
    ) or 0

    expiring_items = db.scalar(
        select(func.count())
        .select_from(PantryItem)
        .where(
            PantryItem.expires_at.is_not(None),
            PantryItem.expires_at >= today,
            PantryItem.expires_at <= three_days_later,
        )
    ) or 0

    staple_items = db.scalar(
        select(func.count())
        .select_from(PantryItem)
        .where(PantryItem.is_staple.is_(True))
    ) or 0

    available_filter = or_(PantryItem.quantity.is_(None), PantryItem.quantity > 0)
    available_items = db.scalar(select(func.count()).select_from(PantryItem).where(available_filter, or_(PantryItem.expires_at.is_(None), PantryItem.expires_at >= today))) or 0
    out_of_stock_items = db.scalar(select(func.count()).select_from(PantryItem).where(PantryItem.quantity == 0)) or 0
    low_stock_items = db.scalar(select(func.count()).select_from(PantryItem).where(PantryItem.quantity.is_not(None), PantryItem.quantity > 0, PantryItem.low_stock_threshold.is_not(None), PantryItem.quantity <= PantryItem.low_stock_threshold)) or 0

    return InventorySummary(
        total_items=total_items,
        available_items=available_items,
        out_of_stock_items=out_of_stock_items,
        expired_items=expired_items,
        expiring_within_3_days=expiring_items,
        low_stock_items=low_stock_items,
        staple_items=staple_items,
    )


@router.get(
    "",
    response_model=list[PantryItemRead],
)
def list_inventory(
    q: str | None = Query(
        default=None,
        description="Search by ingredient name",
    ),
    location: str | None = None,
    owner: str | None = None,
    include_expired: bool = True,
    expiring_within_days: int | None = Query(
        default=None,
        ge=0,
        le=3650,
    ),
    low_stock: bool | None = None,
    staple: bool | None = None,
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
) -> list[PantryItem]:
    today = date.today()

    statement = select(PantryItem)

    if q:
        statement = statement.where(
            func.lower(PantryItem.name).contains(q.lower())
        )

    if location:
        statement = statement.where(
            PantryItem.location == location
        )

    if owner:
        statement = statement.where(
            PantryItem.owner == owner
        )

    if low_stock is not None:
        condition = (
            PantryItem.quantity.is_not(None), PantryItem.quantity > 0,
            PantryItem.low_stock_threshold.is_not(None),
            PantryItem.quantity <= PantryItem.low_stock_threshold,
        )
        statement = statement.where(*condition) if low_stock else statement.where(or_(PantryItem.low_stock_threshold.is_(None), PantryItem.quantity.is_(None), PantryItem.quantity == 0, PantryItem.quantity > PantryItem.low_stock_threshold))
    if staple is not None:
        statement = statement.where(PantryItem.is_staple.is_(staple))

    if expiring_within_days is not None:
        cutoff = today + timedelta(days=expiring_within_days)

        statement = statement.where(
            PantryItem.expires_at.is_not(None),
            PantryItem.expires_at <= cutoff,
        )

        if not include_expired:
            statement = statement.where(
                PantryItem.expires_at >= today
            )

    elif not include_expired:
        statement = statement.where(
            or_(
                PantryItem.expires_at.is_(None),
                PantryItem.expires_at >= today,
            )
        )

    statement = (
        statement
        .order_by(
            case(
                (PantryItem.expires_at.is_(None), 1),
                else_=0,
            ),
            PantryItem.expires_at.asc(),
            PantryItem.name.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    return list(db.scalars(statement).all())


@router.post(
    "",
    response_model=PantryItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_inventory_item(
    payload: PantryItemCreate,
    db: Session = Depends(get_db),
) -> PantryItem:
    values = payload.model_dump()
    if not values.get("normalized_name"):
        values["normalized_name"] = normalize_name(values["name"])
    item = PantryItem(**values)

    db.add(item)
    db.commit()
    db.refresh(item)

    return item


@router.get(
    "/{item_id}",
    response_model=PantryItemRead,
)
def read_inventory_item(
    item_id: int,
    db: Session = Depends(get_db),
) -> PantryItem:
    return get_item_or_404(db, item_id)


@router.patch(
    "/{item_id}",
    response_model=PantryItemRead,
)
def update_inventory_item(
    item_id: int,
    payload: PantryItemUpdate,
    db: Session = Depends(get_db),
) -> PantryItem:
    item = get_item_or_404(db, item_id)

    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields supplied",
        )

    required_fields = {
        "name",
        "location",
        "owner",
        "opened",
        "is_staple",
    }

    for field_name, value in updates.items():
        if field_name in required_fields and value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field_name} cannot be null",
            )

        setattr(item, field_name, value)

    if "name" in updates and "normalized_name" not in updates:
        item.normalized_name = normalize_name(item.name)

    db.commit()
    db.refresh(item)

    return item


@router.post("/{item_id}/consume", response_model=PantryItemRead)
def consume_inventory_item(item_id: int, db: Session = Depends(get_db)) -> PantryItem:
    item = get_item_or_404(db, item_id)
    item.quantity = 0
    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/restock", response_model=PantryItemRead)
def restock_inventory_item(item_id: int, payload: PantryItemUpdate, db: Session = Depends(get_db)) -> PantryItem:
    item = get_item_or_404(db, item_id)
    allowed = {"quantity", "unit", "purchased_at", "expires_at"}
    updates = payload.model_dump(exclude_unset=True)
    invalid = set(updates) - allowed
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unsupported restock fields: {', '.join(sorted(invalid))}")
    for key, value in updates.items():
        setattr(item, key, value)
    item.opened = False
    item.opened_at = None
    db.commit()
    db.refresh(item)
    return item


@router.post("/{item_id}/open", response_model=PantryItemRead)
def open_inventory_item(item_id: int, db: Session = Depends(get_db)) -> PantryItem:
    item = get_item_or_404(db, item_id)
    item.opened = True
    item.opened_at = date.today()
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_inventory_item(
    item_id: int,
    db: Session = Depends(get_db),
) -> Response:
    item = get_item_or_404(db, item_id)

    db.delete(item)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
