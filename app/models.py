from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class PantryItem(Base):
    __tablename__ = "pantry_items"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )

    quantity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    normalized_name: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    low_stock_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchased_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    opened_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    mealie_food_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    unit: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    location: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="pantry",
        index=True,
    )

    expires_at: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )

    opened: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_staple: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )

    owner: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="household",
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    @property
    def is_expired(self) -> bool:
        return (
            self.expires_at is not None
            and self.expires_at < date.today()
        )

    @property
    def days_until_expiry(self) -> int | None:
        if self.expires_at is None:
            return None

        return (self.expires_at - date.today()).days


class IngredientAlias(Base):
    __tablename__ = "ingredient_aliases"
    __table_args__ = (UniqueConstraint("normalized_alias", name="uq_ingredient_alias_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(160), nullable=False)
    alias: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class CookingHistory(Base):
    __tablename__ = "cooking_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mealie_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recipe_name: Mapped[str] = mapped_column(String(300), nullable=False)
    cooked_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(40), nullable=False, default="household", index=True)
    servings: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class HomeAssistantSelection(Base):
    __tablename__ = "home_assistant_selections"
    __table_args__ = (UniqueConstraint("owner", name="uq_home_assistant_selection_owner"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(40), nullable=False, default="ready_now")
    selected_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    selected_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    selected_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    filters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    seed: Mapped[int | None] = mapped_column(nullable=True)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class HomeAssistantSelectionHistory(Base):
    __tablename__ = "home_assistant_selection_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    mealie_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)


class CookingSession(Base):
    __tablename__ = "cooking_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'completed', 'cancelled')", name="ck_cooking_session_status"),
        Index(
            "uq_cooking_session_active_owner",
            "owner",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    mealie_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recipe_name: Mapped[str] = mapped_column(String(300), nullable=False)
    recipe_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    current_step_index: Mapped[int] = mapped_column(nullable=False, default=0)
    checked_ingredients_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    servings: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class CookingTimer(Base):
    __tablename__ = "cooking_timers"
    __table_args__ = (
        CheckConstraint("state IN ('running', 'paused', 'finished', 'cancelled')", name="ck_cooking_timer_state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cooking_session_id: Mapped[int] = mapped_column(
        ForeignKey("cooking_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    duration_seconds: Mapped[int] = mapped_column(nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    remaining_seconds: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class RecipeSource(Base):
    __tablename__ = "recipe_sources"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    repo_url: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        unique=True,
    )

    branch: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    include_path: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        default="dishes",
    )

    sync_interval_minutes: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    last_commit: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class SourceRecipe(Base):
    __tablename__ = "source_recipes"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "path",
            name="uq_source_recipe_path",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey(
            "recipe_sources.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    path: Mapped[str] = mapped_column(
        String(1500),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        index=True,
    )

    category: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
        index=True,
    )

    search_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    content_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    source_commit: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="available",
        index=True,
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )



class RecipeImportJob(Base):
    __tablename__ = "recipe_import_jobs"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey(
            "recipe_sources.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    selection_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="queued",
        index=True,
    )

    total_items: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class RecipeImportItem(Base):
    __tablename__ = "recipe_import_items"

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "source_recipe_id",
            name="uq_import_job_source_recipe",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey(
            "recipe_import_jobs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    source_recipe_id: Mapped[int] = mapped_column(
        ForeignKey(
            "source_recipes.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    source_content_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    source_commit: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="queued",
        index=True,
    )

    normalized_json: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    duplicate_of_item_id: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    duplicate_mealie_slug: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    duplicate_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    attempts: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
