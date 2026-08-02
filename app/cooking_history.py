from __future__ import annotations

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
