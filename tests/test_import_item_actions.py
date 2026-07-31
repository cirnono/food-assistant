from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.import_queue as queue
from app.ai_recipes import NormalizedRecipe
from app.database import Base
from app.import_queue import (
    ProcessImportItemRequest,
    RestoreRejectedRequest,
    process_specific_import_item,
    restore_rejected_item,
    update_job_status,
)
from app.llm.errors import LLMProviderError
from app.main import app
from app.models import RecipeImportItem, RecipeImportJob, RecipeSource, SourceRecipe


def normalized_recipe(path: str, name: str = "test recipe") -> NormalizedRecipe:
    return NormalizedRecipe.model_validate(
        {
            "name": name,
            "original_name": name,
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


def make_session(
    *,
    item_statuses: list[str],
    normalized: bool = True,
) -> tuple[Session, RecipeImportJob, list[RecipeImportItem], RecipeSource]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    source = RecipeSource(
        name="source",
        repo_url="https://example.invalid/repository",
        branch="main",
        include_path="recipes",
    )
    db.add(source)
    db.flush()
    job = RecipeImportJob(
        source_id=source.id,
        name="job",
        selection_json="{}",
        status="approved",
        total_items=len(item_statuses),
    )
    db.add(job)
    db.flush()
    items: list[RecipeImportItem] = []
    for index, item_status in enumerate(item_statuses, start=1):
        path = f"recipe-{index}.md"
        content = f"source content {index}"
        digest = hashlib.sha256(content.encode()).hexdigest()
        recipe = SourceRecipe(
            source_id=source.id,
            path=path,
            title=f"recipe {index}",
            content_sha256=digest,
            source_commit="commit",
        )
        db.add(recipe)
        db.flush()
        item = RecipeImportItem(
            job_id=job.id,
            source_recipe_id=recipe.id,
            source_content_sha256=digest,
            source_commit="commit",
            status=item_status,
            normalized_json=(
                normalized_recipe(path).model_dump_json() if normalized else None
            ),
            error="previous rejection",
            attempts=3,
        )
        db.add(item)
        items.append(item)
    db.commit()
    return db, job, items, source


def test_restore_rejected_returns_to_review_and_preserves_audit() -> None:
    db, job, items, _ = make_session(item_statuses=["rejected"])
    item = items[0]
    before = NormalizedRecipe.model_validate_json(item.normalized_json)

    result = restore_rejected_item(
        job.id,
        item.id,
        RestoreRejectedRequest(confirm_item_id=item.id),
        db,
    )

    db.refresh(item)
    after = NormalizedRecipe.model_validate_json(item.normalized_json)
    assert result["item_status"] == "review"
    assert item.status == "review"
    assert item.attempts == 3
    assert item.error is None
    assert after.name == before.name
    assert any("Previous rejection reason: previous rejection" in w for w in after.warnings)
    db.close()


@pytest.mark.parametrize("status", ["review", "queued", "imported"])
def test_restore_rejected_refuses_other_statuses(status: str) -> None:
    db, job, items, _ = make_session(item_statuses=[status])
    with pytest.raises(HTTPException) as raised:
        restore_rejected_item(
            job.id,
            items[0].id,
            RestoreRejectedRequest(confirm_item_id=items[0].id),
            db,
        )
    assert raised.value.status_code == 409
    db.close()


def test_restore_rejected_requires_matching_confirmation_and_normalized_data() -> None:
    db, job, items, _ = make_session(item_statuses=["rejected"])
    item = items[0]
    with pytest.raises(HTTPException) as mismatch:
        restore_rejected_item(
            job.id,
            item.id,
            RestoreRejectedRequest(confirm_item_id=item.id + 1),
            db,
        )
    assert mismatch.value.status_code == 409
    item.normalized_json = None
    db.commit()
    with pytest.raises(HTTPException) as missing:
        restore_rejected_item(
            job.id,
            item.id,
            RestoreRejectedRequest(confirm_item_id=item.id),
            db,
        )
    assert missing.value.status_code == 409
    db.close()


def test_restore_api_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/import-jobs/1/items/1/restore-rejected",
            json={"confirm_item_id": 1},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_targeted_processing_only_processes_selected_item(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db, job, items, _ = make_session(item_statuses=["queued", "queued"], normalized=False)
    for index, item in enumerate(items, start=1):
        recipe = db.get(SourceRecipe, item.source_recipe_id)
        assert recipe is not None
        (tmp_path / recipe.path).write_text(f"source content {index}")

    async def normalize(**kwargs: Any) -> NormalizedRecipe:
        recipe = kwargs["recipe"]
        return normalized_recipe(recipe.path)

    monkeypatch.setattr(queue, "source_repo_dir", lambda source_id: tmp_path)
    monkeypatch.setattr(queue, "normalize_source_recipe", normalize)
    monkeypatch.setattr(
        queue,
        "apply_recipe_quality_gate",
        lambda recipe, **kwargs: (recipe, []),
    )
    result = await process_specific_import_item(
        job.id,
        items[1].id,
        ProcessImportItemRequest(
            confirm_item_id=items[1].id,
            auto_import=False,
            unload_model_after=False,
        ),
        db,
    )
    db.refresh(items[0])
    db.refresh(items[1])
    assert result["item"]["id"] == items[1].id
    assert items[0].status == "queued"
    assert items[1].status == "review"
    db.close()


@pytest.mark.asyncio
async def test_targeted_processing_rejects_non_queued_and_second_call() -> None:
    db, job, items, _ = make_session(item_statuses=["review"])
    request = ProcessImportItemRequest(
        confirm_item_id=items[0].id,
        unload_model_after=False,
    )
    with pytest.raises(HTTPException) as raised:
        await process_specific_import_item(job.id, items[0].id, request, db)
    assert raised.value.status_code == 409
    db.close()


@pytest.mark.asyncio
async def test_infrastructure_failure_returns_target_to_queue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db, job, items, _ = make_session(item_statuses=["queued"], normalized=False)
    item = items[0]
    recipe = db.get(SourceRecipe, item.source_recipe_id)
    assert recipe is not None
    (tmp_path / recipe.path).write_text("source content 1")

    async def fail(**kwargs: Any) -> NormalizedRecipe:
        del kwargs
        raise LLMProviderError("CUDA out of memory", infrastructure=True)

    monkeypatch.setattr(queue, "source_repo_dir", lambda source_id: tmp_path)
    monkeypatch.setattr(queue, "normalize_source_recipe", fail)
    with pytest.raises(HTTPException):
        await process_specific_import_item(
            job.id,
            item.id,
            ProcessImportItemRequest(
                confirm_item_id=item.id,
                unload_model_after=False,
            ),
            db,
        )
    db.refresh(item)
    assert item.status == "queued"
    db.close()


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["imported", "skipped"], "completed"),
        (["imported", "rejected", "skipped"], "completed"),
        (["imported", "queued"], "approved"),
        (["imported", "approved_for_import"], "ready_to_import"),
        (["imported", "review"], "review"),
        (["imported", "failed"], "review"),
    ],
)
def test_job_terminal_statuses(statuses: list[str], expected: str) -> None:
    db, job, _, _ = make_session(item_statuses=statuses)
    update_job_status(db, job)
    assert job.status == expected
    db.close()
