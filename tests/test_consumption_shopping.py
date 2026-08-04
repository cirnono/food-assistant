from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.cooking_sessions as cooking
import app.shopping as shopping
from app.api_auth import read_api_token
from app.consumption import build_consumption_proposal
from app.database import Base, get_db
from app.main import app
from app.models import (
    ConsumptionReview,
    InventoryAdjustment,
    PantryItem,
    ShoppingListItem,
)


TOKEN = {"X-Food-Assistant-Token": "example-development-token-00000000"}


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
