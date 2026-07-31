from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.ai_recipes import NormalizedRecipe
from app.maintenance.resolve_duplicate_import import (
    DuplicateResolutionError,
    resolve_duplicate,
)
from app.mealie_import_records import (
    ensure_mealie_import_schema,
    mark_record_imported,
    start_import_record,
)
from app.mealie_importer import build_import_key
from app.models import RecipeImportItem, RecipeImportJob, RecipeSource, SourceRecipe


def normalized_recipe(path: str) -> NormalizedRecipe:
    return NormalizedRecipe.model_validate(
        {
            "name": "same recipe",
            "original_name": "same recipe",
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


def duplicate_session(
    *,
    same_sha: bool = True,
    reference_status: str = "imported",
    create_record: bool = True,
) -> tuple[Session, RecipeImportJob, RecipeImportItem, RecipeImportItem]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ensure_mealie_import_schema(db)
    source = RecipeSource(
        name="source",
        repo_url="https://example.invalid/repository",
        branch="main",
        include_path="recipes",
    )
    db.add(source)
    db.flush()
    digest = hashlib.sha256(b"same content").hexdigest()
    other_digest = hashlib.sha256(b"different content").hexdigest()
    reference_recipe = SourceRecipe(
        source_id=source.id,
        path="first/source.md",
        title="same recipe",
        content_sha256=digest,
        source_commit="commit",
    )
    target_recipe = SourceRecipe(
        source_id=source.id,
        path="second/source.md",
        title="same recipe",
        content_sha256=digest if same_sha else other_digest,
        source_commit="commit",
    )
    db.add_all([reference_recipe, target_recipe])
    db.flush()
    job = RecipeImportJob(
        source_id=source.id,
        name="job",
        selection_json="{}",
        status="ready_to_import",
        total_items=2,
    )
    db.add(job)
    db.flush()
    normalized_path = "canonical/source.md"
    reference = RecipeImportItem(
        job_id=job.id,
        source_recipe_id=reference_recipe.id,
        source_content_sha256=digest,
        source_commit="commit",
        status=reference_status,
        normalized_json=normalized_recipe(normalized_path).model_dump_json(),
    )
    target = RecipeImportItem(
        job_id=job.id,
        source_recipe_id=target_recipe.id,
        source_content_sha256=digest if same_sha else other_digest,
        source_commit="commit",
        status="approved_for_import",
        normalized_json=normalized_recipe(normalized_path).model_dump_json(),
    )
    db.add_all([reference, target])
    db.flush()
    if create_record:
        import_key = build_import_key(
            source_id=source.id,
            source_recipe_id=reference_recipe.id,
            source_content_sha256=digest,
        )
        start_import_record(
            db,
            import_item_id=reference.id,
            source_id=source.id,
            source_recipe_id=reference_recipe.id,
            source_content_sha256=digest,
            import_key=import_key,
        )
        mark_record_imported(
            db,
            import_item_id=reference.id,
            mealie_slug="existing-recipe",
            mealie_recipe_id="mealie-id",
        )
    db.commit()
    return db, job, reference, target


def test_verified_equivalent_source_can_be_skipped_duplicate() -> None:
    db, job, reference, target = duplicate_session()
    result = resolve_duplicate(
        db,
        job_id=job.id,
        item_id=target.id,
        duplicate_of_item_id=reference.id,
        confirm_item_id=target.id,
    )
    db.refresh(target)
    assert result["resolved"] is True
    assert target.status == "skipped"
    assert target.duplicate_of_item_id == reference.id
    assert target.duplicate_mealie_slug == "existing-recipe"
    assert target.duplicate_reason == "equivalent_content_and_normalized_source_identity"
    db.close()


def test_same_name_with_different_sha_is_not_duplicate() -> None:
    db, job, reference, target = duplicate_session(same_sha=False)
    result = resolve_duplicate(
        db,
        job_id=job.id,
        item_id=target.id,
        duplicate_of_item_id=reference.id,
    )
    assert result["eligible"] is False
    with pytest.raises(DuplicateResolutionError):
        resolve_duplicate(
            db,
            job_id=job.id,
            item_id=target.id,
            duplicate_of_item_id=reference.id,
            confirm_item_id=target.id,
        )
    db.close()


def test_duplicate_items_must_share_job() -> None:
    db, job, reference, target = duplicate_session()
    other_job = RecipeImportJob(
        source_id=job.source_id,
        name="other",
        selection_json="{}",
        status="review",
        total_items=1,
    )
    db.add(other_job)
    db.flush()
    target.job_id = other_job.id
    db.commit()
    with pytest.raises(DuplicateResolutionError):
        resolve_duplicate(
            db,
            job_id=other_job.id,
            item_id=target.id,
            duplicate_of_item_id=reference.id,
        )
    db.close()


@pytest.mark.parametrize(
    ("reference_status", "create_record"),
    [("review", True), ("imported", False)],
)
def test_reference_must_be_imported_with_record(
    reference_status: str,
    create_record: bool,
) -> None:
    db, job, reference, target = duplicate_session(
        reference_status=reference_status,
        create_record=create_record,
    )
    result = resolve_duplicate(
        db,
        job_id=job.id,
        item_id=target.id,
        duplicate_of_item_id=reference.id,
    )
    assert result["eligible"] is False
    db.close()


def test_duplicate_dry_run_does_not_write() -> None:
    db, job, reference, target = duplicate_session()
    result = resolve_duplicate(
        db,
        job_id=job.id,
        item_id=target.id,
        duplicate_of_item_id=reference.id,
    )
    db.refresh(target)
    assert result["dry_run"] is True
    assert target.status == "approved_for_import"
    assert target.duplicate_of_item_id is None
    db.close()


def test_duplicate_confirmation_must_match_target() -> None:
    db, job, reference, target = duplicate_session()
    with pytest.raises(DuplicateResolutionError, match="Confirmation"):
        resolve_duplicate(
            db,
            job_id=job.id,
            item_id=target.id,
            duplicate_of_item_id=reference.id,
            confirm_item_id=target.id + 1,
        )
    db.close()
