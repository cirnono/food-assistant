from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def utc_now() -> str:
    return datetime.now(
        UTC
    ).isoformat()


def ensure_mealie_import_schema(
    db: Session,
) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS
            mealie_import_records (
                import_item_id INTEGER
                    PRIMARY KEY,
                source_id INTEGER
                    NOT NULL,
                source_recipe_id INTEGER
                    NOT NULL,
                source_content_sha256
                    VARCHAR(64)
                    NOT NULL,
                import_key VARCHAR(200)
                    NOT NULL,
                state VARCHAR(40)
                    NOT NULL,
                mealie_slug VARCHAR(255),
                mealie_recipe_id VARCHAR(64),
                error TEXT,
                created_at VARCHAR(50)
                    NOT NULL,
                updated_at VARCHAR(50)
                    NOT NULL
            )
            """
        )
    )

    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            uq_mealie_import_records_import_key
            ON mealie_import_records (
                import_key
            )
            """
        )
    )

    db.commit()


def _row_to_dict(
    row: Any,
) -> dict[str, Any] | None:
    if row is None:
        return None

    return dict(row._mapping)


def get_record_by_item(
    db: Session,
    import_item_id: int,
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT *
            FROM mealie_import_records
            WHERE import_item_id = :item_id
            """
        ),
        {
            "item_id": import_item_id,
        },
    ).first()

    return _row_to_dict(row)


def get_record_by_key(
    db: Session,
    import_key: str,
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT *
            FROM mealie_import_records
            WHERE import_key = :import_key
            """
        ),
        {
            "import_key": import_key,
        },
    ).first()

    return _row_to_dict(row)


def start_import_record(
    db: Session,
    *,
    import_item_id: int,
    source_id: int,
    source_recipe_id: int,
    source_content_sha256: str,
    import_key: str,
) -> None:
    now = utc_now()

    existing = get_record_by_item(
        db,
        import_item_id,
    )

    if existing is None:
        db.execute(
            text(
                """
                INSERT INTO mealie_import_records (
                    import_item_id,
                    source_id,
                    source_recipe_id,
                    source_content_sha256,
                    import_key,
                    state,
                    mealie_slug,
                    mealie_recipe_id,
                    error,
                    created_at,
                    updated_at
                )
                VALUES (
                    :import_item_id,
                    :source_id,
                    :source_recipe_id,
                    :source_content_sha256,
                    :import_key,
                    'importing',
                    NULL,
                    NULL,
                    NULL,
                    :now,
                    :now
                )
                """
            ),
            {
                "import_item_id": (
                    import_item_id
                ),
                "source_id": source_id,
                "source_recipe_id": (
                    source_recipe_id
                ),
                "source_content_sha256": (
                    source_content_sha256
                ),
                "import_key": import_key,
                "now": now,
            },
        )

        return

    db.execute(
        text(
            """
            UPDATE mealie_import_records
            SET
                source_id = :source_id,
                source_recipe_id =
                    :source_recipe_id,
                source_content_sha256 =
                    :source_content_sha256,
                import_key = :import_key,
                state = 'importing',
                mealie_slug = NULL,
                mealie_recipe_id = NULL,
                error = NULL,
                updated_at = :now
            WHERE import_item_id =
                :import_item_id
            """
        ),
        {
            "import_item_id": (
                import_item_id
            ),
            "source_id": source_id,
            "source_recipe_id": (
                source_recipe_id
            ),
            "source_content_sha256": (
                source_content_sha256
            ),
            "import_key": import_key,
            "now": now,
        },
    )


def record_created_slug(
    db: Session,
    *,
    import_item_id: int,
    mealie_slug: str,
) -> None:
    db.execute(
        text(
            """
            UPDATE mealie_import_records
            SET
                mealie_slug = :mealie_slug,
                updated_at = :now
            WHERE import_item_id =
                :import_item_id
            """
        ),
        {
            "import_item_id": (
                import_item_id
            ),
            "mealie_slug": mealie_slug,
            "now": utc_now(),
        },
    )


def mark_record_imported(
    db: Session,
    *,
    import_item_id: int,
    mealie_slug: str,
    mealie_recipe_id: str,
) -> None:
    db.execute(
        text(
            """
            UPDATE mealie_import_records
            SET
                state = 'imported',
                mealie_slug = :mealie_slug,
                mealie_recipe_id =
                    :mealie_recipe_id,
                error = NULL,
                updated_at = :now
            WHERE import_item_id =
                :import_item_id
            """
        ),
        {
            "import_item_id": (
                import_item_id
            ),
            "mealie_slug": mealie_slug,
            "mealie_recipe_id": (
                mealie_recipe_id
            ),
            "now": utc_now(),
        },
    )


def mark_record_failed(
    db: Session,
    *,
    import_item_id: int,
    state: str,
    error: str,
) -> None:
    db.execute(
        text(
            """
            UPDATE mealie_import_records
            SET
                state = :state,
                error = :error,
                updated_at = :now
            WHERE import_item_id =
                :import_item_id
            """
        ),
        {
            "import_item_id": (
                import_item_id
            ),
            "state": state,
            "error": error,
            "now": utc_now(),
        },
    )


def upsert_reconciled_record(
    db: Session,
    *,
    import_item_id: int,
    source_id: int,
    source_recipe_id: int,
    source_content_sha256: str,
    import_key: str,
    mealie_slug: str,
    mealie_recipe_id: str,
) -> None:
    """Restore a verified imported record without committing the transaction."""
    now = utc_now()
    db.execute(
        text(
            """
            INSERT INTO mealie_import_records (
                import_item_id,
                source_id,
                source_recipe_id,
                source_content_sha256,
                import_key,
                state,
                mealie_slug,
                mealie_recipe_id,
                error,
                created_at,
                updated_at
            )
            VALUES (
                :import_item_id,
                :source_id,
                :source_recipe_id,
                :source_content_sha256,
                :import_key,
                'imported',
                :mealie_slug,
                :mealie_recipe_id,
                NULL,
                :now,
                :now
            )
            ON CONFLICT(import_item_id) DO UPDATE SET
                source_id = excluded.source_id,
                source_recipe_id = excluded.source_recipe_id,
                source_content_sha256 = excluded.source_content_sha256,
                import_key = excluded.import_key,
                state = 'imported',
                mealie_slug = excluded.mealie_slug,
                mealie_recipe_id = excluded.mealie_recipe_id,
                error = NULL,
                updated_at = excluded.updated_at
            """
        ),
        {
            "import_item_id": import_item_id,
            "source_id": source_id,
            "source_recipe_id": source_recipe_id,
            "source_content_sha256": source_content_sha256,
            "import_key": import_key,
            "mealie_slug": mealie_slug,
            "mealie_recipe_id": mealie_recipe_id,
            "now": now,
        },
    )
