from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CookingHistory
from app.schemas import CookingHistoryCreate, CookingHistoryRead


router = APIRouter(prefix="/api/v1/cooking-history", tags=["cooking history"])


def create_cooking_history_record(
    payload: CookingHistoryCreate,
    db: Session,
    *,
    commit: bool = True,
) -> CookingHistory:
    """Shared cooking-history write used by HTTP and HA workflows."""
    row = CookingHistory(**payload.model_dump())
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def record_cooked_recipe(
    payload: CookingHistoryCreate,
    db: Session,
    *,
    idempotency_notes: str | None = None,
    recent_window: timedelta | None = None,
) -> tuple[CookingHistory, bool]:
    """Create one history row unless its explicit idempotency rule already matches."""
    statement = select(CookingHistory).where(
        CookingHistory.owner == payload.owner,
        CookingHistory.mealie_slug == payload.mealie_slug,
    )
    if idempotency_notes is not None:
        statement = statement.where(CookingHistory.notes == idempotency_notes)
    elif recent_window is not None:
        statement = statement.where(
            CookingHistory.created_at >= datetime.now(UTC) - recent_window
        )
    else:
        return create_cooking_history_record(payload, db, commit=False), True
    existing = db.scalar(statement.order_by(CookingHistory.id.desc()).limit(1))
    if existing is not None:
        return existing, False
    return create_cooking_history_record(payload, db, commit=False), True


@router.get("", response_model=list[CookingHistoryRead])
def list_history(owner: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> list[CookingHistory]:
    statement = select(CookingHistory)
    if owner:
        statement = statement.where(CookingHistory.owner == owner)
    return list(db.scalars(statement.order_by(CookingHistory.cooked_at.desc(), CookingHistory.id.desc()).offset(offset).limit(limit)).all())


@router.post("", response_model=CookingHistoryRead, status_code=201)
def create_history(payload: CookingHistoryCreate, db: Session = Depends(get_db)) -> CookingHistory:
    return create_cooking_history_record(payload, db)


@router.delete("/{history_id}", status_code=204, response_class=Response)
def delete_history(history_id: int, db: Session = Depends(get_db)) -> Response:
    row = db.get(CookingHistory, history_id)
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Cooking history entry not found")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
