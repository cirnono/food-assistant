from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.ai_recipes import (
    NormalizedRecipe,
    SYSTEM_PROMPT,
    repair_normalized_recipe_payload,
)
from app.database import get_db
from app.github_sources import source_repo_dir
from app.ingredient_policy import inventory_policy_for_food
from app.mealie_importer import (
    MealieImportError,
    MealieWriter,
    build_import_key,
    build_mealie_native_ingredients,
    build_mealie_patch_payload,
    build_mealie_preview,
    verify_mealie_recipe,
)
from app.mealie_entities import (
    resolve_recipe_entities,
    verify_native_structure,
)
from app.mealie_import_records import (
    ensure_mealie_import_schema,
    get_record_by_item,
    get_record_by_key,
    mark_record_failed,
    mark_record_imported,
    record_created_slug,
    start_import_record,
)
from app.llm.errors import is_infrastructure_error
from app.llm.factory import get_llm_provider
from app.models import (
    RecipeImportItem,
    RecipeImportJob,
    RecipeSource,
    SourceRecipe,
)
from app.ollama_client import (
    OLLAMA_MODEL,
    OllamaClientError,
)
from app.recipe_quality import apply_recipe_quality_gate


router = APIRouter(
    prefix="/api/v1/import-jobs",
    tags=["recipe-import-jobs"],
)


SelectionMode = Literal[
    "all",
    "filter",
    "ids",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class AutoImportRequest(StrictModel):
    confirm_job_id: int = Field(
        ge=1,
    )

    max_items: int = Field(
        default=20,
        ge=1,
        le=100,
    )

    stop_after_consecutive_failures: int = Field(
        default=3,
        ge=1,
        le=10,
    )


class ProcessAndAutoImportRequest(
    StrictModel
):
    count: int = Field(
        default=20,
        ge=1,
        le=100,
    )

    unload_model_after_batch: bool = True


class ImportJobCreate(StrictModel):
    source_id: int = Field(ge=1)

    name: str | None = Field(
        default=None,
        max_length=200,
    )

    mode: SelectionMode

    q: str | None = Field(
        default=None,
        max_length=200,
    )

    category: str | None = Field(
        default=None,
        max_length=300,
    )

    recipe_ids: list[int] = Field(
        default_factory=list,
        max_length=1000,
    )

    max_items: int = Field(
        default=50,
        ge=1,
        le=1000,
    )


class ImportJobApproval(StrictModel):
    confirm_total: int = Field(
        ge=1,
    )



class ImportBatchRequest(StrictModel):
    count: int = Field(
        default=3,
        ge=1,
        le=5,
    )



class ImportItemUpdate(StrictModel):
    normalized: NormalizedRecipe

    review_note: str | None = Field(
        default=None,
        max_length=2000,
    )


class ImportItemApproval(StrictModel):
    confirm_name: str = Field(
        min_length=1,
        max_length=200,
    )

    acknowledge_warnings: bool = False

    review_note: str | None = Field(
        default=None,
        max_length=2000,
    )


class ImportItemRejection(StrictModel):
    reason: str = Field(
        min_length=2,
        max_length=2000,
    )


class RestoreRejectedRequest(StrictModel):
    confirm_item_id: int = Field(ge=1)


class ProcessImportItemRequest(StrictModel):
    confirm_item_id: int = Field(ge=1)
    auto_import: bool = False
    unload_model_after: bool = True


class MealieImportConfirmation(StrictModel):
    confirm_item_id: int = Field(
        ge=1,
    )

    confirm_name: str = Field(
        min_length=1,
        max_length=200,
    )


def get_job_or_404(
    db: Session,
    job_id: int,
) -> RecipeImportJob:
    job = db.get(
        RecipeImportJob,
        job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Import job not found",
        )

    return job


def get_item_or_404(
    db: Session,
    job_id: int,
    item_id: int,
) -> RecipeImportItem:
    item = db.scalar(
        select(RecipeImportItem).where(
            RecipeImportItem.id == item_id,
            RecipeImportItem.job_id == job_id,
        )
    )

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Import item not found",
        )

    return item


def is_ignorable_timer_warning(
    warning: str,
) -> bool:
    """
    兼容升级前已经保存的范围计时器警告。

    正常的范围计时器不再需要人工确认；无效范围仍由
    [必须修正] 规则阻断。
    """
    value = str(warning)

    if not (
        value.startswith("[需要确认]")
        or value.startswith("[系统校验]")
    ):
        return False

    timer_phrases = (
        "包含时间范围",
        "范围计时器建议",
        "接受范围计时器",
        "没有自动生成单一计时器",
    )

    return any(
        phrase in value
        for phrase in timer_phrases
    )


def classify_import_warnings(
    recipe: NormalizedRecipe,
) -> dict[str, list[str]]:
    blocking: list[str] = []
    confirmation: list[str] = []
    ignored: list[str] = []

    for raw_warning in recipe.warnings:
        warning = str(raw_warning)

        if warning.startswith(
            "[必须修正]"
        ):
            blocking.append(warning)
            continue

        if (
            warning.startswith(
                "[需要确认]"
            )
            or warning.startswith(
                "[系统校验]"
            )
        ):
            if is_ignorable_timer_warning(
                warning
            ):
                ignored.append(warning)
            else:
                confirmation.append(
                    warning
                )

    return {
        "blocking": blocking,
        "confirmation": confirmation,
        "ignored": ignored,
    }


def job_status_counts(
    db: Session,
    job_id: int,
) -> dict[str, int]:
    rows = db.execute(
        select(
            RecipeImportItem.status,
            func.count(),
        )
        .where(
            RecipeImportItem.job_id == job_id
        )
        .group_by(
            RecipeImportItem.status
        )
    ).all()

    return {
        str(item_status): int(count)
        for item_status, count in rows
    }


def update_job_status(
    db: Session,
    job: RecipeImportJob,
) -> dict[str, int]:
    counts = job_status_counts(
        db,
        job.id,
    )

    if job.status == "cancelled":
        return counts

    terminal_statuses = {
        "imported",
        "rejected",
        "skipped",
        "cancelled",
    }
    terminal_count = sum(
        counts.get(item_status, 0)
        for item_status in terminal_statuses
    )
    imported = counts.get("imported", 0)
    rejected = counts.get("rejected", 0)
    skipped = counts.get("skipped", 0)
    cancelled = counts.get("cancelled", 0)
    approved = counts.get(
        "approved_for_import",
        0,
    )

    if (
        terminal_count == job.total_items
    ):
        job.status = "completed"

    elif counts.get("processing", 0) > 0:
        job.status = "processing"

    elif counts.get("queued", 0) > 0:
        if job.status in {
            "approved",
            "processing",
            "review",
        }:
            job.status = "approved"
        else:
            job.status = "draft"

    elif (
        counts.get("failed", 0) > 0
        or counts.get("source_updated", 0) > 0
        or counts.get("review", 0) > 0
    ):
        job.status = "review"

    elif (
        approved + imported + rejected + skipped + cancelled
        == job.total_items
        and approved > 0
    ):
        job.status = "ready_to_import"

    else:
        job.status = "review"

    return counts


def load_normalized_json(
    raw_value: str | None,
) -> dict | None:
    if not raw_value:
        return None

    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def existing_normalized_names(
    db: Session,
    job_id: int,
) -> list[str]:
    values = db.scalars(
        select(
            RecipeImportItem.normalized_json
        ).where(
            RecipeImportItem.job_id == job_id,
            RecipeImportItem.normalized_json
            .is_not(None),
        )
    ).all()

    names: list[str] = []

    for raw_value in values:
        payload = load_normalized_json(
            raw_value
        )

        if not payload:
            continue

        name = payload.get("name")

        if isinstance(name, str) and name:
            names.append(name)

    return sorted(set(names))


def build_source_url(
    source: RecipeSource,
    recipe: SourceRecipe,
) -> str:
    repository_url = (
        source.repo_url.removesuffix(".git")
    )

    branch = source.branch or "master"

    encoded_path = quote(
        recipe.path,
        safe="/",
    )

    return (
        f"{repository_url}/blob/"
        f"{quote(branch, safe='/')}/"
        f"{encoded_path}"
    )


V20_VALID_CATEGORIES = (
    "早餐",
    "午餐",
    "晚餐",
    "主食",
    "主菜",
    "配菜",
    "汤",
    "凉菜",
    "甜点",
    "饮品",
)


V20_NORMALIZED_RECIPE_FIELDS = {
    "name",
    "original_name",
    "description",
    "cuisine",
    "categories",
    "tags",
    "servings",
    "prep_time_minutes",
    "cook_time_minutes",
    "total_time_minutes",
    "ingredients",
    "instructions",
    "source",
    "import_score",
    "recommendation",
    "possible_duplicate",
    "duplicate_candidates",
    "warnings",
    "review_required",
}


def _v20_copy_alias(
    data: dict,
    target: str,
    aliases: tuple[str, ...],
) -> None:
    if (
        target in data
        and data[target] is not None
    ):
        return

    for alias in aliases:
        value = data.get(alias)

        if value is not None:
            data[target] = value
            return


def _v20_fallback_category(
    recipe_name: str,
) -> str:
    name = recipe_name.casefold()

    if any(
        word in name
        for word in (
            "奶茶",
            "茶饮",
            "饮料",
            "果汁",
            "咖啡",
            "莫吉托",
            "鸡尾酒",
            "特调",
        )
    ):
        return "饮品"

    if any(
        word in name
        for word in (
            "蛋糕",
            "蛋挞",
            "雪媚娘",
            "甜品",
            "布丁",
            "奶冻",
            "糍粑",
            "炸鲜奶",
        )
    ):
        return "甜点"

    if any(
        word in name
        for word in (
            "面包",
            "馒头",
            "饼",
            "饭",
            "面",
            "粉",
            "粥",
        )
    ):
        return "主食"

    if any(
        word in name
        for word in (
            "汤",
            "羹",
        )
    ):
        return "汤"

    if any(
        word in name
        for word in (
            "酱",
            "汁",
            "辣子",
            "糖色",
            "葱油",
            "调味",
        )
    ):
        return "配菜"

    return "主菜"


def _v20_normalize_categories(
    raw_value: object,
    *,
    recipe_name: str,
) -> list[str]:
    if isinstance(raw_value, str):
        raw_values = [
            raw_value
        ]

    elif isinstance(raw_value, list):
        raw_values = raw_value

    else:
        raw_values = []

    normalized: list[str] = []

    for raw in raw_values:
        if not isinstance(
            raw,
            (
                str,
                int,
                float,
            ),
        ):
            continue

        value = str(raw).strip()

        if not value:
            continue

        compact = value.replace(
            " ",
            "",
        )

        category: str | None = None

        if value in V20_VALID_CATEGORIES:
            category = value

        elif compact == "配菜":
            category = "配菜"

        elif compact in {
            "调味",
            "调味料",
            "调味汁",
            "酱料",
            "蘸料",
            "佐料",
            "辅料",
        }:
            category = "配菜"

        elif compact in {
            "饮料",
            "酒水",
            "鸡尾酒",
        }:
            category = "饮品"

        elif compact in {
            "汤羹",
            "羹汤",
        }:
            category = "汤"

        elif compact == "小吃":
            category = (
                _v20_fallback_category(
                    recipe_name
                )
            )

        # 炖、炒、煎、炸、蒸、烤等属于技法，
        # 不作为 Mealie 主分类写入。
        if (
            category
            and category not in normalized
        ):
            normalized.append(category)

    if not normalized:
        normalized.append(
            _v20_fallback_category(
                recipe_name
            )
        )

    return normalized


def _v20_compact_validation_errors(
    exc: ValidationError,
) -> list[dict]:
    compact: list[dict] = []

    for error in exc.errors(
        include_url=False
    ):
        entry = {
            "loc": [
                str(value)
                for value in error.get(
                    "loc",
                    (),
                )
            ],
            "type": error.get("type"),
            "msg": error.get("msg"),
        }

        if "input" in error:
            entry["input_preview"] = str(
                error["input"]
            )[:500]

        compact.append(entry)

    return compact


def _v20_prepare_normalized_payload(
    payload: object,
    *,
    source_metadata: dict,
    source_title: str,
) -> dict:
    if not isinstance(payload, dict):
        return {}

    data = dict(payload)

    # 兼容模型额外包了一层 recipe/data/result/output。
    for wrapper in (
        "recipe",
        "data",
        "result",
        "output",
    ):
        candidate = data.get(wrapper)

        if not isinstance(candidate, dict):
            continue

        candidate_keys = set(
            candidate
        )

        if len(
            candidate_keys
            & V20_NORMALIZED_RECIPE_FIELDS
        ) >= 3:
            outer_source = data.get(
                "source"
            )

            data = dict(candidate)

            if (
                "source" not in data
                and outer_source is not None
            ):
                data["source"] = (
                    outer_source
                )

            break

    # 某些回答把整个菜谱对象错误塞进 source。
    source_payload = data.get("source")

    if isinstance(source_payload, dict):
        liftable_fields = (
            "description",
            "cuisine",
            "categories",
            "tags",
            "servings",
            "prep_time_minutes",
            "cook_time_minutes",
            "total_time_minutes",
            "ingredients",
            "instructions",
            "import_score",
            "recommendation",
            "possible_duplicate",
            "duplicate_candidates",
            "warnings",
            "review_required",
        )

        for field in liftable_fields:
            if (
                field not in data
                and field in source_payload
            ):
                data[field] = (
                    source_payload[field]
                )

        source_aliases = {
            "description": (
                "summary",
                "introduction",
            ),
            "categories": (
                "category",
            ),
            "ingredients": (
                "materials",
                "ingredient_list",
                "recipe_ingredients",
            ),
            "instructions": (
                "steps",
                "directions",
                "method",
                "recipe_instructions",
            ),
        }

        for target, aliases in (
            source_aliases.items()
        ):
            if target in data:
                continue

            for alias in aliases:
                if alias in source_payload:
                    data[target] = (
                        source_payload[
                            alias
                        ]
                    )
                    break

    _v20_copy_alias(
        data,
        "name",
        (
            "title",
            "recipe_name",
        ),
    )

    _v20_copy_alias(
        data,
        "original_name",
        (
            "original_title",
            "originalName",
            "title",
        ),
    )

    _v20_copy_alias(
        data,
        "description",
        (
            "summary",
            "introduction",
        ),
    )

    _v20_copy_alias(
        data,
        "categories",
        (
            "category",
        ),
    )

    _v20_copy_alias(
        data,
        "ingredients",
        (
            "materials",
            "ingredient_list",
            "recipe_ingredients",
            "recipeIngredients",
        ),
    )

    _v20_copy_alias(
        data,
        "instructions",
        (
            "steps",
            "directions",
            "method",
            "recipe_instructions",
            "recipeInstructions",
        ),
    )

    name = data.get("name")

    if (
        not isinstance(name, str)
        or not name.strip()
    ):
        name = source_title

    data["name"] = name.strip()

    original_name = data.get(
        "original_name"
    )

    if (
        not isinstance(
            original_name,
            str,
        )
        or not original_name.strip()
    ):
        original_name = source_title

    data["original_name"] = (
        original_name.strip()
    )

    cuisine = data.get("cuisine")

    if (
        not isinstance(cuisine, str)
        or not cuisine.strip()
    ):
        data["cuisine"] = "中餐"

    raw_categories = data.get(
        "categories"
    )

    data["categories"] = (
        _v20_normalize_categories(
            raw_categories,
            recipe_name=data["name"],
        )
    )

    raw_tags = data.get(
        "tags",
        [],
    )

    if isinstance(raw_tags, str):
        raw_tags = [
            value.strip()
            for value in re.split(
                r"[,，\n]",
                raw_tags,
            )
            if value.strip()
        ]

    elif not isinstance(
        raw_tags,
        list,
    ):
        raw_tags = []

    data["tags"] = raw_tags[:12]

    import_score = data.get(
        "import_score"
    )

    try:
        import_score = int(
            import_score
        )
    except (
        TypeError,
        ValueError,
    ):
        import_score = 80

    data["import_score"] = min(
        100,
        max(
            0,
            import_score,
        ),
    )

    if not data.get(
        "recommendation"
    ):
        data["recommendation"] = (
            "review"
        )

    if not isinstance(
        data.get(
            "possible_duplicate"
        ),
        bool,
    ):
        data[
            "possible_duplicate"
        ] = False

    if not isinstance(
        data.get(
            "duplicate_candidates"
        ),
        list,
    ):
        data[
            "duplicate_candidates"
        ] = []

    if not isinstance(
        data.get("warnings"),
        list,
    ):
        data["warnings"] = []

    if not isinstance(
        data.get(
            "review_required"
        ),
        bool,
    ):
        data[
            "review_required"
        ] = False

    # 来源信息由 Food Assistant 自己控制，
    # 不信任模型生成的 source 对象。
    data["source"] = dict(
        source_metadata
    )

    # 顶层模型 extra="forbid"，删除 title、steps、
    # materials、difficulty、images 等额外键。
    return {
        key: value
        for key, value in data.items()
        if key
        in V20_NORMALIZED_RECIPE_FIELDS
    }


async def normalize_source_recipe(
    *,
    db: Session,
    job: RecipeImportJob,
    source: RecipeSource,
    recipe: SourceRecipe,
    content: str,
) -> NormalizedRecipe:
    schema = NormalizedRecipe.model_json_schema()

    source_metadata = {
        "source_name": source.name,
        "source_url": build_source_url(
            source,
            recipe,
        ),
        "source_path": recipe.path,
        "source_license": None,
    }

    known_names = existing_normalized_names(
        db,
        job.id,
    )

    user_prompt = (
        "请整理以下一道菜谱。\n\n"
        "来源信息：\n"
        + json.dumps(
            source_metadata,
            ensure_ascii=False,
        )
        + "\n\n已有菜谱名称，用于重复检测：\n"
        + json.dumps(
            known_names,
            ensure_ascii=False,
        )
        + "\n\n必须遵循的输出 JSON Schema：\n"
        + json.dumps(
            schema,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n\n待整理菜谱原文：\n"
        + content
    )

    payload = await get_llm_provider().structured_chat(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_schema=schema,
    )

    prepared = (
        _v20_prepare_normalized_payload(
            repair_normalized_recipe_payload(
                payload
            ),
            source_metadata=source_metadata,
            source_title=recipe.title,
        )
    )

    try:
        return NormalizedRecipe.model_validate(
            prepared
        )

    except ValidationError as first_exc:
        # 首次失败时只再调用一次模型，专门纠正
        # JSON 字段、层级和类型，不重新理解菜谱。
        repair_prompt = (
            "请修复下面的 JSON，使它严格符合给定 "
            "JSON Schema。\n"
            "只修复字段名、字段层级、枚举和数据类型。\n"
            "不得新增原菜谱中不存在的食材或步骤。\n"
            "不得输出解释，只输出一个 JSON 对象。\n\n"
            "来源菜名：\n"
            + recipe.title
            + "\n\n来源元数据：\n"
            + json.dumps(
                source_metadata,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n\n首次校验错误：\n"
            + json.dumps(
                _v20_compact_validation_errors(
                    first_exc
                ),
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            + "\n\n目标 JSON Schema：\n"
            + json.dumps(
                schema,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n\n需要修复的 JSON：\n"
            + json.dumps(
                prepared,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        )

        repaired_payload = (
            await get_llm_provider().structured_chat(
                system_prompt=(
                    "你是严格的 JSON 结构修复器。"
                    "只输出符合 Schema 的 JSON。"
                ),
                user_prompt=repair_prompt,
                response_schema=schema,
            )
        )

        final_payload = (
            _v20_prepare_normalized_payload(
                repair_normalized_recipe_payload(
                    repaired_payload
                ),
                source_metadata=source_metadata,
                source_title=recipe.title,
            )
        )

        return NormalizedRecipe.model_validate(
            final_payload
        )


DUPLICATE_IMPORT_STATES = {
    "importing",
    "imported",
    "orphaned",
}


DUPLICATE_ACTIVE_ITEM_STATUSES = {
    "processing",
    "review",
    "approved_for_import",
    "importing",
    "imported",
}


def imported_source_revision_record(
    db: Session,
    *,
    source_id: int,
    recipe: SourceRecipe,
) -> dict | None:
    import_key = build_import_key(
        source_id=source_id,
        source_recipe_id=recipe.id,
        source_content_sha256=(
            recipe.content_sha256
        ),
    )

    record = get_record_by_key(
        db,
        import_key,
    )

    if (
        record is not None
        and record.get("state")
        in DUPLICATE_IMPORT_STATES
    ):
        return record

    return None


def active_source_revision_item(
    db: Session,
    *,
    recipe: SourceRecipe,
    exclude_item_id: int | None = None,
) -> RecipeImportItem | None:
    statement = (
        select(RecipeImportItem)
        .join(
            RecipeImportJob,
            RecipeImportJob.id
            == RecipeImportItem.job_id,
        )
        .where(
            RecipeImportItem.source_recipe_id
            == recipe.id,
            RecipeImportItem.source_content_sha256
            == recipe.content_sha256,
            RecipeImportItem.status.in_(
                DUPLICATE_ACTIVE_ITEM_STATUSES
            ),
            RecipeImportJob.status
            != "cancelled",
        )
        .order_by(
            RecipeImportItem.id.asc()
        )
        .limit(1)
    )

    if exclude_item_id is not None:
        statement = statement.where(
            RecipeImportItem.id
            != exclude_item_id
        )

    return db.scalar(statement)


def source_revision_duplicate(
    db: Session,
    *,
    source_id: int,
    recipe: SourceRecipe,
    exclude_item_id: int | None = None,
) -> dict | None:
    record = imported_source_revision_record(
        db,
        source_id=source_id,
        recipe=recipe,
    )

    if record is not None:
        return {
            "kind": "mealie_import_record",
            "state": record.get("state"),
            "existing_item_id": (
                record.get("import_item_id")
            ),
            "mealie_slug": (
                record.get("mealie_slug")
            ),
        }

    active_item = active_source_revision_item(
        db,
        recipe=recipe,
        exclude_item_id=exclude_item_id,
    )

    if active_item is not None:
        return {
            "kind": "active_import_item",
            "state": active_item.status,
            "existing_item_id": (
                active_item.id
            ),
            "existing_job_id": (
                active_item.job_id
            ),
        }

    return None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
def create_import_job(
    request: ImportJobCreate,
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(
        RecipeSource,
        request.source_id,
    )

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Recipe source not found",
        )

    statement = select(SourceRecipe).where(
        SourceRecipe.source_id
        == request.source_id,
        SourceRecipe.active.is_(True),
    )

    if request.mode == "ids":
        ids = sorted(set(request.recipe_ids))

        if not ids:
            raise HTTPException(
                status_code=422,
                detail=(
                    "recipe_ids is required "
                    "when mode is ids"
                ),
            )

        statement = statement.where(
            SourceRecipe.id.in_(ids)
        )

    elif request.mode == "filter":
        if not request.q and not request.category:
            raise HTTPException(
                status_code=422,
                detail=(
                    "q or category is required "
                    "when mode is filter"
                ),
            )

        if request.q:
            query_text = request.q.casefold()

            statement = statement.where(
                or_(
                    func.lower(
                        SourceRecipe.title
                    ).contains(query_text),
                    func.lower(
                        SourceRecipe.path
                    ).contains(query_text),
                    func.lower(
                        SourceRecipe.search_text
                    ).contains(query_text),
                )
            )

        if request.category:
            statement = statement.where(
                SourceRecipe.category
                == request.category
            )

    candidate_recipes = list(
        db.scalars(
            statement.order_by(
                SourceRecipe.category.asc(),
                SourceRecipe.title.asc(),
            )
        ).all()
    )

    ensure_mealie_import_schema(db)

    recipes: list[SourceRecipe] = []
    skipped_duplicates: list[dict] = []

    for recipe in candidate_recipes:
        duplicate = source_revision_duplicate(
            db,
            source_id=source.id,
            recipe=recipe,
        )

        if duplicate is not None:
            skipped_duplicates.append(
                {
                    "source_recipe_id": (
                        recipe.id
                    ),
                    "title": recipe.title,
                    "content_sha256": (
                        recipe.content_sha256
                    ),
                    "duplicate": duplicate,
                }
            )
            continue

        recipes.append(recipe)

        if len(recipes) >= request.max_items:
            break

    if not recipes:
        raise HTTPException(
            status_code=422,
            detail=(
                "No active source recipes "
                "matched this selection"
            ),
        )

    selection = request.model_dump()

    job = RecipeImportJob(
        source_id=source.id,
        name=(
            request.name
            or f"{source.name} 导入任务"
        ),
        selection_json=json.dumps(
            selection,
            ensure_ascii=False,
        ),
        status="draft",
        total_items=len(recipes),
    )

    db.add(job)
    db.flush()

    for recipe in recipes:
        db.add(
            RecipeImportItem(
                job_id=job.id,
                source_recipe_id=recipe.id,
                source_content_sha256=(
                    recipe.content_sha256
                ),
                source_commit=(
                    recipe.source_commit
                ),
                status="queued",
            )
        )

    db.commit()
    db.refresh(job)

    return {
        "id": job.id,
        "name": job.name,
        "source_id": job.source_id,
        "status": job.status,
        "total_items": job.total_items,
        "selection": selection,
        "skipped_duplicates": (
            len(skipped_duplicates)
        ),
        "duplicate_details": (
            skipped_duplicates[:100]
        ),
        "message": (
            "Draft import job created. "
            "Already imported or actively reviewed "
            "source revisions were excluded. "
            "Approval is required before AI processing."
        ),
    }


@router.get("")
def list_import_jobs(
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
) -> list[dict]:
    jobs = db.scalars(
        select(RecipeImportJob)
        .order_by(
            RecipeImportJob.id.desc()
        )
        .offset(offset)
        .limit(limit)
    ).all()

    return [
        {
            "id": job.id,
            "name": job.name,
            "source_id": job.source_id,
            "status": job.status,
            "total_items": job.total_items,
            "status_counts": (
                job_status_counts(
                    db,
                    job.id,
                )
            ),
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }
        for job in jobs
    ]


@router.get("/{job_id}")
def read_import_job(
    job_id: int,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    return {
        "id": job.id,
        "name": job.name,
        "source_id": job.source_id,
        "status": job.status,
        "total_items": job.total_items,
        "selection": json.loads(
            job.selection_json
        ),
        "status_counts": (
            job_status_counts(
                db,
                job.id,
            )
        ),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.post("/{job_id}/approve")
def approve_import_job(
    job_id: int,
    request: ImportJobApproval,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    if job.status not in {
        "draft",
        "queued",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Only draft jobs can be approved"
            ),
        )

    if request.confirm_total != job.total_items:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Confirmation count does not "
                    "match job total"
                ),
                "expected": job.total_items,
                "received": (
                    request.confirm_total
                ),
            },
        )

    job.status = "approved"

    db.commit()
    db.refresh(job)

    return {
        "id": job.id,
        "status": job.status,
        "total_items": job.total_items,
        "message": (
            "Job approved. AI processing "
            "still requires an explicit request."
        ),
    }


@router.post("/{job_id}/cancel")
def cancel_import_job(
    job_id: int,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    if job.status == "completed":
        raise HTTPException(
            status_code=409,
            detail=(
                "Completed jobs cannot be cancelled"
            ),
        )

    processing_count = db.scalar(
        select(func.count())
        .select_from(RecipeImportItem)
        .where(
            RecipeImportItem.job_id == job.id,
            RecipeImportItem.status
            == "processing",
        )
    ) or 0

    if processing_count:
        raise HTTPException(
            status_code=409,
            detail=(
                "A recipe is currently processing"
            ),
        )

    items = db.scalars(
        select(RecipeImportItem).where(
            RecipeImportItem.job_id == job.id,
            RecipeImportItem.status.in_(
                [
                    "queued",
                    "failed",
                    "source_updated",
                ]
            ),
        )
    ).all()

    for item in items:
        item.status = "cancelled"

    job.status = "cancelled"

    db.commit()

    return {
        "id": job.id,
        "status": job.status,
        "cancelled_items": len(items),
    }


async def _process_import_item(
    job_id: int,
    db: Session,
    *,
    target_item_id: int | None = None,
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    if job.status not in {
        "approved",
        "processing",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Job must be approved before "
                "AI processing"
            ),
        )

    ensure_mealie_import_schema(db)

    queued_statement = select(RecipeImportItem).where(
        RecipeImportItem.job_id == job.id,
        RecipeImportItem.status == "queued",
    )
    if target_item_id is not None:
        queued_statement = queued_statement.where(
            RecipeImportItem.id == target_item_id
        )
    queued_items = list(
        db.scalars(
            queued_statement.order_by(RecipeImportItem.id.asc())
        ).all()
    )

    if target_item_id is not None and not queued_items:
        target = get_item_or_404(db, job.id, target_item_id)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Only queued items can be processed",
                "item_id": target.id,
                "current_status": target.status,
            },
        )

    item: RecipeImportItem | None = None
    skipped_duplicates: list[dict] = []
    blocked_duplicates: list[dict] = []

    for candidate in queued_items:
        candidate_recipe = db.get(
            SourceRecipe,
            candidate.source_recipe_id,
        )

        # 让后面的既有错误处理负责缺失来源。
        if candidate_recipe is None:
            item = candidate
            break

        imported_record = (
            imported_source_revision_record(
                db,
                source_id=job.source_id,
                recipe=candidate_recipe,
            )
        )

        if imported_record is not None:
            candidate.status = "cancelled"
            candidate.error = json.dumps(
                {
                    "message": (
                        "Duplicate source revision "
                        "was skipped before Ollama"
                    ),
                    "existing_record": (
                        imported_record
                    ),
                },
                ensure_ascii=False,
            )

            skipped_duplicates.append(
                {
                    "item_id": candidate.id,
                    "source_recipe_id": (
                        candidate_recipe.id
                    ),
                    "title": (
                        candidate_recipe.title
                    ),
                    "existing_item_id": (
                        imported_record.get(
                            "import_item_id"
                        )
                    ),
                    "mealie_slug": (
                        imported_record.get(
                            "mealie_slug"
                        )
                    ),
                }
            )
            continue

        active_item = (
            active_source_revision_item(
                db,
                recipe=candidate_recipe,
                exclude_item_id=candidate.id,
            )
        )

        if active_item is not None:
            blocked_duplicates.append(
                {
                    "item_id": candidate.id,
                    "source_recipe_id": (
                        candidate_recipe.id
                    ),
                    "title": (
                        candidate_recipe.title
                    ),
                    "existing_item_id": (
                        active_item.id
                    ),
                    "existing_job_id": (
                        active_item.job_id
                    ),
                    "existing_status": (
                        active_item.status
                    ),
                }
            )
            continue

        item = candidate
        break

    db.flush()

    if item is None:
        counts = update_job_status(
            db,
            job,
        )

        db.commit()

        if blocked_duplicates:
            message = (
                "No eligible queued item is currently "
                "available. Some source revisions are "
                "being processed or reviewed in another "
                "active job."
            )
        else:
            message = (
                "No queued items remain"
            )

        return {
            "job_id": job.id,
            "job_status": job.status,
            "message": message,
            "status_counts": counts,
            "skipped_duplicates": (
                skipped_duplicates
            ),
            "blocked_duplicates": (
                blocked_duplicates
            ),
        }

    recipe = db.get(
        SourceRecipe,
        item.source_recipe_id,
    )

    source = db.get(
        RecipeSource,
        job.source_id,
    )

    if recipe is None or source is None:
        item.status = "failed"
        item.error = (
            "Source or source recipe no longer exists"
        )
        item.attempts += 1

        update_job_status(
            db,
            job,
        )

        db.commit()

        raise HTTPException(
            status_code=409,
            detail=item.error,
        )

    repository_directory = source_repo_dir(
        source.id
    ).resolve()

    recipe_path = (
        repository_directory / recipe.path
    ).resolve()

    if (
        recipe_path != repository_directory
        and repository_directory
        not in recipe_path.parents
    ):
        item.status = "failed"
        item.error = "Invalid indexed source path"
        item.attempts += 1

        update_job_status(
            db,
            job,
        )

        db.commit()

        raise HTTPException(
            status_code=500,
            detail=item.error,
        )

    if not recipe_path.is_file():
        item.status = "source_updated"
        item.error = (
            "Source recipe file is missing"
        )
        item.attempts += 1

        update_job_status(
            db,
            job,
        )

        db.commit()

        raise HTTPException(
            status_code=409,
            detail=item.error,
        )

    content = recipe_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    current_digest = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    if (
        current_digest
        != item.source_content_sha256
    ):
        item.status = "source_updated"
        item.error = (
            "Source recipe changed after "
            "this job was created"
        )
        item.attempts += 1

        update_job_status(
            db,
            job,
        )

        db.commit()

        raise HTTPException(
            status_code=409,
            detail={
                "message": item.error,
                "queued_sha256": (
                    item.source_content_sha256
                ),
                "current_sha256": (
                    current_digest
                ),
            },
        )

    claim = db.execute(
        update(RecipeImportItem)
        .where(
            RecipeImportItem.id == item.id,
            RecipeImportItem.status == "queued",
        )
        .values(
            status="processing",
            attempts=RecipeImportItem.attempts + 1,
            error=None,
        )
    )
    if claim.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This item is already being processed",
        )
    job.status = "processing"

    db.commit()
    db.refresh(item)

    try:
        normalized = await normalize_source_recipe(
            db=db,
            job=job,
            source=source,
            recipe=recipe,
            content=content,
        )

        (
            normalized,
            quality_issues,
        ) = apply_recipe_quality_gate(
            normalized,
            source_text=content,
            source_name=source.name,
            source_url=build_source_url(
                source,
                recipe,
            ),
            source_path=recipe.path,
            source_license=None,
        )

    except (
        OllamaClientError,
        ValidationError,
    ) as exc:
        item.status = "failed"
        item.error = str(exc)[:4000]

        update_job_status(
            db,
            job,
        )

        db.commit()

        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "AI recipe normalization failed"
                ),
                "item_id": item.id,
                "recipe": recipe.title,
                "error": item.error,
                "duplicate_of_item_id": (
                    item.duplicate_of_item_id
                ),
                "duplicate_mealie_slug": (
                    item.duplicate_mealie_slug
                ),
                "duplicate_reason": item.duplicate_reason,
            },
        ) from exc

    except Exception as exc:
        item.status = "failed"
        item.error = (
            f"{exc.__class__.__name__}: "
            f"{str(exc)}"
        )[:4000]

        update_job_status(
            db,
            job,
        )

        db.commit()

        raise HTTPException(
            status_code=500,
            detail={
                "message": (
                    "Unexpected import processing error"
                ),
                "item_id": item.id,
                "recipe": recipe.title,
                "error": item.error,
            },
        ) from exc

    item.normalized_json = json.dumps(
        normalized.model_dump(
            mode="json",
        ),
        ensure_ascii=False,
    )

    item.status = "review"
    item.error = None

    # Flush item state before recounting statuses.
    # Without this, the job may remain stuck at
    # "processing".
    db.flush()

    counts = update_job_status(
        db,
        job,
    )

    db.commit()

    return {
        "job_id": job.id,
        "job_status": job.status,
        "item": {
            "id": item.id,
            "source_recipe_id": recipe.id,
            "source_title": recipe.title,
            "status": item.status,
            "attempts": item.attempts,
            "model": OLLAMA_MODEL,
            "normalized": normalized.model_dump(
                mode="json",
            ),
            "quality_issues": quality_issues,
        },
        "status_counts": counts,
        "skipped_duplicates": (
            skipped_duplicates
        ),
        "blocked_duplicates": (
            blocked_duplicates
        ),
        "message": (
            "One recipe was normalized and "
            "placed into human review. "
            "Nothing was written to Mealie."
        ),
    }


@router.post("/{job_id}/process-next")
async def process_next_import_item(
    job_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return await _process_import_item(job_id, db)


@router.post("/{job_id}/items/{item_id}/process")
async def process_specific_import_item(
    job_id: int,
    item_id: int,
    request: ProcessImportItemRequest,
    db: Session = Depends(get_db),
) -> dict:
    if request.confirm_item_id != item_id:
        raise HTTPException(
            status_code=409,
            detail="Item confirmation does not match",
        )
    if request.auto_import:
        raise HTTPException(
            status_code=422,
            detail="Targeted processing cannot auto-import",
        )
    try:
        return await _process_import_item(
            job_id,
            db,
            target_item_id=item_id,
        )
    except HTTPException as exc:
        if is_ollama_infrastructure_error(exc):
            item = get_item_or_404(db, job_id, item_id)
            if item.status == "failed":
                item.status = "queued"
                item.error = None
                job = get_job_or_404(db, job_id)
                update_job_status(db, job)
                db.commit()
        raise
    finally:
        if request.unload_model_after:
            try:
                await unload_ollama_model()
            except Exception:
                pass


@router.post("/{job_id}/process-batch")
async def process_import_batch(
    job_id: int,
    request: ImportBatchRequest,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    if job.status not in {
        "approved",
        "processing",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Job must be approved before "
                    "batch AI processing"
                ),
                "current_status": job.status,
            },
        )

    existing_processing = db.scalar(
        select(func.count())
        .select_from(RecipeImportItem)
        .where(
            RecipeImportItem.job_id == job.id,
            RecipeImportItem.status
            == "processing",
        )
    ) or 0

    if existing_processing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Another item in this job is "
                "currently processing"
            ),
        )

    processed_items: list[dict] = []
    skipped_duplicates: list[dict] = []
    blocked_duplicates: list[dict] = []

    stop_reason: str | None = None
    stopped_error: dict | None = None
    last_message: str | None = None

    for _ in range(request.count):
        try:
            result = (
                await process_next_import_item(
                    job_id,
                    db,
                )
            )

        except HTTPException as exc:
            # process-next 会在可预期失败时保存 failed
            # 状态；这里停止整批，但保留此前成功结果。
            db.rollback()

            stop_reason = "item_failed"
            stopped_error = {
                "status_code": exc.status_code,
                "detail": exc.detail,
            }
            break

        last_message = result.get(
            "message"
        )

        skipped_duplicates.extend(
            result.get(
                "skipped_duplicates",
                [],
            )
        )

        blocked_duplicates.extend(
            result.get(
                "blocked_duplicates",
                [],
            )
        )

        item_result = result.get("item")

        if not isinstance(
            item_result,
            dict,
        ):
            stop_reason = (
                "blocked_duplicate"
                if result.get(
                    "blocked_duplicates"
                )
                else "no_queued"
            )
            break

        processed_items.append(
            {
                "item_id": item_result.get(
                    "id"
                ),
                "source_recipe_id": (
                    item_result.get(
                        "source_recipe_id"
                    )
                ),
                "source_title": (
                    item_result.get(
                        "source_title"
                    )
                ),
                "status": item_result.get(
                    "status"
                ),
                "attempts": item_result.get(
                    "attempts"
                ),
                "quality_issues": (
                    item_result.get(
                        "quality_issues",
                        [],
                    )
                ),
            }
        )

    db.expire_all()

    job = get_job_or_404(
        db,
        job_id,
    )

    counts = job_status_counts(
        db,
        job.id,
    )

    if stop_reason == "item_failed":
        message = (
            "Batch processing stopped after "
            "one recipe failed. Previously "
            "processed recipes remain in review."
        )

    elif stop_reason == "blocked_duplicate":
        message = (
            "Batch processing stopped because "
            "the next source revision is active "
            "in another import job."
        )

    elif stop_reason == "no_queued":
        message = (
            "Batch processing stopped because "
            "no eligible queued items remain."
        )

    elif len(processed_items) >= request.count:
        message = (
            "Requested batch completed. "
            "All processed recipes were placed "
            "into human review."
        )

    else:
        message = (
            last_message
            or "Batch processing finished."
        )

    return {
        "job_id": job.id,
        "job_status": job.status,
        "requested_count": request.count,
        "processed_count": len(
            processed_items
        ),
        "processed_items": processed_items,
        "stopped": stop_reason is not None,
        "stop_reason": stop_reason,
        "error": stopped_error,
        "skipped_duplicates": (
            skipped_duplicates
        ),
        "blocked_duplicates": (
            blocked_duplicates
        ),
        "status_counts": counts,
        "message": message,
        "safety": {
            "automatic_approval": False,
            "automatic_mealie_import": False,
        },
    }


@router.post(
    "/{job_id}/items/{item_id}/retry"
)
def retry_import_item(
    job_id: int,
    item_id: int,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    if job.status in {
        "cancelled",
        "completed",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "This job cannot be retried"
            ),
        )

    if item.status not in {
        "failed",
        "source_updated",
        "processing",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Only failed, source_updated, "
                "or stale processing items "
                "can be retried"
            ),
        )

    item.status = "queued"
    item.error = None
    job.status = "approved"

    db.commit()

    return {
        "job_id": job.id,
        "item_id": item.id,
        "item_status": item.status,
        "job_status": job.status,
    }


def append_manual_review_note(
    recipe: NormalizedRecipe,
    note: str | None,
) -> None:
    if note is None:
        return

    cleaned = note.strip()

    if not cleaned:
        return

    warning = f"[人工审核] {cleaned}"

    if warning not in recipe.warnings:
        recipe.warnings.append(warning)


@router.patch(
    "/{job_id}/items/{item_id}"
)
def update_review_item(
    job_id: int,
    item_id: int,
    request: ImportItemUpdate,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    if job.status in {
        "cancelled",
        "completed",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "This job can no longer be edited"
            ),
        )

    if item.status not in {
        "review",
        "approved_for_import",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Only review or approved items "
                "can be edited"
            ),
        )

    recipe = db.get(
        SourceRecipe,
        item.source_recipe_id,
    )

    source = db.get(
        RecipeSource,
        job.source_id,
    )

    if recipe is None or source is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Source or source recipe "
                "no longer exists"
            ),
        )

    normalized = request.normalized

    # 来源字段由系统控制，人工修改不能覆盖。
    normalized.source.source_name = (
        source.name
    )
    normalized.source.source_url = (
        build_source_url(
            source,
            recipe,
        )
    )
    normalized.source.source_path = (
        recipe.path
    )

    append_manual_review_note(
        normalized,
        request.review_note,
    )

    item.normalized_json = json.dumps(
        normalized.model_dump(
            mode="json",
        ),
        ensure_ascii=False,
    )

    item.status = "review"
    item.error = None

    db.flush()

    counts = update_job_status(
        db,
        job,
    )

    db.commit()

    return {
        "job_id": job.id,
        "job_status": job.status,
        "item_id": item.id,
        "item_status": item.status,
        "normalized": normalized.model_dump(
            mode="json",
        ),
        "status_counts": counts,
        "message": (
            "Human-edited result saved. "
            "Run revalidate before approval."
        ),
    }


@router.post(
    "/{job_id}/items/{item_id}/approve-for-import"
)
def approve_item_for_import(
    job_id: int,
    item_id: int,
    request: ImportItemApproval,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    if item.status != "review":
        raise HTTPException(
            status_code=409,
            detail=(
                "Only items in review can "
                "be approved"
            ),
        )

    if not item.normalized_json:
        raise HTTPException(
            status_code=409,
            detail=(
                "This item has no normalized result"
            ),
        )

    try:
        normalized = (
            NormalizedRecipe.model_validate_json(
                item.normalized_json
            )
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Stored normalized result "
                    "is invalid"
                ),
                "errors": exc.errors(
                    include_url=False
                ),
            },
        ) from exc

    if request.confirm_name != normalized.name:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Recipe-name confirmation "
                    "does not match"
                ),
                "expected": normalized.name,
                "received": request.confirm_name,
            },
        )

    warning_groups = (
        classify_import_warnings(
            normalized
        )
    )

    blocking_warnings = (
        warning_groups["blocking"]
    )

    confirmation_warnings = (
        warning_groups["confirmation"]
    )

    if blocking_warnings:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Recipe contains blocking "
                    "quality problems"
                ),
                "blocking_warnings": (
                    blocking_warnings
                ),
                "required": (
                    "Fix the blocking problems "
                    "and run revalidate again"
                ),
            },
        )

    needs_acknowledgement = bool(
        confirmation_warnings
    )

    if (
        needs_acknowledgement
        and not request.acknowledge_warnings
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Recipe still requires "
                    "human confirmation"
                ),
                "warnings": (
                    confirmation_warnings
                ),
                "required": (
                    "Set acknowledge_warnings=true "
                    "after human review"
                ),
            },
        )

    if (
        needs_acknowledgement
        and not request.review_note
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "review_note is required when "
                "confirming quality warnings"
            ),
        )

    append_manual_review_note(
        normalized,
        request.review_note,
    )

    item.normalized_json = json.dumps(
        normalized.model_dump(
            mode="json",
        ),
        ensure_ascii=False,
    )

    item.status = "approved_for_import"
    item.error = None

    db.flush()

    counts = update_job_status(
        db,
        job,
    )

    db.commit()

    return {
        "job_id": job.id,
        "job_status": job.status,
        "item_id": item.id,
        "item_status": item.status,
        "recipe_name": normalized.name,
        "acknowledged_warnings": (
            needs_acknowledgement
        ),
        "status_counts": counts,
        "message": (
            "Recipe approved for import. "
            "Nothing has been written to Mealie yet."
        ),
    }


@router.post(
    "/{job_id}/items/{item_id}/reject"
)
def reject_review_item(
    job_id: int,
    item_id: int,
    request: ImportItemRejection,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    if item.status not in {
        "review",
        "approved_for_import",
        "failed",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "This item cannot be rejected "
                "from its current state"
            ),
        )

    item.status = "rejected"
    item.error = request.reason.strip()

    db.flush()

    counts = update_job_status(
        db,
        job,
    )

    db.commit()

    return {
        "job_id": job.id,
        "job_status": job.status,
        "item_id": item.id,
        "item_status": item.status,
        "reason": item.error,
        "status_counts": counts,
    }


@router.post(
    "/{job_id}/items/{item_id}/restore-rejected"
)
def restore_rejected_item(
    job_id: int,
    item_id: int,
    request: RestoreRejectedRequest,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(db, job_id)
    item = get_item_or_404(db, job_id, item_id)
    if request.confirm_item_id != item_id:
        raise HTTPException(
            status_code=409,
            detail="Item confirmation does not match",
        )
    if item.status != "rejected":
        raise HTTPException(
            status_code=409,
            detail="Only rejected items can be restored",
        )
    if not item.normalized_json:
        raise HTTPException(
            status_code=409,
            detail="This item has no normalized result",
        )
    try:
        normalized = NormalizedRecipe.model_validate_json(
            item.normalized_json
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail="Stored normalized result is invalid",
        ) from exc

    audit_prefix = "[系统审计] Restored from rejected at "
    if not any(
        str(warning).startswith(audit_prefix)
        for warning in normalized.warnings
    ):
        previous_reason = (item.error or "Not recorded").strip()
        normalized.warnings.append(
            audit_prefix
            + datetime.now(UTC).isoformat()
            + ". Previous rejection reason: "
            + previous_reason
        )

    item.normalized_json = json.dumps(
        normalized.model_dump(mode="json"),
        ensure_ascii=False,
    )
    item.status = "review"
    item.error = None
    db.flush()
    counts = update_job_status(db, job)
    db.commit()
    return {
        "job_id": job.id,
        "job_status": job.status,
        "item_id": item.id,
        "item_status": item.status,
        "normalized": normalized.model_dump(mode="json"),
        "status_counts": counts,
    }


def build_pinned_source_url(
    source: RecipeSource,
    recipe: SourceRecipe,
    item: RecipeImportItem,
) -> str:
    repository_url = (
        source.repo_url.removesuffix(
            ".git"
        )
    )

    revision = (
        item.source_commit
        or source.branch
        or "master"
    )

    return (
        f"{repository_url}/blob/"
        f"{quote(revision, safe='')}/"
        f"{quote(recipe.path, safe='/')}"
    )


def load_source_content_for_import(
    source: RecipeSource,
    recipe: SourceRecipe,
    item: RecipeImportItem,
) -> str:
    repository_directory = (
        source_repo_dir(
            source.id
        ).resolve()
    )

    recipe_path = (
        repository_directory
        / recipe.path
    ).resolve()

    if (
        recipe_path
        != repository_directory
        and repository_directory
        not in recipe_path.parents
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "Invalid indexed source path"
            ),
        )

    if not recipe_path.is_file():
        raise HTTPException(
            status_code=409,
            detail=(
                "Source recipe file is missing"
            ),
        )

    content = recipe_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    current_digest = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    if (
        current_digest
        != item.source_content_sha256
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Source recipe changed after "
                    "this import item was created"
                ),
                "queued_sha256": (
                    item.source_content_sha256
                ),
                "current_sha256": (
                    current_digest
                ),
            },
        )

    return content


@router.get(
    "/{job_id}/items/{item_id}/mealie-preview"
)
def preview_mealie_import(
    job_id: int,
    item_id: int,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    if item.status not in {
        "review",
        "approved_for_import",
        "imported",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Item must be reviewed before "
                "creating a Mealie preview"
            ),
        )

    if not item.normalized_json:
        raise HTTPException(
            status_code=409,
            detail=(
                "This item has no normalized result"
            ),
        )

    try:
        normalized = (
            NormalizedRecipe.model_validate_json(
                item.normalized_json
            )
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Stored normalized result "
                    "is invalid"
                ),
                "errors": exc.errors(
                    include_url=False
                ),
            },
        ) from exc

    recipe = db.get(
        SourceRecipe,
        item.source_recipe_id,
    )

    source = db.get(
        RecipeSource,
        job.source_id,
    )

    if recipe is None or source is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Source or source recipe "
                "no longer exists"
            ),
        )

    load_source_content_for_import(
        source,
        recipe,
        item,
    )

    source_url = build_pinned_source_url(
        source,
        recipe,
        item,
    )

    import_key = build_import_key(
        source_id=source.id,
        source_recipe_id=recipe.id,
        source_content_sha256=(
            item.source_content_sha256
        ),
    )

    ensure_mealie_import_schema(db)

    return {
        "job_id": job.id,
        "job_status": job.status,
        "item_id": item.id,
        "item_status": item.status,
        "existing_import_record": (
            get_record_by_item(
                db,
                item.id,
            )
        ),
        "preview": build_mealie_preview(
            normalized,
            import_key=import_key,
            source_url=source_url,
            source_commit=(
                item.source_commit
            ),
            source_content_sha256=(
                item.source_content_sha256
            ),
        ),
        "message": (
            "Preview only. Nothing was "
            "written to Mealie."
        ),
    }


@router.post(
    "/{job_id}/items/{item_id}/import-to-mealie"
)
async def import_item_to_mealie(
    job_id: int,
    item_id: int,
    request: MealieImportConfirmation,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    ensure_mealie_import_schema(db)

    existing_record = get_record_by_item(
        db,
        item.id,
    )

    if (
        item.status == "imported"
        and existing_record is not None
        and existing_record.get("state")
        == "imported"
    ):
        return {
            "job_id": job.id,
            "item_id": item.id,
            "item_status": item.status,
            "idempotent": True,
            "mealie_slug": (
                existing_record.get(
                    "mealie_slug"
                )
            ),
            "mealie_recipe_id": (
                existing_record.get(
                    "mealie_recipe_id"
                )
            ),
            "message": (
                "This recipe was already "
                "imported."
            ),
        }

    if item.status != "approved_for_import":
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Only approved_for_import "
                    "items can be written to Mealie"
                ),
                "current_status": item.status,
            },
        )

    if request.confirm_item_id != item.id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Item confirmation does "
                    "not match"
                ),
                "expected": item.id,
                "received": (
                    request.confirm_item_id
                ),
            },
        )

    if not item.normalized_json:
        raise HTTPException(
            status_code=409,
            detail=(
                "This item has no normalized result"
            ),
        )

    try:
        normalized = (
            NormalizedRecipe.model_validate_json(
                item.normalized_json
            )
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Stored normalized result "
                    "is invalid"
                ),
                "errors": exc.errors(
                    include_url=False
                ),
            },
        ) from exc

    if request.confirm_name != normalized.name:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Recipe-name confirmation "
                    "does not match"
                ),
                "expected": normalized.name,
                "received": (
                    request.confirm_name
                ),
            },
        )

    recipe = db.get(
        SourceRecipe,
        item.source_recipe_id,
    )

    source = db.get(
        RecipeSource,
        job.source_id,
    )

    if recipe is None or source is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Source or source recipe "
                "no longer exists"
            ),
        )

    load_source_content_for_import(
        source,
        recipe,
        item,
    )

    source_url = build_pinned_source_url(
        source,
        recipe,
        item,
    )

    import_key = build_import_key(
        source_id=source.id,
        source_recipe_id=recipe.id,
        source_content_sha256=(
            item.source_content_sha256
        ),
    )

    duplicate_record = get_record_by_key(
        db,
        import_key,
    )

    if (
        duplicate_record is not None
        and duplicate_record.get(
            "import_item_id"
        ) != item.id
        and duplicate_record.get("state")
        in {
            "importing",
            "imported",
            "orphaned",
        }
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "The same source revision "
                    "already has an import record"
                ),
                "existing_record": (
                    duplicate_record
                ),
            },
        )

    claim = db.execute(
        update(RecipeImportItem)
        .where(
            RecipeImportItem.id == item.id,
            RecipeImportItem.status
            == "approved_for_import",
        )
        .values(
            status="importing",
            error=None,
        )
    )

    if claim.rowcount != 1:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                "The item could not be claimed "
                "for import"
            ),
        )

    start_import_record(
        db,
        import_item_id=item.id,
        source_id=source.id,
        source_recipe_id=recipe.id,
        source_content_sha256=(
            item.source_content_sha256
        ),
        import_key=import_key,
    )

    db.commit()
    db.refresh(item)

    writer: MealieWriter | None = None
    created_slug: str | None = None
    rollback_error: str | None = None

    try:
        writer = MealieWriter()

        resolution = (
            await resolve_recipe_entities(
                writer,
                normalized,
                create_missing=True,
            )
        )

        if resolution[
            "summary"
        ]["missing"]:
            raise MealieImportError(
                "Some native Mealie entities "
                "could not be resolved: "
                + json.dumps(
                    resolution[
                        "summary"
                    ]["missing"],
                    ensure_ascii=False,
                )
            )

        native_ingredients = (
            build_mealie_native_ingredients(
                normalized,
                foods=resolution["foods"],
                units=resolution["units"],
            )
        )

        created_slug = (
            await writer.create_blank_recipe(
                normalized.name
            )
        )

        record_created_slug(
            db,
            import_item_id=item.id,
            mealie_slug=created_slug,
        )

        db.commit()

        blank_recipe = await writer.get_recipe(
            created_slug
        )

        payload = (
            build_mealie_patch_payload(
                normalized,
                blank_recipe=blank_recipe,
                import_key=import_key,
                source_url=source_url,
                source_commit=(
                    item.source_commit
                ),
                source_content_sha256=(
                    item.source_content_sha256
                ),
                native_categories=(
                    resolution["categories"]
                ),
                native_tags=(
                    resolution["tags"]
                ),
                native_ingredients=(
                    native_ingredients
                ),
            )
        )

        await writer.patch_recipe(
            created_slug,
            payload,
        )

        verified_recipe = (
            await writer.get_recipe(
                created_slug
            )
        )

        verify_mealie_recipe(
            normalized,
            mealie_recipe=verified_recipe,
            import_key=import_key,
        )

        native_errors = (
            verify_native_structure(
                normalized,
                verified_recipe,
                resolved_categories=(
                    resolution["categories"]
                ),
                resolved_tags=resolution["tags"],
            )
        )

        if native_errors:
            raise MealieImportError(
                "Native Mealie structure "
                "verification failed: "
                + "; ".join(native_errors)
            )

        mealie_recipe_id = str(
            verified_recipe.get("id")
            or ""
        )

        if not mealie_recipe_id:
            raise MealieImportError(
                "Verified Mealie recipe "
                "has no id"
            )

        item.status = "imported"
        item.error = None

        mark_record_imported(
            db,
            import_item_id=item.id,
            mealie_slug=created_slug,
            mealie_recipe_id=(
                mealie_recipe_id
            ),
        )

        db.flush()

        counts = update_job_status(
            db,
            job,
        )

        db.commit()

        return {
            "job_id": job.id,
            "job_status": job.status,
            "item_id": item.id,
            "item_status": item.status,
            "idempotent": False,
            "mealie_slug": created_slug,
            "mealie_recipe_id": (
                mealie_recipe_id
            ),
            "mealie_url": (
                f"/g/home/r/"
                f"{created_slug}"
            ),
            "native_resolution_summary": (
                resolution["summary"]
            ),
            "verified": {
                "native_structure": True,
                "name": (
                    verified_recipe.get(
                        "name"
                    )
                ),
                "ingredient_count": len(
                    verified_recipe.get(
                        "recipeIngredient",
                        [],
                    )
                ),
                "instruction_count": len(
                    verified_recipe.get(
                        "recipeInstructions",
                        [],
                    )
                ),
                "orgURL": (
                    verified_recipe.get(
                        "orgURL"
                    )
                ),
                "schema_version": (
                    verified_recipe.get(
                        "extras",
                        {},
                    ).get(
                        "foodAssistantSchemaVersion"
                    )
                ),
                "categories": [
                    value.get("name")
                    for value
                    in verified_recipe.get(
                        "recipeCategory",
                        [],
                    )
                ],
                "tags": [
                    value.get("name")
                    for value
                    in verified_recipe.get(
                        "tags",
                        [],
                    )
                ],
            },
            "status_counts": counts,
            "message": (
                "Recipe was imported to "
                "Mealie and verified by GET."
            ),
        }

    except Exception as exc:
        error = (
            f"{exc.__class__.__name__}: "
            f"{str(exc)}"
        )[:4000]

        rollback_succeeded = (
            created_slug is None
        )

        if (
            created_slug is not None
            and writer is not None
        ):
            try:
                await writer.delete_recipe(
                    created_slug
                )

                rollback_succeeded = True

            except Exception as cleanup_exc:
                rollback_error = (
                    f"{cleanup_exc.__class__.__name__}: "
                    f"{str(cleanup_exc)}"
                )[:2000]

        if rollback_succeeded:
            item.status = (
                "approved_for_import"
            )

            item.error = (
                "Mealie import failed; "
                "created recipe was rolled back. "
                + error
            )

            mark_record_failed(
                db,
                import_item_id=item.id,
                state="rolled_back",
                error=item.error,
            )

        else:
            item.status = "import_failed"

            item.error = (
                "Mealie import failed and "
                "automatic rollback failed. "
                f"slug={created_slug}; "
                f"import_error={error}; "
                f"rollback_error={rollback_error}"
            )[:4000]

            mark_record_failed(
                db,
                import_item_id=item.id,
                state="orphaned",
                error=item.error,
            )

        db.flush()

        counts = update_job_status(
            db,
            job,
        )

        db.commit()

        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Mealie import failed"
                ),
                "item_id": item.id,
                "item_status": item.status,
                "created_slug": (
                    created_slug
                ),
                "rollback_succeeded": (
                    rollback_succeeded
                ),
                "error": error,
                "rollback_error": (
                    rollback_error
                ),
                "status_counts": counts,
            },
        ) from exc


def build_auto_import_preview(
    db: Session,
    job: RecipeImportJob,
    *,
    limit: int | None = None,
) -> dict:
    statement = (
        select(RecipeImportItem)
        .where(
            RecipeImportItem.job_id
            == job.id,
            RecipeImportItem.status.in_(
                [
                    "review",
                    "approved_for_import",
                ]
            ),
        )
        .order_by(
            RecipeImportItem.id.asc()
        )
    )

    if limit is not None:
        statement = statement.limit(limit)

    items = list(
        db.scalars(statement).all()
    )

    eligible: list[dict] = []
    requires_attention: list[dict] = []

    for item in items:
        source_recipe = db.get(
            SourceRecipe,
            item.source_recipe_id,
        )

        source_title = (
            source_recipe.title
            if source_recipe is not None
            else f"Item {item.id}"
        )

        if not item.normalized_json:
            requires_attention.append(
                {
                    "item_id": item.id,
                    "name": source_title,
                    "status": item.status,
                    "reasons": [
                        "没有标准化结果"
                    ],
                }
            )
            continue

        try:
            normalized = (
                NormalizedRecipe
                .model_validate_json(
                    item.normalized_json
                )
            )
        except ValidationError as exc:
            requires_attention.append(
                {
                    "item_id": item.id,
                    "name": source_title,
                    "status": item.status,
                    "reasons": [
                        "标准化结果无法通过模型校验"
                    ],
                    "validation_errors": (
                        exc.errors(
                            include_url=False
                        )
                    ),
                }
            )
            continue

        groups = classify_import_warnings(
            normalized
        )

        reasons = (
            groups["blocking"]
            + groups["confirmation"]
        )

        if reasons:
            requires_attention.append(
                {
                    "item_id": item.id,
                    "name": normalized.name,
                    "status": item.status,
                    "reasons": reasons,
                    "ignored_warnings": (
                        groups["ignored"]
                    ),
                }
            )
            continue

        eligible.append(
            {
                "item_id": item.id,
                "name": normalized.name,
                "status": item.status,
                "will_auto_approve": (
                    item.status == "review"
                ),
                "will_import": True,
                "ignored_warnings": (
                    groups["ignored"]
                ),
            }
        )

    return {
        "job_id": job.id,
        "job_name": job.name,
        "job_status": job.status,
        "eligible_count": len(eligible),
        "requires_attention_count": len(
            requires_attention
        ),
        "eligible": eligible,
        "requires_attention": (
            requires_attention
        ),
        "status_counts": job_status_counts(
            db,
            job.id,
        ),
        "policy": {
            "blocking_prefixes": [
                "[必须修正]",
                "[需要确认]",
                "[系统校验]",
            ],
            "ignored": [
                "正常时间范围计时器",
                "水和食用油的语义补全提示",
            ],
            "invalid_timer_ranges_block": True,
        },
    }


@router.get(
    "/{job_id}/auto-import-preview"
)
def preview_auto_import(
    job_id: int,
    limit: int = Query(
        default=500,
        ge=1,
        le=1000,
    ),
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    preview = build_auto_import_preview(
        db,
        job,
        limit=limit,
    )

    preview["message"] = (
        "Preview only. Nothing was "
        "approved or written to Mealie."
    )

    return preview


@router.post(
    "/{job_id}/auto-import"
)
async def auto_import_eligible_items(
    job_id: int,
    request: AutoImportRequest,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    if request.confirm_job_id != job.id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Job confirmation does not match"
                ),
                "expected": job.id,
                "received": (
                    request.confirm_job_id
                ),
            },
        )

    if job.status == "cancelled":
        raise HTTPException(
            status_code=409,
            detail=(
                "Cancelled jobs cannot be "
                "automatically imported"
            ),
        )

    preview = build_auto_import_preview(
        db,
        job,
    )

    selected = preview["eligible"][
        :request.max_items
    ]

    imported: list[dict] = []
    failed: list[dict] = []
    auto_approved = 0
    consecutive_failures = 0
    stopped_early = False

    for candidate in selected:
        item_id = int(
            candidate["item_id"]
        )

        try:
            db.expire_all()

            item = get_item_or_404(
                db,
                job.id,
                item_id,
            )

            if not item.normalized_json:
                raise RuntimeError(
                    "Normalized result disappeared"
                )

            normalized = (
                NormalizedRecipe
                .model_validate_json(
                    item.normalized_json
                )
            )

            groups = classify_import_warnings(
                normalized
            )

            if (
                groups["blocking"]
                or groups["confirmation"]
            ):
                raise RuntimeError(
                    "Recipe became ineligible "
                    "before import"
                )

            was_review = (
                item.status == "review"
            )

            if was_review:
                approve_item_for_import(
                    job.id,
                    item.id,
                    ImportItemApproval(
                        confirm_name=(
                            normalized.name
                        ),
                        acknowledge_warnings=False,
                        review_note=None,
                    ),
                    db,
                )

                auto_approved += 1

            db.expire_all()

            result = await import_item_to_mealie(
                job.id,
                item.id,
                MealieImportConfirmation(
                    confirm_item_id=item.id,
                    confirm_name=(
                        normalized.name
                    ),
                ),
                db,
            )

            imported.append(
                {
                    "item_id": item.id,
                    "name": normalized.name,
                    "auto_approved": was_review,
                    "idempotent": result.get(
                        "idempotent",
                        False,
                    ),
                    "mealie_slug": result.get(
                        "mealie_slug"
                    ),
                    "mealie_recipe_id": (
                        result.get(
                            "mealie_recipe_id"
                        )
                    ),
                }
            )

            consecutive_failures = 0

        except HTTPException as exc:
            db.rollback()

            failed.append(
                {
                    "item_id": item_id,
                    "name": candidate.get(
                        "name"
                    ),
                    "status_code": (
                        exc.status_code
                    ),
                    "error": exc.detail,
                }
            )

            consecutive_failures += 1

        except Exception as exc:
            db.rollback()

            failed.append(
                {
                    "item_id": item_id,
                    "name": candidate.get(
                        "name"
                    ),
                    "error": (
                        f"{exc.__class__.__name__}: "
                        f"{str(exc)}"
                    ),
                }
            )

            consecutive_failures += 1

        if (
            consecutive_failures
            >= request
            .stop_after_consecutive_failures
        ):
            stopped_early = True
            break

    db.expire_all()

    current_job = get_job_or_404(
        db,
        job.id,
    )

    counts = job_status_counts(
        db,
        current_job.id,
    )

    return {
        "job_id": current_job.id,
        "job_name": current_job.name,
        "job_status": current_job.status,
        "requested_max_items": (
            request.max_items
        ),
        "selected_count": len(selected),
        "auto_approved_count": (
            auto_approved
        ),
        "imported_count": len(imported),
        "failed_count": len(failed),
        "remaining_eligible_count": max(
            0,
            preview["eligible_count"]
            - len(selected),
        ),
        "stopped_early": stopped_early,
        "stop_after_consecutive_failures": (
            request
            .stop_after_consecutive_failures
        ),
        "imported": imported,
        "failed": failed,
        "status_counts": counts,
        "message": (
            "Eligible recipes were automatically "
            "approved and imported one by one."
            if imported
            else
            "No eligible recipe was imported."
        ),
    }


OLLAMA_INFRASTRUCTURE_ERROR_MARKERS = (
    "cudamalloc failed",
    "cuda out of memory",
    "out of memory",
    "unable to allocate cuda",
    "unable to allocate cuda0",
    "llama-server process has terminated",
    "error loading model",
    "failed to connect",
    "couldn't connect",
    "connection refused",
    "connect timeout",
    "connection timeout",
    "timed out",
    "no route to host",
    "ollama returned http 500",
    "ollama is unavailable",
    "remoteprotocolerror",
    "server disconnected",
    "peer closed connection",
)


def flatten_error_detail(
    value: object,
) -> str:
    if isinstance(value, dict):
        return " ".join(
            flatten_error_detail(item)
            for item in value.values()
        )

    if isinstance(value, list):
        return " ".join(
            flatten_error_detail(item)
            for item in value
        )

    return str(value)


def is_ollama_infrastructure_error(
    value: object,
) -> bool:
    if is_infrastructure_error(value):
        return True

    text = flatten_error_detail(
        value
    ).casefold()

    return any(
        marker in text
        for marker
        in OLLAMA_INFRASTRUCTURE_ERROR_MARKERS
    )


def requeue_ollama_infrastructure_failures(
    db: Session,
    job_id: int,
) -> list[dict]:
    items = list(
        db.scalars(
            select(RecipeImportItem)
            .where(
                RecipeImportItem.job_id
                == job_id,
                RecipeImportItem.status
                == "failed",
            )
            .order_by(
                RecipeImportItem.id.asc()
            )
        ).all()
    )

    requeued: list[dict] = []

    for item in items:
        error = item.error or ""

        if not is_ollama_infrastructure_error(
            error
        ):
            continue

        source_recipe = db.get(
            SourceRecipe,
            item.source_recipe_id,
        )

        requeued.append(
            {
                "item_id": item.id,
                "name": (
                    source_recipe.title
                    if source_recipe
                    else f"Item {item.id}"
                ),
                "previous_error": error[:1000],
            }
        )

        item.status = "queued"
        item.error = None

    return requeued


async def unload_ollama_model() -> dict:
    try:
        return await get_llm_provider().unload()

    except Exception as exc:
        return {
            "succeeded": False,
            "error": (
                f"{exc.__class__.__name__}: "
                f"{str(exc)}"
            )[:1000],
        }


@router.post(
    "/{job_id}/process-and-auto-import"
)
async def process_and_auto_import(
    job_id: int,
    request: ProcessAndAutoImportRequest,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    # 将此前因 Ollama 断线、OOM 等产生的 failed
    # 自动恢复成 queued。
    requeued_infrastructure_items = (
        requeue_ollama_infrastructure_failures(
            db,
            job.id,
        )
    )

    if requeued_infrastructure_items:
        update_job_status(
            db,
            job,
        )

        db.commit()
        db.expire_all()

        job = get_job_or_404(
            db,
            job_id,
        )

    if job.status not in {
        "approved",
        "processing",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Job must be approved before "
                    "combined processing"
                ),
                "job_status": job.status,
                "queued": job_status_counts(
                    db,
                    job.id,
                ).get(
                    "queued",
                    0,
                ),
            },
        )

    attempted_count = 0
    normalized_count = 0

    imported: list[dict] = []
    requires_review: list[dict] = []
    processing_failed: list[dict] = []
    import_failed: list[dict] = []

    skipped_duplicates: list[dict] = []
    blocked_duplicates: list[dict] = []

    infrastructure_error: dict | None = None
    stop_reason: str | None = None

    for _ in range(request.count):
        attempted_count += 1

        try:
            result = await process_next_import_item(
                job.id,
                db,
            )

        except HTTPException as exc:
            if is_ollama_infrastructure_error(
                exc.detail
            ):
                db.rollback()

                restored = (
                    requeue_ollama_infrastructure_failures(
                        db,
                        job.id,
                    )
                )

                update_job_status(
                    db,
                    job,
                )

                db.commit()

                infrastructure_error = {
                    "status_code": (
                        exc.status_code
                    ),
                    "detail": exc.detail,
                    "requeued_items": restored,
                }

                stop_reason = (
                    "ollama_infrastructure_error"
                )
                break

            db.rollback()

            processing_failed.append(
                {
                    "sequence": attempted_count,
                    "status_code": (
                        exc.status_code
                    ),
                    "error": exc.detail,
                }
            )

            # 单道菜谱错误不阻断整批。
            continue

        skipped_duplicates.extend(
            result.get(
                "skipped_duplicates",
                [],
            )
        )

        blocked_duplicates.extend(
            result.get(
                "blocked_duplicates",
                [],
            )
        )

        item_result = result.get("item")

        if not isinstance(
            item_result,
            dict,
        ):
            stop_reason = (
                "blocked_duplicate"
                if result.get(
                    "blocked_duplicates"
                )
                else "no_queued"
            )
            break

        normalized_count += 1

        item_id = int(
            item_result["id"]
        )

        db.expire_all()

        item = get_item_or_404(
            db,
            job.id,
            item_id,
        )

        if not item.normalized_json:
            processing_failed.append(
                {
                    "item_id": item_id,
                    "name": item_result.get(
                        "source_title"
                    ),
                    "error": (
                        "Normalized result "
                        "was not stored"
                    ),
                }
            )
            continue

        try:
            normalized = (
                NormalizedRecipe
                .model_validate_json(
                    item.normalized_json
                )
            )

        except ValidationError as exc:
            processing_failed.append(
                {
                    "item_id": item_id,
                    "name": item_result.get(
                        "source_title"
                    ),
                    "error": (
                        "Stored normalized result "
                        "failed validation"
                    ),
                    "validation_errors": (
                        exc.errors(
                            include_url=False
                        )
                    ),
                }
            )
            continue

        warning_groups = (
            classify_import_warnings(
                normalized
            )
        )

        if (
            warning_groups["blocking"]
            or warning_groups[
                "confirmation"
            ]
        ):
            requires_review.append(
                {
                    "item_id": item.id,
                    "name": normalized.name,
                    "blocking_warnings": (
                        warning_groups[
                            "blocking"
                        ]
                    ),
                    "confirmation_warnings": (
                        warning_groups[
                            "confirmation"
                        ]
                    ),
                    "ignored_warnings": (
                        warning_groups[
                            "ignored"
                        ]
                    ),
                }
            )
            continue

        try:
            approve_item_for_import(
                job.id,
                item.id,
                ImportItemApproval(
                    confirm_name=(
                        normalized.name
                    ),
                    acknowledge_warnings=False,
                    review_note=None,
                ),
                db,
            )

            db.expire_all()

            import_result = (
                await import_item_to_mealie(
                    job.id,
                    item.id,
                    MealieImportConfirmation(
                        confirm_item_id=(
                            item.id
                        ),
                        confirm_name=(
                            normalized.name
                        ),
                    ),
                    db,
                )
            )

            imported.append(
                {
                    "item_id": item.id,
                    "name": normalized.name,
                    "mealie_slug": (
                        import_result.get(
                            "mealie_slug"
                        )
                    ),
                    "mealie_recipe_id": (
                        import_result.get(
                            "mealie_recipe_id"
                        )
                    ),
                    "idempotent": (
                        import_result.get(
                            "idempotent",
                            False,
                        )
                    ),
                }
            )

        except HTTPException as exc:
            db.rollback()

            import_failed.append(
                {
                    "item_id": item.id,
                    "name": normalized.name,
                    "status_code": (
                        exc.status_code
                    ),
                    "error": exc.detail,
                }
            )

        except Exception as exc:
            db.rollback()

            import_failed.append(
                {
                    "item_id": item.id,
                    "name": normalized.name,
                    "error": (
                        f"{exc.__class__.__name__}: "
                        f"{str(exc)}"
                    )[:4000],
                }
            )

    unload_result = None

    if request.unload_model_after_batch:
        unload_result = (
            await unload_ollama_model()
        )

    db.expire_all()

    current_job = get_job_or_404(
        db,
        job.id,
    )

    counts = job_status_counts(
        db,
        current_job.id,
    )

    return {
        "job_id": current_job.id,
        "job_name": current_job.name,
        "job_status": current_job.status,
        "requested_count": request.count,
        "attempted_count": attempted_count,
        "normalized_count": normalized_count,
        "imported_count": len(imported),
        "requires_review_count": len(
            requires_review
        ),
        "processing_failed_count": len(
            processing_failed
        ),
        "import_failed_count": len(
            import_failed
        ),
        "stopped_early": (
            stop_reason is not None
        ),
        "stop_reason": stop_reason,
        "infrastructure_error": (
            infrastructure_error
        ),
        "requeued_infrastructure_items": (
            requeued_infrastructure_items
        ),
        "imported": imported,
        "requires_review": (
            requires_review
        ),
        "processing_failed": (
            processing_failed
        ),
        "import_failed": import_failed,
        "skipped_duplicates": (
            skipped_duplicates
        ),
        "blocked_duplicates": (
            blocked_duplicates
        ),
        "ollama_unload": unload_result,
        "status_counts": counts,
        "message": (
            "Batch stopped because Ollama "
            "became unavailable."
            if infrastructure_error
            else
            "Recipes were processed and "
            "eligible results were imported."
        ),
    }


def load_normalized_item_for_native(
    item: RecipeImportItem,
) -> NormalizedRecipe:
    if not item.normalized_json:
        raise HTTPException(
            status_code=409,
            detail=(
                "This item has no normalized result"
            ),
        )

    try:
        return (
            NormalizedRecipe.model_validate_json(
                item.normalized_json
            )
        )

    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Stored normalized result "
                    "is invalid"
                ),
                "errors": exc.errors(
                    include_url=False
                ),
            },
        ) from exc


@router.get(
    "/{job_id}/items/{item_id}/"
    "native-structure-preview"
)
async def preview_native_structure(
    job_id: int,
    item_id: int,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    if item.status not in {
        "approved_for_import",
        "imported",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Item must be approved or imported"
            ),
        )

    normalized = (
        load_normalized_item_for_native(
            item
        )
    )

    recipe = db.get(
        SourceRecipe,
        item.source_recipe_id,
    )

    source = db.get(
        RecipeSource,
        job.source_id,
    )

    if recipe is None or source is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Source or source recipe "
                "no longer exists"
            ),
        )

    load_source_content_for_import(
        source,
        recipe,
        item,
    )

    writer = MealieWriter()

    resolution = (
        await resolve_recipe_entities(
            writer,
            normalized,
            create_missing=False,
        )
    )

    return {
        "job_id": job.id,
        "item_id": item.id,
        "item_status": item.status,
        "recipe_name": normalized.name,
        "resolution": resolution,
        "message": (
            "Preview only. Missing entities "
            "were not created."
        ),
    }


@router.post(
    "/{job_id}/items/{item_id}/"
    "upgrade-mealie-structure"
)
async def upgrade_mealie_structure(
    job_id: int,
    item_id: int,
    request: MealieImportConfirmation,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    if item.status != "imported":
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Only imported items can "
                    "be upgraded"
                ),
                "current_status": item.status,
            },
        )

    if request.confirm_item_id != item.id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Item confirmation does "
                    "not match"
                ),
                "expected": item.id,
                "received": (
                    request.confirm_item_id
                ),
            },
        )

    normalized = (
        load_normalized_item_for_native(
            item
        )
    )

    if request.confirm_name != normalized.name:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Recipe-name confirmation "
                    "does not match"
                ),
                "expected": normalized.name,
                "received": (
                    request.confirm_name
                ),
            },
        )

    recipe = db.get(
        SourceRecipe,
        item.source_recipe_id,
    )

    source = db.get(
        RecipeSource,
        job.source_id,
    )

    if recipe is None or source is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Source or source recipe "
                "no longer exists"
            ),
        )

    load_source_content_for_import(
        source,
        recipe,
        item,
    )

    ensure_mealie_import_schema(db)

    record = get_record_by_item(
        db,
        item.id,
    )

    if (
        record is None
        or record.get("state")
        != "imported"
        or not record.get("mealie_slug")
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Imported Mealie record "
                "is missing"
            ),
        )

    slug = str(
        record["mealie_slug"]
    )

    writer = MealieWriter()

    current_recipe = (
        await writer.get_recipe(slug)
    )

    existing_errors = (
        verify_native_structure(
            normalized,
            current_recipe,
        )
    )

    if not existing_errors:
        return {
            "job_id": job.id,
            "item_id": item.id,
            "item_status": item.status,
            "mealie_slug": slug,
            "idempotent": True,
            "message": (
                "Recipe already uses native "
                "Mealie structure."
            ),
        }

    resolution = (
        await resolve_recipe_entities(
            writer,
            normalized,
            create_missing=True,
        )
    )

    if resolution[
        "summary"
    ]["missing"]:
        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Some Mealie entities "
                    "could not be resolved"
                ),
                "resolution": resolution,
            },
        )

    native_ingredients = (
        build_mealie_native_ingredients(
            normalized,
            foods=resolution["foods"],
            units=resolution["units"],
        )
    )

    source_url = build_pinned_source_url(
        source,
        recipe,
        item,
    )

    import_key = build_import_key(
        source_id=source.id,
        source_recipe_id=recipe.id,
        source_content_sha256=(
            item.source_content_sha256
        ),
    )

    payload = build_mealie_patch_payload(
        normalized,
        blank_recipe=current_recipe,
        import_key=import_key,
        source_url=source_url,
        source_commit=(
            item.source_commit
        ),
        source_content_sha256=(
            item.source_content_sha256
        ),
        native_categories=(
            resolution["categories"]
        ),
        native_tags=(
            resolution["tags"]
        ),
        native_ingredients=(
            native_ingredients
        ),
    )

    rollback_payload = dict(
        current_recipe
    )

    rollback_payload.pop(
        "updatedAt",
        None,
    )

    try:
        await writer.patch_recipe(
            slug,
            payload,
        )

        verified_recipe = (
            await writer.get_recipe(
                slug
            )
        )

        verification_errors = (
            verify_native_structure(
                normalized,
                verified_recipe,
                resolved_categories=(
                    resolution["categories"]
                ),
                resolved_tags=resolution["tags"],
            )
        )

        if verification_errors:
            raise MealieImportError(
                "Native structure verification "
                "failed: "
                + "; ".join(
                    verification_errors
                )
            )

    except Exception as exc:
        rollback_succeeded = False
        rollback_error = None

        try:
            await writer.patch_recipe(
                slug,
                rollback_payload,
            )

            rollback_succeeded = True

        except Exception as cleanup_exc:
            rollback_error = (
                f"{cleanup_exc.__class__.__name__}: "
                f"{cleanup_exc}"
            )[:2000]

        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Native structure upgrade "
                    "failed"
                ),
                "error": (
                    f"{exc.__class__.__name__}: "
                    f"{exc}"
                )[:4000],
                "rollback_succeeded": (
                    rollback_succeeded
                ),
                "rollback_error": (
                    rollback_error
                ),
            },
        ) from exc

    return {
        "job_id": job.id,
        "item_id": item.id,
        "item_status": item.status,
        "mealie_slug": slug,
        "idempotent": False,
        "resolution_summary": (
            resolution["summary"]
        ),
        "verified": {
            "categories": [
                value.get("name")
                for value
                in verified_recipe.get(
                    "recipeCategory",
                    [],
                )
            ],
            "tags": [
                value.get("name")
                for value
                in verified_recipe.get(
                    "tags",
                    [],
                )
            ],
            "ingredients": [
                {
                    "food": (
                        value.get(
                            "food",
                            {},
                        ).get("name")
                        if isinstance(
                            value.get("food"),
                            dict,
                        )
                        else None
                    ),
                    "unit": (
                        value.get(
                            "unit",
                            {},
                        ).get("name")
                        if isinstance(
                            value.get("unit"),
                            dict,
                        )
                        else None
                    ),
                    "quantity": (
                        value.get("quantity")
                    ),
                }
                for value
                in verified_recipe.get(
                    "recipeIngredient",
                    [],
                )
            ],
            "schema_version": (
                verified_recipe.get(
                    "extras",
                    {},
                ).get(
                    "foodAssistantSchemaVersion"
                )
            ),
        },
        "message": (
            "Existing Mealie recipe was "
            "upgraded and verified."
        ),
    }


@router.post(
    "/{job_id}/items/{item_id}/revalidate"
)
def revalidate_import_item(
    job_id: int,
    item_id: int,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    if not item.normalized_json:
        raise HTTPException(
            status_code=409,
            detail=(
                "This item has no normalized "
                "result to revalidate"
            ),
        )

    recipe = db.get(
        SourceRecipe,
        item.source_recipe_id,
    )

    source = db.get(
        RecipeSource,
        job.source_id,
    )

    if recipe is None or source is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Source or source recipe "
                "no longer exists"
            ),
        )

    try:
        normalized = (
            NormalizedRecipe.model_validate_json(
                item.normalized_json
            )
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Stored normalized result "
                    "is invalid"
                ),
                "errors": exc.errors(
                    include_url=False
                ),
            },
        ) from exc

    repository_directory = source_repo_dir(
        source.id
    ).resolve()

    recipe_path = (
        repository_directory / recipe.path
    ).resolve()

    if (
        recipe_path != repository_directory
        and repository_directory
        not in recipe_path.parents
    ):
        raise HTTPException(
            status_code=500,
            detail="Invalid indexed source path",
        )

    if not recipe_path.is_file():
        item.status = "source_updated"
        item.error = (
            "Source recipe file is missing"
        )

        db.commit()

        raise HTTPException(
            status_code=409,
            detail=item.error,
        )

    content = recipe_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    current_digest = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    if (
        current_digest
        != item.source_content_sha256
    ):
        item.status = "source_updated"
        item.error = (
            "Source recipe changed after "
            "this job was created"
        )

        db.commit()

        raise HTTPException(
            status_code=409,
            detail=item.error,
        )

    (
        normalized,
        quality_issues,
    ) = apply_recipe_quality_gate(
        normalized,
        source_text=content,
        source_name=source.name,
        source_url=build_source_url(
            source,
            recipe,
        ),
        source_path=recipe.path,
        source_license=None,
    )

    item.normalized_json = json.dumps(
        normalized.model_dump(
            mode="json",
        ),
        ensure_ascii=False,
    )

    item.status = "review"
    item.error = None

    db.flush()

    counts = update_job_status(
        db,
        job,
    )

    db.commit()

    return {
        "job_id": job.id,
        "job_status": job.status,
        "item": {
            "id": item.id,
            "source_recipe_id": recipe.id,
            "source_title": recipe.title,
            "status": item.status,
            "normalized": normalized.model_dump(
                mode="json",
            ),
            "quality_issues": quality_issues,
            "inventory_policies": [
                {
                    "food_name": (
                        ingredient.food_name
                    ),
                    "policy": (
                        inventory_policy_for_food(
                            ingredient.food_name
                        )
                    ),
                }
                for ingredient
                in normalized.ingredients
            ],
        },
        "status_counts": counts,
        "message": (
            "Stored AI result was revalidated. "
            "Ollama was not called and nothing "
            "was written to Mealie."
        ),
    }


@router.get("/{job_id}/items")
def list_import_job_items(
    job_id: int,
    item_status: str | None = Query(
        default=None,
        alias="status",
        max_length=40,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    statement = (
        select(
            RecipeImportItem,
            SourceRecipe,
        )
        .join(
            SourceRecipe,
            SourceRecipe.id
            == RecipeImportItem.source_recipe_id,
        )
        .where(
            RecipeImportItem.job_id == job.id
        )
    )

    if item_status:
        statement = statement.where(
            RecipeImportItem.status
            == item_status
        )

    rows = db.execute(
        statement
        .order_by(
            RecipeImportItem.id.asc()
        )
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "job_id": job.id,
        "job_status": job.status,
        "total_items": job.total_items,
        "status_counts": (
            job_status_counts(
                db,
                job.id,
            )
        ),
        "items": [
            {
                "id": item.id,
                "source_recipe_id": recipe.id,
                "title": recipe.title,
                "category": recipe.category,
                "path": recipe.path,
                "status": item.status,
                "attempts": item.attempts,
                "has_normalized_result": (
                    item.normalized_json
                    is not None
                ),
                "source_content_sha256": (
                    item.source_content_sha256
                ),
                "source_commit": (
                    item.source_commit
                ),
                "error": item.error,
            }
            for item, recipe in rows
        ],
    }


@router.get(
    "/{job_id}/items/{item_id}"
)
def read_import_job_item(
    job_id: int,
    item_id: int,
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(
        db,
        job_id,
    )

    item = get_item_or_404(
        db,
        job_id,
        item_id,
    )

    recipe = db.get(
        SourceRecipe,
        item.source_recipe_id,
    )

    return {
        "job_id": job.id,
        "job_status": job.status,
        "item": {
            "id": item.id,
            "source_recipe_id": (
                item.source_recipe_id
            ),
            "source_title": (
                recipe.title
                if recipe is not None
                else None
            ),
            "source_path": (
                recipe.path
                if recipe is not None
                else None
            ),
            "status": item.status,
            "attempts": item.attempts,
            "error": item.error,
            "duplicate_of_item_id": item.duplicate_of_item_id,
            "duplicate_mealie_slug": item.duplicate_mealie_slug,
            "duplicate_reason": item.duplicate_reason,
            "normalized": load_normalized_json(
                item.normalized_json
            ),
        },
    }
