from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable
import unicodedata

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai_recipes import NormalizedRecipe
from app.database import SessionLocal, init_database
from app.import_queue import load_source_content_for_import, update_job_status
from app.mealie_entities import extract_items
from app.mealie_import_records import (
    ensure_mealie_import_schema,
    upsert_reconciled_record,
)
from app.mealie_importer import MealieWriter, build_import_key
from app.models import RecipeImportItem, RecipeImportJob, RecipeSource, SourceRecipe


class ReconcileError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExpectedImportIdentity:
    job: RecipeImportJob
    item: RecipeImportItem
    source: RecipeSource
    recipe: SourceRecipe
    import_key: str
    source_path: str
    source_sha256: str


def build_expected_identity(
    db: Session,
    *,
    job_id: int,
    item_id: int,
    source_loader: Callable[[RecipeSource, SourceRecipe, RecipeImportItem], str] = (
        load_source_content_for_import
    ),
) -> ExpectedImportIdentity:
    job = db.get(RecipeImportJob, job_id)
    item = db.get(RecipeImportItem, item_id)
    if job is None or item is None or item.job_id != job_id:
        raise ReconcileError("Import job or item was not found")

    source = db.get(RecipeSource, job.source_id)
    recipe = db.get(SourceRecipe, item.source_recipe_id)
    if source is None or recipe is None or recipe.source_id != source.id:
        raise ReconcileError("Import source or source recipe was not found")

    if not item.normalized_json:
        raise ReconcileError("Import item has no normalized recipe")
    try:
        normalized = NormalizedRecipe.model_validate_json(item.normalized_json)
    except ValidationError as exc:
        raise ReconcileError("Import item normalized recipe is invalid") from exc

    source_loader(source, recipe, item)
    normalized_path = normalized.source.source_path
    if normalized_path != recipe.path:
        raise ReconcileError("Normalized source path does not match the import item")

    return ExpectedImportIdentity(
        job=job,
        item=item,
        source=source,
        recipe=recipe,
        import_key=build_import_key(
            source_id=source.id,
            source_recipe_id=recipe.id,
            source_content_sha256=item.source_content_sha256,
        ),
        source_path=recipe.path,
        source_sha256=item.source_content_sha256,
    )


async def _recipe_summaries(writer: MealieWriter, *, search: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    target_name = unicodedata.normalize("NFKC", search).strip().casefold()
    for page in range(1, 101):
        value = await writer.request_json(
            "GET",
            "/api/recipes",
            params={"page": page, "perPage": 100, "search": search},
            expected_statuses={200},
        )
        items = extract_items(value)
        new_items = 0
        for item in items:
            item_name = item.get("name")
            if (
                not isinstance(item_name, str)
                or unicodedata.normalize("NFKC", item_name).strip().casefold()
                != target_name
            ):
                continue
            slug = item.get("slug")
            if not isinstance(slug, str) or not slug or slug in seen:
                continue
            seen.add(slug)
            results.append(item)
            new_items += 1
        total_pages = value.get("total_pages") if isinstance(value, dict) else None
        if isinstance(total_pages, int) and page >= total_pages:
            break
        if not isinstance(total_pages, int) and len(items) < 100:
            break
    return results


def _validation(recipe: dict[str, Any], expected: ExpectedImportIdentity) -> dict[str, bool]:
    extras = recipe.get("extras")
    if not isinstance(extras, dict):
        extras = {}
    managed = extras.get("foodAssistantManaged")
    managed_matches = managed is True or managed == 1 or (
        isinstance(managed, str)
        and managed.strip().casefold() in {"1", "true", "yes"}
    )
    return {
        "foodAssistantManaged": managed_matches,
        "foodAssistantImportKey": (
            extras.get("foodAssistantImportKey") == expected.import_key
        ),
        "foodAssistantSourcePath": (
            extras.get("foodAssistantSourcePath") == expected.source_path
        ),
        "foodAssistantSourceSha256": (
            extras.get("foodAssistantSourceSha256") == expected.source_sha256
        ),
    }


async def inspect_candidates(
    writer: MealieWriter,
    expected: ExpectedImportIdentity,
) -> list[dict[str, Any]]:
    normalized = NormalizedRecipe.model_validate_json(expected.item.normalized_json)
    summaries = await _recipe_summaries(writer, search=normalized.name)
    candidates: list[dict[str, Any]] = []
    for summary in summaries:
        slug = summary.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        recipe = await writer.get_recipe(slug)
        recipe_id = recipe.get("id")
        if not isinstance(recipe_id, str) or not recipe_id:
            continue
        validation = _validation(recipe, expected)
        candidates.append(
            {
                "slug": slug,
                "recipe_id": recipe_id,
                "validation": validation,
                "all_fields_match": all(validation.values()),
            }
        )
    return candidates


async def reconcile_import(
    db: Session,
    writer: MealieWriter,
    *,
    job_id: int,
    item_id: int,
    confirm_item_id: int | None = None,
    source_loader: Callable[[RecipeSource, SourceRecipe, RecipeImportItem], str] = (
        load_source_content_for_import
    ),
) -> dict[str, Any]:
    expected = build_expected_identity(
        db,
        job_id=job_id,
        item_id=item_id,
        source_loader=source_loader,
    )
    candidates = await inspect_candidates(writer, expected)
    matches = [candidate for candidate in candidates if candidate["all_fields_match"]]
    result: dict[str, Any] = {
        "job_id": job_id,
        "item_id": item_id,
        "dry_run": confirm_item_id is None,
        "candidate_count": len(candidates),
        "verified_match_count": len(matches),
        "candidates": candidates,
        "reconciled": False,
    }
    if confirm_item_id is None:
        return result
    if confirm_item_id != item_id:
        raise ReconcileError("Confirmation item id does not match")
    if len(matches) != 1:
        raise ReconcileError("Exactly one fully verified Mealie recipe is required")

    match = matches[0]
    try:
        ensure_mealie_import_schema(db)
        upsert_reconciled_record(
            db,
            import_item_id=expected.item.id,
            source_id=expected.source.id,
            source_recipe_id=expected.recipe.id,
            source_content_sha256=expected.source_sha256,
            import_key=expected.import_key,
            mealie_slug=match["slug"],
            mealie_recipe_id=match["recipe_id"],
        )
        expected.item.status = "imported"
        expected.item.error = None
        update_job_status(db, expected.job)
        db.commit()
    except Exception:
        db.rollback()
        raise

    result["dry_run"] = False
    result["reconciled"] = True
    result["job_status"] = expected.job.status
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely reconcile an existing managed Mealie import."
    )
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--item-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-item-id", type=int)
    args = parser.parse_args()
    if args.confirm_item_id is not None and args.dry_run:
        parser.error("--dry-run and --confirm-item-id are mutually exclusive")
    return args


async def async_main() -> int:
    args = parse_args()
    init_database()
    with SessionLocal() as db:
        ensure_mealie_import_schema(db)
        result = await reconcile_import(
            db,
            MealieWriter(),
            job_id=args.job_id,
            item_id=args.item_id,
            confirm_item_id=args.confirm_item_id,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
