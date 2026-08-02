from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai_recipes import NormalizedRecipe
from app.database import Base
from app.maintenance.reconcile_mealie_import import (
    ReconcileError,
    reconcile_import,
)
from app.mealie_import_records import ensure_mealie_import_schema, get_record_by_item
from app.mealie_importer import build_import_key
from app.models import RecipeImportItem, RecipeImportJob, RecipeSource, SourceRecipe


class FakeWriter:
    def __init__(self, recipes: list[dict[str, Any]]) -> None:
        self.recipes = recipes
        self.methods: list[str] = []

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        params: dict[str, Any] | None = None,
        expected_statuses: set[int],
    ) -> Any:
        del payload, params, expected_statuses
        self.methods.append(method)
        assert method == "GET"
        assert path == "/api/recipes"
        return {
            "items": [
                {"slug": recipe["slug"], "name": recipe["name"]}
                for recipe in self.recipes
            ],
            "total_pages": 1,
        }

    async def get_recipe(self, slug: str) -> dict[str, Any]:
        self.methods.append("GET")
        return next(recipe for recipe in self.recipes if recipe["slug"] == slug)


def normalized_json(path: str) -> str:
    recipe = NormalizedRecipe.model_validate(
        {
            "name": "existing recipe",
            "original_name": "existing recipe",
            "cuisine": "中餐",
            "categories": ["主菜"],
            "tags": ["test"],
            "ingredients": [{"food_name": "food", "original_text": "food"}],
            "instructions": [{"step_number": 1, "text": "cook"}],
            "source": {"source_path": path},
            "import_score": 100,
            "recommendation": "import",
        }
    )
    return recipe.model_dump_json()


def make_session() -> tuple[Session, RecipeImportJob, RecipeImportItem, str]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    ensure_mealie_import_schema(session)
    source = RecipeSource(
        name="source",
        repo_url="https://example.invalid/repository",
        branch="main",
        include_path="recipes",
    )
    session.add(source)
    session.flush()
    path = "recipes/example.md"
    recipe = SourceRecipe(
        source_id=source.id,
        path=path,
        title="existing recipe",
        content_sha256="a" * 64,
        source_commit="commit",
    )
    session.add(recipe)
    session.flush()
    job = RecipeImportJob(
        source_id=source.id,
        name="job",
        selection_json="{}",
        status="review",
        total_items=1,
    )
    session.add(job)
    session.flush()
    item = RecipeImportItem(
        job_id=job.id,
        source_recipe_id=recipe.id,
        source_content_sha256="a" * 64,
        source_commit="commit",
        status="approved_for_import",
        normalized_json=normalized_json(path),
        error="old error",
    )
    session.add(item)
    session.commit()
    return session, job, item, path


def managed_recipe(
    *,
    source_id: int,
    source_recipe_id: int,
    path: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extras: dict[str, Any] = {
        "foodAssistantManaged": "1",
        "foodAssistantImportKey": build_import_key(
            source_id=source_id,
            source_recipe_id=source_recipe_id,
            source_content_sha256="a" * 64,
        ),
        "foodAssistantSourcePath": path,
        "foodAssistantSourceSha256": "a" * 64,
    }
    extras.update(overrides or {})
    return {
        "id": "mealie-id",
        "slug": "existing-recipe",
        "name": "existing recipe",
        "extras": extras,
    }


def source_loader(*args: Any) -> str:
    del args
    return "source content"


@pytest.mark.asyncio
async def test_dry_run_never_updates_database() -> None:
    db, job, item, path = make_session()
    writer = FakeWriter(
        [
            managed_recipe(
                source_id=job.source_id,
                source_recipe_id=item.source_recipe_id,
                path=path,
            )
        ]
    )

    result = await reconcile_import(
        db,
        writer,
        job_id=job.id,
        item_id=item.id,
        source_loader=source_loader,
    )

    assert result["dry_run"] is True
    assert result["verified_match_count"] == 1
    assert get_record_by_item(db, item.id) is None
    assert item.status == "approved_for_import"
    assert set(writer.methods) == {"GET"}
    db.close()


@pytest.mark.asyncio
async def test_confirm_reconciles_item_record_and_job() -> None:
    db, job, item, path = make_session()
    writer = FakeWriter(
        [
            managed_recipe(
                source_id=job.source_id,
                source_recipe_id=item.source_recipe_id,
                path=path,
            )
        ]
    )

    result = await reconcile_import(
        db,
        writer,
        job_id=job.id,
        item_id=item.id,
        confirm_item_id=item.id,
        source_loader=source_loader,
    )

    db.refresh(item)
    db.refresh(job)
    record = get_record_by_item(db, item.id)
    assert result["reconciled"] is True
    assert item.status == "imported"
    assert item.error is None
    assert job.status == "completed"
    assert record is not None
    assert record["state"] == "imported"
    assert record["mealie_slug"] == "existing-recipe"
    assert record["mealie_recipe_id"] == "mealie-id"
    assert set(writer.methods) == {"GET"}
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"foodAssistantManaged": False},
        {"foodAssistantImportKey": "wrong"},
        {"foodAssistantSourcePath": "wrong"},
        {"foodAssistantSourceSha256": "wrong"},
    ],
)
async def test_any_identity_mismatch_refuses_recovery(
    overrides: dict[str, Any],
) -> None:
    db, job, item, path = make_session()
    writer = FakeWriter(
        [
            managed_recipe(
                source_id=job.source_id,
                source_recipe_id=item.source_recipe_id,
                path=path,
                overrides=overrides,
            )
        ]
    )

    with pytest.raises(ReconcileError, match="Exactly one"):
        await reconcile_import(
            db,
            writer,
            job_id=job.id,
            item_id=item.id,
            confirm_item_id=item.id,
            source_loader=source_loader,
        )

    assert get_record_by_item(db, item.id) is None
    assert item.status == "approved_for_import"
    db.close()


@pytest.mark.asyncio
async def test_confirmation_id_must_match() -> None:
    db, job, item, path = make_session()
    writer = FakeWriter(
        [
            managed_recipe(
                source_id=job.source_id,
                source_recipe_id=item.source_recipe_id,
                path=path,
            )
        ]
    )

    with pytest.raises(ReconcileError, match="Confirmation"):
        await reconcile_import(
            db,
            writer,
            job_id=job.id,
            item_id=item.id,
            confirm_item_id=item.id + 1,
            source_loader=source_loader,
        )

    assert get_record_by_item(db, item.id) is None
    db.close()
