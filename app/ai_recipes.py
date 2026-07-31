from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from app.llm.factory import get_llm_provider

from app.ollama_client import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OllamaClientError,
    ollama_tags,
)


Cuisine = Literal[
    "中餐",
    "日料",
    "西餐",
    "其他",
]

Category = Literal[
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
]

RecipeTag = Annotated[
    str,
    Field(
        min_length=1,
        max_length=50,
    ),
]

Recommendation = Literal[
    "import",
    "review",
    "skip",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class RecipeNormalizeRequest(StrictModel):
    source_text: str = Field(
        min_length=20,
        max_length=50000,
    )

    source_name: str | None = Field(
        default=None,
        max_length=200,
    )

    source_url: str | None = Field(
        default=None,
        max_length=2000,
    )

    source_path: str | None = Field(
        default=None,
        max_length=1000,
    )

    source_license: str | None = Field(
        default=None,
        max_length=200,
    )

    existing_recipe_names: list[str] = Field(
        default_factory=list,
        max_length=500,
    )


IngredientAmountMode = Literal[
    "exact",
    "range",
    "as_needed",
    "coverage",
    "to_taste",
    "unspecified",
]


IngredientRole = Literal[
    "main",
    "seasoning",
    "process",
    "garnish",
]


TimerKind = Literal[
    "fixed",
    "range",
]


TimerSource = Literal[
    "automatic",
    "manual",
]


class NormalizedIngredient(StrictModel):
    food_name: str = Field(
        min_length=1,
        max_length=150,
    )

    quantity: float | None = Field(
        default=None,
        ge=0,
    )

    quantity_max: float | None = Field(
        default=None,
        ge=0,
    )

    unit: str | None = Field(
        default=None,
        max_length=50,
    )

    amount_mode: IngredientAmountMode = (
        "exact"
    )

    role: IngredientRole = "main"

    note: str | None = Field(
        default=None,
        max_length=500,
    )

    original_text: str = Field(
        min_length=1,
        max_length=1000,
    )

    optional: bool = False


class RecipeTimer(StrictModel):
    name: str = Field(
        min_length=1,
        max_length=100,
    )

    kind: TimerKind = "fixed"

    duration_seconds: int | None = Field(
        default=None,
        ge=1,
        le=2678400,
    )

    duration_min_seconds: int | None = Field(
        default=None,
        ge=1,
        le=2678400,
    )

    duration_max_seconds: int | None = Field(
        default=None,
        ge=1,
        le=2678400,
    )

    source: TimerSource = "automatic"

    accepted: bool = True


class RecipeInstruction(StrictModel):
    step_number: int = Field(
        ge=1,
        le=500,
    )

    text: str = Field(
        min_length=1,
        max_length=4000,
    )

    timers: list[RecipeTimer] = Field(
        default_factory=list,
        max_length=20,
    )


class RecipeSource(StrictModel):
    source_name: str | None = None
    source_url: str | None = None
    source_path: str | None = None
    source_license: str | None = None


class NormalizedRecipe(StrictModel):
    name: str = Field(
        min_length=1,
        max_length=200,
    )

    original_name: str = Field(
        min_length=1,
        max_length=200,
    )

    description: str | None = Field(
        default=None,
        max_length=3000,
    )

    cuisine: Cuisine
    categories: list[Category]
    tags: list[RecipeTag] = Field(
        max_length=12,
    )

    servings: float | None = Field(
        default=None,
        gt=0,
    )

    prep_time_minutes: int | None = Field(
        default=None,
        ge=0,
        le=10080,
    )

    cook_time_minutes: int | None = Field(
        default=None,
        ge=0,
        le=10080,
    )

    total_time_minutes: int | None = Field(
        default=None,
        ge=0,
        le=10080,
    )

    ingredients: list[NormalizedIngredient] = Field(
        min_length=1,
        max_length=200,
    )

    instructions: list[RecipeInstruction] = Field(
        min_length=1,
        max_length=500,
    )

    source: RecipeSource

    import_score: int = Field(
        ge=0,
        le=100,
    )

    recommendation: Recommendation

    possible_duplicate: bool = False

    duplicate_candidates: list[str] = Field(
        default_factory=list,
        max_length=50,
    )

    warnings: list[str] = Field(
        default_factory=list,
        max_length=100,
    )

    review_required: bool = False


def _repair_key(
    value: object,
) -> str:
    if not isinstance(value, str):
        return ""

    return "".join(
        character
        for character in value.casefold()
        if character.isalnum()
    )


def _repair_number(
    value: object,
) -> float | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        raw = value.strip()

        if not raw:
            return None

        try:
            return float(raw)
        except ValueError:
            return None

    return None


def _repair_boolean(
    value: object,
    *,
    default: bool = False,
) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalised = value.strip().casefold()

        if normalised in {
            "true",
            "yes",
            "1",
            "是",
        }:
            return True

        if normalised in {
            "false",
            "no",
            "0",
            "否",
        }:
            return False

    return default


def _repair_food_name(
    ingredient: dict,
) -> str | None:
    # 优先使用明确名称字段，不把包含完整原文的
    # “food, name”等异常字段误当成食材名称。
    candidates = (
        ingredient.get("food_name"),
        ingredient.get("ingredient_name"),
        ingredient.get("name"),
        ingredient.get("ingredient"),
        ingredient.get("food"),
    )

    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate = candidate.get("name")

        if (
            isinstance(candidate, str)
            and candidate.strip()
        ):
            return candidate.strip()

    for key, value in ingredient.items():
        if _repair_key(key) not in {
            "foodname",
            "ingredientname",
        }:
            continue

        if (
            isinstance(value, str)
            and value.strip()
        ):
            return value.strip()

    return None


def _repair_original_text(
    ingredient: dict,
    food_name: str | None,
) -> str:
    for key in (
        "original_text",
        "originalText",
        "raw_text",
        "rawText",
        "display",
        "source_text",
    ):
        value = ingredient.get(key)

        if (
            isinstance(value, str)
            and value.strip()
        ):
            return value.strip()

    # 某些模型会错误生成 “food, name”，其内容更像
    # 原始食材描述。只将其作为 original_text 使用。
    for key, value in ingredient.items():
        if key in {
            "food_name",
            "ingredient_name",
            "name",
            "food",
            "ingredient",
        }:
            continue

        if _repair_key(key) != "foodname":
            continue

        if (
            isinstance(value, str)
            and value.strip()
        ):
            return value.strip()

    return food_name or "未命名食材"


def _repair_amount_mode(
    ingredient: dict,
    *,
    quantity: float | None,
    quantity_max: float | None,
    note: str | None,
    original_text: str,
) -> str:
    allowed = {
        "exact",
        "range",
        "as_needed",
        "coverage",
        "to_taste",
        "unspecified",
    }

    raw_mode = ingredient.get(
        "amount_mode"
    )

    if raw_mode in allowed:
        return raw_mode

    combined = (
        (note or "")
        + " "
        + original_text
    )

    if quantity_max is not None:
        return "range"

    if quantity is not None:
        return "exact"

    if any(
        value in combined
        for value in (
            "淹没",
            "没过",
            "浸没",
            "覆盖",
        )
    ):
        return "coverage"

    if any(
        value in combined
        for value in (
            "按口味",
            "依口味",
            "酌量",
        )
    ):
        return "to_taste"

    if any(
        value in combined
        for value in (
            "适量",
            "少许",
            "少量",
            "按需",
        )
    ):
        return "as_needed"

    return "unspecified"


def _repair_ingredient(
    value: object,
) -> object:
    if not isinstance(value, dict):
        return value

    food_name = _repair_food_name(value)

    quantity = _repair_number(
        value.get(
            "quantity",
            value.get("amount"),
        )
    )

    quantity_max = _repair_number(
        value.get(
            "quantity_max",
            value.get("max_quantity"),
        )
    )

    unit_value = value.get(
        "unit",
        value.get("measurement"),
    )

    unit = (
        unit_value.strip()
        if isinstance(unit_value, str)
        and unit_value.strip()
        else None
    )

    note_value = value.get(
        "note",
        value.get(
            "notes",
            value.get("remark"),
        ),
    )

    note = (
        note_value.strip()
        if isinstance(note_value, str)
        and note_value.strip()
        else None
    )

    original_text = _repair_original_text(
        value,
        food_name,
    )

    role = value.get("role", "main")

    if role not in {
        "main",
        "seasoning",
        "process",
        "garnish",
    }:
        role = "main"

    amount_mode = _repair_amount_mode(
        value,
        quantity=quantity,
        quantity_max=quantity_max,
        note=note,
        original_text=original_text,
    )

    return {
        "food_name": (
            food_name
            or "未识别食材"
        ),
        "quantity": quantity,
        "quantity_max": quantity_max,
        "unit": unit,
        "amount_mode": amount_mode,
        "role": role,
        "note": note,
        "original_text": original_text,
        "optional": _repair_boolean(
            value.get("optional"),
            default=False,
        ),
    }


def _repair_timer(
    value: object,
) -> object:
    if not isinstance(value, dict):
        return value

    minimum = _repair_number(
        value.get(
            "duration_min_seconds",
            value.get("min_seconds"),
        )
    )

    maximum = _repair_number(
        value.get(
            "duration_max_seconds",
            value.get("max_seconds"),
        )
    )

    duration = _repair_number(
        value.get(
            "duration_seconds",
            value.get("seconds"),
        )
    )

    kind = value.get("kind")

    if kind not in {
        "fixed",
        "range",
    }:
        kind = (
            "range"
            if minimum is not None
            or maximum is not None
            else "fixed"
        )

    name = value.get("name")

    if not isinstance(name, str) or not name.strip():
        name = "计时器"

    source = value.get(
        "source",
        "automatic",
    )

    if source not in {
        "automatic",
        "manual",
    }:
        source = "automatic"

    default_accepted = (
        kind == "fixed"
    )

    return {
        "name": name.strip(),
        "kind": kind,
        "duration_seconds": (
            round(duration)
            if duration is not None
            else None
        ),
        "duration_min_seconds": (
            round(minimum)
            if minimum is not None
            else None
        ),
        "duration_max_seconds": (
            round(maximum)
            if maximum is not None
            else None
        ),
        "source": source,
        "accepted": _repair_boolean(
            value.get("accepted"),
            default=default_accepted,
        ),
    }


def repair_normalized_recipe_payload(
    payload: object,
) -> object:
    """
    Repair common LLM schema drift before strict Pydantic
    validation. The repaired result is still validated with
    NormalizedRecipe, so invalid data cannot bypass the model.
    """
    if not isinstance(payload, dict):
        return payload

    repaired = dict(payload)

    ingredients = repaired.get(
        "ingredients"
    )

    if isinstance(ingredients, list):
        repaired["ingredients"] = [
            _repair_ingredient(value)
            for value in ingredients
        ]

    instructions = repaired.get(
        "instructions"
    )

    if isinstance(instructions, list):
        repaired_instructions = []

        for instruction in instructions:
            if not isinstance(
                instruction,
                dict,
            ):
                repaired_instructions.append(
                    instruction
                )
                continue

            clean_instruction = {
                key: instruction.get(key)
                for key in (
                    "step_number",
                    "text",
                )
                if key in instruction
            }

            timers = instruction.get(
                "timers",
                [],
            )

            clean_instruction["timers"] = (
                [
                    _repair_timer(timer)
                    for timer in timers
                ]
                if isinstance(timers, list)
                else []
            )

            repaired_instructions.append(
                clean_instruction
            )

        repaired["instructions"] = (
            repaired_instructions
        )

    return repaired


class RecipeNormalizeResponse(StrictModel):
    status: Literal["ok"]
    model: str
    recipe: NormalizedRecipe


SYSTEM_PROMPT = """
你是家庭 Mealie 菜谱库的数据标准化助手。

家庭饮食以中餐家常菜为主，也接受日式家常菜，以及意大利面、
焗饭、烤鸡、炖肉等简单西餐。

你一次只处理一道菜谱。

必须遵守：

1. 只能整理输入中明确存在的信息，不得编造食材、数量、步骤、
   时间、温度、份量或来源。
2. 原文没有份量时 servings 必须为 null，不能因为家庭默认两人
   就擅自填写 2。
3. “适量”“少许”“一把”等不能虚构数值，应把 quantity 和 unit
   保持为 null，并把原文含义放入 note。
4. 食材名称可以标准化，但 original_text 必须保留输入原文。
5. 鸡胸肉和鸡腿肉、牛奶和淡奶油、生米和熟米饭不得错误合并。
6. 只有原文明示持续时间时，才能生成 timers。
7. 时间字段只有原文明示时才能填写。
8. 步骤必须按原始顺序整理成独立可执行动作。
9. 信息缺失、疑似错误或无法确认时，加入 warnings，并将
   review_required 设为 true。
10. 根据已有菜谱名称判断可能重复，但不得自行删除。
11. 面向用户的文本全部使用中文。
12. 只返回符合给定 JSON Schema 的对象，不要输出解释、
    Markdown 或代码块。
13. tags 优先使用家常菜、快手菜、蒸、炒、炖、烤、煮、凉拌、
    意面、米饭、面食、待试做、来源-HowToCook等稳定标签。
    原文明确涉及微波炉、空气炸锅等方式时，可以使用“微波”、
    “空气炸锅”等额外标签。标签总数不要超过 8 个。

导入评分：

- 日常可做、材料常见、步骤完整：加分。
- 中餐家常菜、日料家常菜、简单意面西餐：加分。
- 食材特殊、步骤残缺、用途过窄、疑似重复：减分。
- 80～100：import。
- 50～79：review。
- 0～49：skip。
- 存在严重缺失时，即使分数较高也必须 review。
""".strip()


router = APIRouter(
    tags=["ai"],
)


@router.get(
    "/api/v1/integrations/ollama/status"
)
async def ollama_status() -> dict:
    """
    Ollama availability is reported separately.

    An offline Windows AI host must not make the main
    food-assistant container unhealthy.
    """
    try:
        payload = await ollama_tags()
    except OllamaClientError as exc:
        return {
            "status": "unavailable",
            "ollama_base_url": OLLAMA_BASE_URL,
            "configured_model": OLLAMA_MODEL,
            "configured_model_present": False,
            "detail": str(exc),
        }

    models = []

    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue

        name = item.get("name")

        if isinstance(name, str):
            models.append(name)

    return {
        "status": "ok",
        "ollama_base_url": OLLAMA_BASE_URL,
        "configured_model": OLLAMA_MODEL,
        "configured_model_present": (
            OLLAMA_MODEL in models
        ),
        "available_models": models,
    }


@router.post(
    "/api/v1/ai/recipe/normalize",
    response_model=RecipeNormalizeResponse,
)
async def normalize_recipe(
    request: RecipeNormalizeRequest,
) -> RecipeNormalizeResponse:
    schema = NormalizedRecipe.model_json_schema()

    source_metadata = {
        "source_name": request.source_name,
        "source_url": request.source_url,
        "source_path": request.source_path,
        "source_license": request.source_license,
    }

    user_prompt = (
        "请整理以下一道菜谱。\n\n"
        "来源信息：\n"
        + json.dumps(
            source_metadata,
            ensure_ascii=False,
        )
        + "\n\n已有菜谱名称，用于重复检测：\n"
        + json.dumps(
            request.existing_recipe_names,
            ensure_ascii=False,
        )
        + "\n\n必须遵循的输出 JSON Schema：\n"
        + json.dumps(
            schema,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n\n待整理菜谱原文：\n"
        + request.source_text
    )

    try:
        payload = await get_llm_provider().structured_chat(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=schema,
        )
    except OllamaClientError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Local AI unavailable",
                "error": str(exc),
            },
        ) from exc

    try:
        recipe = NormalizedRecipe.model_validate(
            payload
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Model response failed schema "
                    "validation"
                ),
                "errors": exc.errors(
                    include_url=False
                ),
                "model_response": payload,
            },
        ) from exc

    return RecipeNormalizeResponse(
        status="ok",
        model=OLLAMA_MODEL,
        recipe=recipe,
    )
