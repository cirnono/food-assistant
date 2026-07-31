from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PantryItemCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        max_length=120,
    )

    quantity: float | None = Field(
        default=None,
        ge=0,
    )

    unit: str | None = Field(
        default=None,
        max_length=40,
    )

    location: str = Field(
        default="pantry",
        min_length=1,
        max_length=40,
    )

    expires_at: date | None = None
    opened: bool = False
    is_staple: bool = False

    owner: str = Field(
        default="household",
        min_length=1,
        max_length=40,
    )

    notes: str | None = Field(
        default=None,
        max_length=2000,
    )


class PantryItemUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )

    quantity: float | None = Field(
        default=None,
        ge=0,
    )

    unit: str | None = Field(
        default=None,
        max_length=40,
    )

    location: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
    )

    expires_at: date | None = None
    opened: bool | None = None
    is_staple: bool | None = None

    owner: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
    )

    notes: str | None = Field(
        default=None,
        max_length=2000,
    )


class PantryItemRead(PantryItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_expired: bool
    days_until_expiry: int | None
    created_at: datetime
    updated_at: datetime


class InventorySummary(BaseModel):
    total_items: int
    expired_items: int
    expiring_within_3_days: int
    staple_items: int
