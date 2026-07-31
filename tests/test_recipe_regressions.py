from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai_recipes import RecipeTimer, repair_normalized_recipe_payload
from app.import_queue import (
    _v20_normalize_categories,
    _v20_prepare_normalized_payload,
)


def test_side_dish_category_mapping() -> None:
    assert _v20_normalize_categories("酱料", recipe_name="葱油") == ["配菜"]
    assert _v20_normalize_categories("配 菜", recipe_name="凉拌菜") == ["配菜"]


def test_nested_source_fields_are_lifted() -> None:
    result = _v20_prepare_normalized_payload(
        {
            "title": "测试菜",
            "source": {
                "summary": "说明",
                "category": "配菜",
                "ingredients": [{"food_name": "盐", "original_text": "盐"}],
                "instructions": [{"step_number": 1, "text": "混合"}],
            },
        },
        source_metadata={"source_name": "example"},
        source_title="原始菜名",
    )
    assert result["description"] == "说明"
    assert result["categories"] == ["配菜"]
    assert result["source"] == {"source_name": "example"}


def test_title_alias_repairs_name() -> None:
    result = _v20_prepare_normalized_payload(
        {"title": "别名菜谱"},
        source_metadata={},
        source_title="原始标题",
    )
    assert result["name"] == "别名菜谱"
    assert result["original_name"] == "别名菜谱"


def test_repair_preserves_valid_timer() -> None:
    result = repair_normalized_recipe_payload(
        {
            "instructions": [
                {
                    "step_number": 1,
                    "text": "等待",
                    "timers": [{"name": "等待", "seconds": 60}],
                }
            ]
        }
    )
    assert result["instructions"][0]["timers"][0]["duration_seconds"] == 60


def test_timer_accepts_31_days() -> None:
    assert RecipeTimer(name="最长安全计时", duration_seconds=31 * 86400)


def test_timer_rejects_more_than_31_days() -> None:
    with pytest.raises(ValidationError):
        RecipeTimer(name="超长计时", duration_seconds=31 * 86400 + 1)
