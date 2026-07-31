from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.mealie_import_records import (
    ensure_mealie_import_schema,
    get_record_by_item,
    start_import_record,
)


def test_mealie_import_record_is_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as session:
        ensure_mealie_import_schema(session)
        values = {
            "import_item_id": 1,
            "source_id": 2,
            "source_recipe_id": 3,
            "source_content_sha256": "a" * 64,
            "import_key": "2:3:" + "a" * 64,
        }
        start_import_record(session, **values)
        session.commit()
        start_import_record(session, **values)
        session.commit()
        record = get_record_by_item(session, 1)
    assert record is not None
    assert record["state"] == "importing"
    assert record["import_key"] == values["import_key"]
