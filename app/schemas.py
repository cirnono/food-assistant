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
    normalized_name: str | None = Field(default=None, max_length=160)
    low_stock_threshold: float | None = Field(default=None, ge=0)
    purchased_at: date | None = None
    opened_at: date | None = None
    mealie_food_id: str | None = Field(default=None, max_length=255)

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
    normalized_name: str | None = Field(default=None, max_length=160)
    low_stock_threshold: float | None = Field(default=None, ge=0)
    purchased_at: date | None = None
    opened_at: date | None = None
    mealie_food_id: str | None = Field(default=None, max_length=255)

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
    available_items: int
    out_of_stock_items: int
    expired_items: int
    expiring_within_3_days: int
    low_stock_items: int
    staple_items: int


class IngredientAliasCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    canonical_name: str = Field(min_length=1, max_length=160)
    alias: str = Field(min_length=1, max_length=160)


class IngredientAliasUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    canonical_name: str | None = Field(default=None, min_length=1, max_length=160)
    alias: str | None = Field(default=None, min_length=1, max_length=160)


class IngredientAliasRead(IngredientAliasCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class CookingHistoryCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    mealie_slug: str = Field(min_length=1, max_length=255)
    recipe_name: str = Field(min_length=1, max_length=300)
    cooked_at: date = Field(default_factory=date.today)
    owner: str = Field(default="household", min_length=1, max_length=40)
    servings: float | None = Field(default=None, gt=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    notes: str | None = Field(default=None, max_length=2000)


class CookingHistoryRead(CookingHistoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class HomeAssistantFilters(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    owner: str = Field(default="household", min_length=1, max_length=40)
    mode: str = Field(default="ready_now", pattern="^(ready_now|missing_one_or_two|use_soon|random_pick)$")
    max_missing: int = Field(default=2, ge=0, le=50)
    max_total_time: int | None = Field(default=None, ge=1)
    category: str | None = Field(default=None, max_length=160)
    cuisine: str | None = Field(default=None, max_length=160)


class HomeAssistantNextRequest(HomeAssistantFilters):
    confirm_owner: str = Field(min_length=1, max_length=40)


class HomeAssistantMarkCookedRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    owner: str = Field(default="household", min_length=1, max_length=40)
    confirm_slug: str = Field(min_length=1, max_length=255)
    servings: float | None = Field(default=None, gt=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    notes: str | None = Field(default=None, max_length=2000)
    select_next: bool = True


class HomeAssistantRefreshRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    owner: str = Field(default="household", min_length=1, max_length=40)
    refresh_recipe_cache: bool = False
