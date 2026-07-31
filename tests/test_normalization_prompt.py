from __future__ import annotations

from app.import_queue import build_normalization_user_prompt


def test_normalization_prompt_starts_with_complete_recipe_and_omits_schema() -> None:
    content = "# 菜谱\n\n## 配料\n\n- 水\n\n## 步骤\n\n1. 加水"
    prompt = build_normalization_user_prompt(
        content=content,
        source_metadata={
            "source_name": "source",
            "source_url": "https://example.test/recipe",
            "source_path": "recipe.md",
            "source_license": None,
        },
    )

    assert prompt.index(content) < prompt.index("来源信息")
    assert content in prompt
    assert "已有菜谱名称" not in prompt
    assert '"$defs"' not in prompt
    assert "ingredients 和 instructions 均不得为空" in prompt
    assert prompt.count(content) == 1
