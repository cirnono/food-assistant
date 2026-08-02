from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
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
