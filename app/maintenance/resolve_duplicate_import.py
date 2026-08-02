from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_database
from app.import_queue import update_job_status
from app.mealie_import_records import (
    ensure_mealie_import_schema,
    get_record_by_item,
    utc_now,
)
from app.models import RecipeImportItem, RecipeImportJob, SourceRecipe


class DuplicateResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ItemIdentity:
    item: RecipeImportItem
    job: RecipeImportJob
    recipe: SourceRecipe
    source_id: int
    source_path: str
    source_sha256: str
    normalized_name: str | None
    normalized_source_path: str | None
    normalized_source_sha256: str | None


def _identity(db: Session, *, job_id: int, item_id: int) -> ItemIdentity:
    job = db.get(RecipeImportJob, job_id)
    item = db.get(RecipeImportItem, item_id)
    if job is None or item is None or item.job_id != job_id:
        raise DuplicateResolutionError("Import job or item was not found")
    recipe = db.get(SourceRecipe, item.source_recipe_id)
    if recipe is None or recipe.source_id != job.source_id:
        raise DuplicateResolutionError("Source recipe identity is invalid")

    normalized: dict[str, Any] = {}
    if item.normalized_json:
        try:
            value = json.loads(item.normalized_json)
        except json.JSONDecodeError:
            value = {}
        if isinstance(value, dict):
            normalized = value
    source = normalized.get("source")
    if not isinstance(source, dict):
        source = {}
    return ItemIdentity(
        item=item,
        job=job,
        recipe=recipe,
        source_id=job.source_id,
        source_path=recipe.path,
        source_sha256=item.source_content_sha256,
        normalized_name=normalized.get("name"),
        normalized_source_path=source.get("source_path"),
        normalized_source_sha256=(
            source.get("source_sha256")
            or source.get("source_content_sha256")
            or item.source_content_sha256
        ),
    )


def inspect_duplicate(
    db: Session,
    *,
    job_id: int,
    item_id: int,
    duplicate_of_item_id: int,
) -> dict[str, Any]:
    target = _identity(db, job_id=job_id, item_id=item_id)
    reference = _identity(
        db,
        job_id=job_id,
        item_id=duplicate_of_item_id,
    )
    record = get_record_by_item(db, reference.item.id)
    checks = {
        "same_job": target.item.job_id == reference.item.job_id,
        "reference_is_imported": reference.item.status == "imported",
        "reference_record_is_imported": bool(
            record
            and record.get("state") == "imported"
            and record.get("mealie_slug")
            and record.get("mealie_recipe_id")
        ),
        "same_source_id": target.source_id == reference.source_id,
        "same_source_path": target.source_path == reference.source_path,
        "same_source_sha256": target.source_sha256 == reference.source_sha256,
        "same_normalized_source_path": (
            target.normalized_source_path == reference.normalized_source_path
        ),
        "same_normalized_source_sha256": (
            target.normalized_source_sha256
            == reference.normalized_source_sha256
        ),
        "same_normalized_name": (
            target.normalized_name == reference.normalized_name
        ),
    }
    exact_source_identity = all(
        checks[key]
        for key in ("same_source_id", "same_source_path", "same_source_sha256")
    )
    equivalent_content_identity = all(
        checks[key]
        for key in (
            "same_source_id",
            "same_source_sha256",
            "same_normalized_source_path",
            "same_normalized_source_sha256",
        )
    )
    eligible = all(
        checks[key]
        for key in (
            "same_job",
            "reference_is_imported",
            "reference_record_is_imported",
        )
    ) and (exact_source_identity or equivalent_content_identity)
    reason = (
        "exact_source_identity"
        if exact_source_identity
        else "equivalent_content_and_normalized_source_identity"
        if equivalent_content_identity
        else "source_identity_mismatch"
    )
    return {
        "job_id": job_id,
        "item_id": item_id,
        "duplicate_of_item_id": duplicate_of_item_id,
        "checks": checks,
        "reason": reason,
        "eligible": eligible,
        "reference_record": record,
        "target": target,
    }


def resolve_duplicate(
    db: Session,
    *,
    job_id: int,
    item_id: int,
    duplicate_of_item_id: int,
    confirm_item_id: int | None = None,
) -> dict[str, Any]:
    inspection = inspect_duplicate(
        db,
        job_id=job_id,
        item_id=item_id,
        duplicate_of_item_id=duplicate_of_item_id,
    )
    public = {
        key: value
        for key, value in inspection.items()
        if key not in {"reference_record", "target"}
    }
    public["dry_run"] = confirm_item_id is None
    public["resolved"] = False
    if confirm_item_id is None:
        return public
    if confirm_item_id != item_id:
        raise DuplicateResolutionError("Confirmation item id does not match")
    if not inspection["eligible"]:
        raise DuplicateResolutionError("Duplicate source identity is not verified")

    target: ItemIdentity = inspection["target"]
    record = inspection["reference_record"]
    if target.item.status in {"imported", "skipped"}:
        raise DuplicateResolutionError("Target item is already terminal")
    target.item.status = "skipped"
    target.item.error = None
    target.item.duplicate_of_item_id = duplicate_of_item_id
    target.item.duplicate_mealie_slug = str(record["mealie_slug"])
    target.item.duplicate_reason = str(inspection["reason"])

    existing_target_record = get_record_by_item(db, target.item.id)
    if existing_target_record is not None:
        db.execute(
            text(
                """
                UPDATE mealie_import_records
                SET state = 'skipped_duplicate',
                    mealie_slug = :slug,
                    mealie_recipe_id = :recipe_id,
                    error = NULL,
                    updated_at = :now
                WHERE import_item_id = :item_id
                """
            ),
            {
                "slug": record["mealie_slug"],
                "recipe_id": record["mealie_recipe_id"],
                "now": utc_now(),
                "item_id": target.item.id,
            },
        )

    db.flush()
    counts = update_job_status(db, target.job)
    db.commit()
    public.update(
        {
            "dry_run": False,
            "resolved": True,
            "item_status": target.item.status,
            "status_counts": counts,
        }
    )
    return public


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve a fully verified duplicate import item."
    )
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--item-id", type=int, required=True)
    parser.add_argument("--duplicate-of-item-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-item-id", type=int)
    args = parser.parse_args()
    if args.dry_run and args.confirm_item_id is not None:
        parser.error("--dry-run and --confirm-item-id are mutually exclusive")
    return args


def main() -> int:
    args = parse_args()
    init_database()
    with SessionLocal() as db:
        ensure_mealie_import_schema(db)
        result = resolve_duplicate(
            db,
            job_id=args.job_id,
            item_id=args.item_id,
            duplicate_of_item_id=args.duplicate_of_item_id,
            confirm_item_id=args.confirm_item_id,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
