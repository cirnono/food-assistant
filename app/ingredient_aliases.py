from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingredient_names import normalize_name
from app.models import IngredientAlias
from app.schemas import IngredientAliasCreate, IngredientAliasRead, IngredientAliasUpdate


router = APIRouter(prefix="/api/v1/ingredient-aliases", tags=["ingredient aliases"])


def _get(db: Session, alias_id: int) -> IngredientAlias:
    row = db.get(IngredientAlias, alias_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ingredient alias not found")
    return row


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Normalized alias already exists") from exc


@router.get("", response_model=list[IngredientAliasRead])
def list_aliases(db: Session = Depends(get_db)) -> list[IngredientAlias]:
    return list(db.scalars(select(IngredientAlias).order_by(IngredientAlias.alias)).all())


@router.post("", response_model=IngredientAliasRead, status_code=201)
def create_alias(payload: IngredientAliasCreate, db: Session = Depends(get_db)) -> IngredientAlias:
    normalized = normalize_name(payload.alias)
    if not normalized:
        raise HTTPException(status_code=422, detail="alias cannot normalize to empty")
    row = IngredientAlias(**payload.model_dump(), normalized_alias=normalized)
    db.add(row)
    _commit(db)
    db.refresh(row)
    return row


@router.patch("/{alias_id}", response_model=IngredientAliasRead)
def update_alias(alias_id: int, payload: IngredientAliasUpdate, db: Session = Depends(get_db)) -> IngredientAlias:
    row = _get(db, alias_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields supplied")
    for key, value in updates.items():
        setattr(row, key, value)
    if "alias" in updates:
        row.normalized_alias = normalize_name(row.alias)
        if not row.normalized_alias:
            raise HTTPException(status_code=422, detail="alias cannot normalize to empty")
    _commit(db)
    db.refresh(row)
    return row


@router.delete("/{alias_id}", status_code=204, response_class=Response)
def delete_alias(alias_id: int, db: Session = Depends(get_db)) -> Response:
    db.delete(_get(db, alias_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
