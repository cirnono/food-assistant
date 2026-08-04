from __future__ import annotations

from collections.abc import Generator
import json
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.cooking_sessions as cooking
import app.shopping as shopping
from app.cooking_ui import COOKING_HTML
from app.consumption_ui import HTML as CONSUMPTION_HTML
from app.pantry_ui import PANTRY_HTML, RECOMMENDATIONS_HTML
from app.quality_ui import HTML as QUALITY_HTML
from app.shopping_ui import HTML as SHOPPING_HTML
from app.api_auth import read_api_token
from app.consumption import build_consumption_proposal
from app.database import Base, get_db
from app.main import app
from app.models import (
    ConsumptionReview,
    CookingSession,
    InventoryAdjustment,
    PantryItem,
    ShoppingListItem,
)
from app.units import (
    normalize_unit,
    unit_match_reason,
    units_compatible,
    units_merge_compatible,
)


TOKEN = {"X-Food-Assistant-Token": "example-development-token-00000000"}


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("g", "克"),
        ("ml", "毫升"),
        ("tbsp", "汤匙"),
        ("tsp", "茶匙"),
        ("kg", "公斤"),
        (None, None),
        (" GRAMS. ", "克"),
    ],
)
def test_equivalent_units_are_compatible(left, right):
    assert units_compatible(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [("g", "kg"), ("ml", "l"), (None, "g"), ("适量", "适量"), ("个", "枚")],
)
def test_non_equivalent_units_are_not_compatible(left, right):
    assert not units_compatible(left, right)


def test_unit_normalization_is_comparison_only():
    assert normalize_unit(" 公克。 ") == "g"
    assert normalize_unit("少许") is None
    assert unit_match_reason("克", "g") == "equivalent spelling"
    assert units_merge_compatible("盒", " 盒 ")
    assert not units_merge_compatible("适量", "适量")


def recipe(slug: str = "tomato-eggs") -> dict:
    return {
        "name": "番茄炒蛋",
        "slug": slug,
        "recipeIngredient": [
            {"food": {"name": "鸡蛋"}, "quantity": 2, "unit": {"name": "个"}},
            {"food": {"name": "西红柿"}, "quantity": 1, "unit": {"name": "个"}},
            {"food": {"name": "水"}, "quantity": 1, "unit": {"name": "杯"}},
        ],
        "recipeInstructions": [{"text": "炒熟"}],
    }


@pytest.fixture()
def client_db(
    tmp_path, monkeypatch
) -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/v025.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)

    def override_db():
        yield session

    async def fake_detail(slug: str):
        return recipe(slug), None

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(cooking, "get_recipe_detail_cached", fake_detail)
    monkeypatch.setattr(shopping, "get_recipe_detail_cached", fake_detail)
    read_api_token.cache_clear()
    with TestClient(app) as client:
        yield client, session
    app.dependency_overrides.clear()
    session.close()


def start_and_finish(client: TestClient) -> dict:
    started = client.post(
        "/api/v1/cooking-sessions/start",
        headers=TOKEN,
        json={
            "owner": "household",
            "mealie_slug": "tomato-eggs",
            "confirm_slug": "tomato-eggs",
        },
    ).json()
    response = client.post(
        f"/api/v1/cooking-sessions/{started['id']}/finish",
        headers=TOKEN,
        json={
            "owner": "household",
            "confirm_session_id": started["id"],
            "select_next": False,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_finish_creates_one_stable_pending_review_and_ignores_water(client_db):
    client, session = client_db
    session.add(
        PantryItem(
            name="鸡蛋",
            normalized_name="鸡蛋",
            quantity=6,
            unit="个",
            owner="household",
        )
    )
    session.commit()
    finished = start_and_finish(client)
    review = finished["consumption_review"]
    assert review["status"] == "pending"
    assert session.scalar(select(func.count()).select_from(ConsumptionReview)) == 1
    payload = client.get(
        f"/api/v1/consumption-reviews/{review['id']}?owner=household", headers=TOKEN
    ).json()
    assert [item["recipe_ingredient_name"] for item in payload["proposal"]] == [
        "鸡蛋",
        "西红柿",
    ]
    assert payload["proposal"][0]["suggested_action"] == "deduct"


def test_equivalent_unit_proposal_and_confirm_preserve_raw_units(client_db):
    client, session = client_db
    pantry = PantryItem(
        name="鸡蛋", normalized_name="鸡蛋", quantity=100, unit="g", owner="household"
    )
    session.add(pantry)
    session.commit()
    proposal = build_consumption_proposal(
        session,
        "household",
        {"ingredients": [{"name": "鸡蛋", "quantity": 2, "unit": "克"}]},
    )[0]
    assert proposal["quantity_compatible"] is True
    assert proposal["recipe_unit"] == "克"
    assert proposal["pantry_unit"] == "g"
    assert proposal["recipe_unit_normalized"] == "g"
    assert proposal["pantry_unit_normalized"] == "g"
    assert proposal["unit_family"] == "mass"
    assert proposal["unit_match_reason"] == "equivalent spelling"


def test_matching_exact_alias_ambiguous_none_unknown_and_conflict(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/proposal.db")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                PantryItem(
                    name="番茄",
                    normalized_name="番茄",
                    quantity=3,
                    unit="个",
                    owner="household",
                ),
                PantryItem(
                    name="鸡蛋 A",
                    normalized_name="鸡蛋",
                    quantity=4,
                    unit="个",
                    owner="household",
                ),
                PantryItem(
                    name="鸡蛋 B",
                    normalized_name="鸡蛋",
                    quantity=None,
                    unit="个",
                    owner="household",
                ),
            ]
        )
        db.commit()
        proposal = build_consumption_proposal(
            db,
            "household",
            {
                "ingredients": [
                    {"name": "西红柿", "quantity": 1, "unit": "个"},
                    {"name": "鸡蛋", "quantity": 2, "unit": "个"},
                    {"name": "盐", "quantity": None, "unit": None},
                    {"name": "西红柿", "quantity": 1, "unit": "个"},
                ]
            },
        )
        assert [x["match_type"] for x in proposal] == [
            "alias",
            "ambiguous",
            "none",
            "alias",
        ]
        assert proposal[0]["pantry_item_conflict"] is True


def test_confirm_is_atomic_idempotent_audited_adds_shopping_and_undoes_once(client_db):
    client, session = client_db
    pantry = PantryItem(
        name="鸡蛋",
        normalized_name="鸡蛋",
        quantity=2,
        unit="个",
        low_stock_threshold=1,
        is_staple=True,
        owner="household",
    )
    session.add(pantry)
    session.commit()
    review_id = start_and_finish(client)["consumption_review"]["id"]
    payload = {
        "owner": "household",
        "confirm_review_id": review_id,
        "items": [
            {
                "recipe_ingredient_index": 0,
                "pantry_item_id": pantry.id,
                "action": "deduct",
                "quantity_used": 2,
                "unit": "个",
                "add_to_shopping_list_if_low": True,
            }
        ],
    }
    endpoint = f"/api/v1/consumption-reviews/{review_id}/confirm"
    first = client.post(endpoint, headers=TOKEN, json=payload)
    second = client.post(endpoint, headers=TOKEN, json=payload)
    assert first.status_code == second.status_code == 200
    session.refresh(pantry)
    assert pantry.quantity == 0
    assert session.scalar(select(func.count()).select_from(InventoryAdjustment)) == 1
    assert session.scalar(select(func.count()).select_from(ShoppingListItem)) == 1
    undo = client.post(
        f"/api/v1/consumption-reviews/{review_id}/undo",
        headers=TOKEN,
        json={"owner": "household", "confirm_review_id": review_id},
    )
    assert undo.status_code == 200
    session.refresh(pantry)
    assert pantry.quantity == 2
    assert session.scalar(select(func.count()).select_from(InventoryAdjustment)) == 2
    assert (
        client.post(
            f"/api/v1/consumption-reviews/{review_id}/undo",
            headers=TOKEN,
            json={"owner": "household", "confirm_review_id": review_id},
        ).status_code
        == 409
    )


def test_invalid_confirm_rolls_back_every_item_and_dismiss_changes_nothing(client_db):
    client, session = client_db
    one = PantryItem(
        name="鸡蛋", normalized_name="鸡蛋", quantity=5, unit="个", owner="household"
    )
    two = PantryItem(
        name="番茄", normalized_name="番茄", quantity=1, unit="个", owner="household"
    )
    session.add_all([one, two])
    session.commit()
    review_id = start_and_finish(client)["consumption_review"]["id"]
    response = client.post(
        f"/api/v1/consumption-reviews/{review_id}/confirm",
        headers=TOKEN,
        json={
            "owner": "household",
            "confirm_review_id": review_id,
            "items": [
                {
                    "recipe_ingredient_index": 0,
                    "pantry_item_id": one.id,
                    "action": "deduct",
                    "quantity_used": 1,
                    "unit": "个",
                },
                {
                    "recipe_ingredient_index": 1,
                    "pantry_item_id": two.id,
                    "action": "deduct",
                    "quantity_used": 2,
                    "unit": "个",
                },
            ],
        },
    )
    assert response.status_code == 409
    session.refresh(one)
    session.refresh(two)
    assert (one.quantity, two.quantity) == (5, 1)
    assert session.scalar(select(func.count()).select_from(InventoryAdjustment)) == 0
    assert (
        client.post(
            f"/api/v1/consumption-reviews/{review_id}/dismiss",
            headers=TOKEN,
            json={"owner": "household", "confirm_review_id": review_id},
        ).status_code
        == 200
    )


def test_shopping_dedup_complete_restock_and_pages(client_db):
    client, session = client_db
    assert client.get("/consumption").status_code == 200
    assert client.get("/shopping").status_code == 200
    create = {
        "owner": "household",
        "name": "牛奶",
        "quantity": 1,
        "unit": "盒",
        "priority": "normal",
        "source": "manual",
    }
    first = client.post("/api/v1/shopping-list", headers=TOKEN, json=create).json()
    client.post("/api/v1/shopping-list", headers=TOKEN, json=create)
    assert (
        len(client.get("/api/v1/shopping-list?owner=household", headers=TOKEN).json())
        == 1
    )
    completed = client.post(
        f"/api/v1/shopping-list/{first['id']}/complete",
        headers=TOKEN,
        json={
            "owner": "household",
            "confirm_item_id": first["id"],
            "restock": {
                "mode": "create",
                "quantity": 2,
                "unit": "盒",
                "location": "fridge",
            },
        },
    )
    assert completed.status_code == 200
    assert completed.json()["pantry_item"]["quantity"] == 2
    assert (
        client.post(
            f"/api/v1/shopping-list/{first['id']}/complete",
            headers=TOKEN,
            json={
                "owner": "household",
                "confirm_item_id": first["id"],
                "restock": {"mode": "create", "quantity": 2, "unit": "盒"},
            },
        ).json()["already_completed"]
        is True
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(PantryItem)
            .where(PantryItem.name == "牛奶")
        )
        == 1
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(InventoryAdjustment)
            .where(InventoryAdjustment.adjustment_type == "restock")
        )
        == 1
    )


def test_data_quality_summary_is_local_read_only_and_authenticated(client_db):
    client, session = client_db
    session.add(
        CookingSession(
            id=999,
            owner="household",
            mealie_slug="quality-test",
            recipe_name="测试菜谱",
            recipe_snapshot_json="{}",
            status="completed",
            current_step_index=0,
        )
    )
    session.flush()
    session.add_all(
        [
            PantryItem(
                name="盐", normalized_name="盐", quantity=None, unit=None, owner="household"
            ),
            PantryItem(
                name="食盐", normalized_name="盐", quantity=1, unit="适量", owner="household"
            ),
            ShoppingListItem(
                owner="household",
                name="牛奶",
                normalized_name="牛奶",
                quantity=None,
                unit=None,
                status="active",
                priority="normal",
                source="manual",
            ),
            ConsumptionReview(
                cooking_session_id=999,
                owner="household",
                recipe_name="测试菜谱",
                mealie_slug="quality-test",
                status="pending",
                proposal_json=json.dumps(
                    [
                        {"match_type": "ambiguous", "quantity_compatible": False},
                        {"match_type": "none", "quantity_compatible": False},
                        {
                            "match_type": "exact",
                            "matched_pantry_item_id": 1,
                            "quantity_compatible": False,
                        },
                    ]
                ),
            ),
        ]
    )
    session.commit()
    assert client.get("/api/v1/data-quality/summary").status_code == 401
    response = client.get("/api/v1/data-quality/summary", headers=TOKEN)
    assert response.status_code == 200
    data = response.json()
    assert data["inventory_unknown_quantity"] == 1
    assert data["inventory_missing_unit"] == 1
    assert data["inventory_unrecognized_unit"] == 1
    assert data["duplicate_normalized_names"] == 1
    assert data["pending_consumption_reviews"] == 1
    assert data["ambiguous_consumption_matches"] == 1
    assert data["unmatched_consumption_ingredients"] == 1
    assert data["incompatible_unit_matches"] == 1
    assert data["shopping_items_missing_quantity"] == 1
    assert data["shopping_items_missing_unit"] == 1
    assert "proposal_json" not in response.text
    assert TOKEN["X-Food-Assistant-Token"] not in response.text
    assert client.get("/quality").status_code == 200


@pytest.mark.parametrize(
    ("existing_quantity", "incoming_quantity", "expected_quantity"),
    [
        (12, 3, 15),
        (12, None, 12),
        (None, 3, 3),
        (None, None, None),
    ],
)
def test_shopping_merge_quantity_states(
    client_db, existing_quantity, incoming_quantity, expected_quantity
):
    client, _ = client_db
    base = {
        "owner": "household",
        "name": "鸡蛋",
        "quantity": existing_quantity,
        "unit": "个",
        "priority": "high",
        "source": "manual",
    }
    first = client.post("/api/v1/shopping-list", headers=TOKEN, json=base).json()
    incoming = {
        **base,
        "quantity": incoming_quantity,
        "priority": "low",
        "source": "recipe_missing",
    }
    merged = client.post("/api/v1/shopping-list", headers=TOKEN, json=incoming).json()
    assert merged["id"] == first["id"]
    assert merged["quantity"] == expected_quantity
    assert merged["priority"] == "high"
    assert merged["source"] == "manual"


def test_shopping_incompatible_units_do_not_merge(client_db):
    client, _ = client_db
    common = {
        "owner": "household",
        "name": "牛奶",
        "quantity": 1,
        "priority": "normal",
        "source": "manual",
    }
    first = client.post(
        "/api/v1/shopping-list", headers=TOKEN, json={**common, "unit": "盒"}
    ).json()
    second = client.post(
        "/api/v1/shopping-list", headers=TOKEN, json={**common, "unit": "升"}
    ).json()
    assert first["id"] != second["id"]
    assert len(
        client.get("/api/v1/shopping-list?owner=household", headers=TOKEN).json()
    ) == 2


def test_recipe_missing_does_not_clear_known_shopping_quantity(client_db):
    client, _ = client_db
    existing = client.post(
        "/api/v1/shopping-list",
        headers=TOKEN,
        json={
            "owner": "household",
            "name": "鸡蛋",
            "quantity": 12,
            "unit": None,
            "priority": "normal",
            "source": "manual",
        },
    ).json()
    response = client.post(
        "/api/v1/shopping-list/from-recipe",
        headers=TOKEN,
        json={
            "owner": "household",
            "mealie_slug": "tomato-eggs",
            "confirm_slug": "tomato-eggs",
            "selected_missing_ingredients": ["鸡蛋"],
        },
    )
    assert response.status_code == 200
    merged = response.json()["items"][0]
    assert merged["id"] == existing["id"]
    assert merged["quantity"] == 12
    assert merged["source"] == "manual"


def test_shopping_priority_and_stable_order(client_db):
    client, _ = client_db
    for name, priority in [
        ("低", "low"),
        ("普通一", "normal"),
        ("高", "high"),
        ("普通二", "normal"),
    ]:
        assert client.post(
            "/api/v1/shopping-list",
            headers=TOKEN,
            json={
                "owner": "household",
                "name": name,
                "quantity": None,
                "unit": None,
                "priority": priority,
                "source": "manual",
            },
        ).status_code == 201
    rows = client.get(
        "/api/v1/shopping-list?owner=household", headers=TOKEN
    ).json()
    assert [row["name"] for row in rows] == ["高", "普通一", "普通二", "低"]


def test_shopping_page_tabs_status_actions_and_empty_states():
    for status, label in (
        ("active", "待购买"),
        ("completed", "已完成"),
        ("dismissed", "已忽略"),
    ):
        assert f'id="tab-{status}"' in SHOPPING_HTML
        assert label in SHOPPING_HTML
    assert 'class="tab active-tab" aria-pressed="true"' in SHOPPING_HTML
    assert "let current='active'" in SHOPPING_HTML
    assert "classList.toggle('active-tab',selected)" in SHOPPING_HTML
    assert "setAttribute('aria-pressed',String(selected))" in SHOPPING_HTML
    assert "if(x.status==='active')return" in SHOPPING_HTML
    assert "永久删除" in SHOPPING_HTML
    assert "恢复到待购买" in SHOPPING_HTML
    assert "method:'DELETE'" in SHOPPING_HTML
    assert "?owner=household" in SHOPPING_HTML
    assert "确认永久删除该购物项吗？此操作不能撤销。" in SHOPPING_HTML
    assert "暂无待购买项目" in SHOPPING_HTML
    assert "暂无已完成项目" in SHOPPING_HTML
    assert "暂无已忽略项目" in SHOPPING_HTML
    assert "completed_at" in SHOPPING_HTML
    assert "dismissed_at" in SHOPPING_HTML
    active_branch = SHOPPING_HTML.split("if(x.status==='active')return", 1)[1].split(
        ";return", 1
    )[0]
    assert "deleteItem" not in active_branch


@pytest.mark.parametrize(
    "html",
    [
        PANTRY_HTML,
        RECOMMENDATIONS_HTML,
        COOKING_HTML,
        CONSUMPTION_HTML,
        SHOPPING_HTML,
        QUALITY_HTML,
    ],
)
def test_generated_page_javascript_passes_node_check(tmp_path, html):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = re.search(r"<script>(.*)</script>", html, re.DOTALL)
    assert script is not None
    script_path = tmp_path / "shopping.js"
    script_path.write_text(script.group(1), encoding="utf-8")
    result = subprocess.run(
        [node, "--check", str(script_path)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_all_pages_use_shared_navigation_token_and_feedback():
    pages = [
        PANTRY_HTML,
        RECOMMENDATIONS_HTML,
        COOKING_HTML,
        CONSUMPTION_HTML,
        SHOPPING_HTML,
        QUALITY_HTML,
    ]
    for html in pages:
        assert "foodAssistantApiToken" in html
        for path, label in [
            ("/cook", "厨房"),
            ("/pantry", "库存"),
            ("/recommendations", "推荐"),
            ("/consumption", "消耗确认"),
            ("/shopping", "购物清单"),
            ("/quality", "数据质量"),
        ]:
            assert path in html
            assert label in html
        assert 'id="error"' in html
        assert "success" in html
        assert "site-nav" in html
