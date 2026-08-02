from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATABASE_PATH = Path(
    os.environ.get(
        "DATABASE_PATH",
        str(DATA_DIR / "food-assistant.db"),
    )
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{DATABASE_PATH}",
).strip()


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 10,
    },
    pool_pre_ping=True,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(
    dbapi_connection: Any,
    connection_record: Any,
) -> None:
    del connection_record

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def init_database() -> None:
    """Create the data directory and initial database tables."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Import models before create_all so SQLAlchemy knows the tables.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations()


def ensure_schema_migrations() -> None:
    """Apply small SQLite migrations for existing installations."""
    with engine.begin() as connection:
        pantry_rows = connection.exec_driver_sql(
            "PRAGMA table_info(pantry_items)"
        ).fetchall()
        pantry_columns = {str(row[1]) for row in pantry_rows}
        pantry_additions = {
            "normalized_name": "VARCHAR(160)",
            "low_stock_threshold": "FLOAT",
            "purchased_at": "DATE",
            "opened_at": "DATE",
            "mealie_food_id": "VARCHAR(255)",
        }
        for column_name, column_type in pantry_additions.items():
            if pantry_rows and column_name not in pantry_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE pantry_items ADD COLUMN {column_name} {column_type}"
                )

        rows = connection.exec_driver_sql(
            "PRAGMA table_info(source_recipes)"
        ).fetchall()

        columns = {
            str(row[1])
            for row in rows
        }

        if (
            rows
            and "search_text" not in columns
        ):
            connection.exec_driver_sql(
                "ALTER TABLE source_recipes "
                "ADD COLUMN search_text "
                "TEXT NOT NULL DEFAULT ''"
            )

        item_rows = connection.exec_driver_sql(
            "PRAGMA table_info(recipe_import_items)"
        ).fetchall()
        item_columns = {str(row[1]) for row in item_rows}
        duplicate_columns = {
            "duplicate_of_item_id": "INTEGER",
            "duplicate_mealie_slug": "VARCHAR(255)",
            "duplicate_reason": "TEXT",
        }
        for column_name, column_type in duplicate_columns.items():
            if item_rows and column_name not in item_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE recipe_import_items "
                    f"ADD COLUMN {column_name} {column_type}"
                )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def check_database() -> None:
    """Run a lightweight database readiness check."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
