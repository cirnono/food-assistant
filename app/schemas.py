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


class CookingSessionStartRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    owner: str = Field(default="household", min_length=1, max_length=40)
    mealie_slug: str | None = Field(default=None, min_length=1, max_length=255)
    confirm_slug: str | None = Field(default=None, min_length=1, max_length=255)
    servings: float | None = Field(default=None, gt=0)


class CookingSessionActionRequest(BaseModel):
    owner: str = Field(default="household", min_length=1, max_length=40)
    confirm_session_id: int = Field(gt=0)


class CookingSessionSetStepRequest(CookingSessionActionRequest):
    step_index: int = Field(ge=0)


class CookingSessionToggleIngredientRequest(CookingSessionActionRequest):
    ingredient_index: int = Field(ge=0)


class CookingSessionFinishRequest(CookingSessionActionRequest):
    select_next: bool = True


class CookingTimerCreateRequest(CookingSessionActionRequest):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=80)
    duration_seconds: int = Field(ge=1, le=86_400)
    start_immediately: bool = True


class ConsumptionConfirmItem(BaseModel):
    recipe_ingredient_index: int = Field(ge=0)
    pantry_item_id: int = Field(gt=0)
    action: str = Field(pattern="^(deduct|consume_all|leave_unchanged)$")
    quantity_used: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=40)
    add_to_shopping_list_if_low: bool = False


class ConsumptionConfirmRequest(BaseModel):
    owner: str = Field(default="household", min_length=1, max_length=40)
    confirm_review_id: int = Field(gt=0)
    items: list[ConsumptionConfirmItem]


class ConsumptionActionRequest(BaseModel):
    owner: str = Field(default="household", min_length=1, max_length=40)
    confirm_review_id: int = Field(gt=0)


class ShoppingListCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    owner: str = Field(default="household", min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=40)
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    source: str = Field(default="manual", pattern="^(manual|low_stock|out_of_stock|recipe_missing|consumption_review)$")
    pantry_item_id: int | None = Field(default=None, gt=0)
    consumption_review_id: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)


class ShoppingListUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    owner: str = Field(default="household", min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=40)
    priority: str | None = Field(default=None, pattern="^(low|normal|high)$")
    notes: str | None = Field(default=None, max_length=2000)


class ShoppingRestock(BaseModel):
    mode: str = Field(default="none", pattern="^(none|existing|create)$")
    pantry_item_id: int | None = Field(default=None, gt=0)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=40)
    location: str = Field(default="pantry", min_length=1, max_length=40)
    purchased_at: date | None = None
    expires_at: date | None = None


class ShoppingCompleteRequest(BaseModel):
    owner: str = Field(default="household", min_length=1, max_length=40)
    confirm_item_id: int = Field(gt=0)
    restock: ShoppingRestock = Field(default_factory=ShoppingRestock)


class ShoppingActionRequest(BaseModel):
    owner: str = Field(default="household", min_length=1, max_length=40)
    confirm_item_id: int = Field(gt=0)


class ShoppingFromRecipeRequest(BaseModel):
    owner: str = Field(default="household", min_length=1, max_length=40)
    mealie_slug: str = Field(min_length=1, max_length=255)
    confirm_slug: str = Field(min_length=1, max_length=255)
    selected_missing_ingredients: list[str]
