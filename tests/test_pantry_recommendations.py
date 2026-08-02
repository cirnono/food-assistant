from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.api_auth import read_api_token
from app.database import Base
from app.ingredient_names import BUILTIN_ALIASES, alias_map
from app.main import app
from app.models import CookingHistory, IngredientAlias, PantryItem
from app.recommendations import build_recommendations


TOKEN = {"X-Food-Assistant-Token": "example-development-token-00000000"}


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/pantry.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def response(payload, url="http://mealie/api/recipes"):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


def test_quantity_staple_and_expiry_semantics(db, monkeypatch):
    today = date.today()
    db.add_all([
        PantryItem(name="番茄", quantity=None),
        PantryItem(name="盐", quantity=None, is_staple=True),
        PantryItem(name="土豆", quantity=0, is_staple=True),
        PantryItem(name="洋葱", quantity=2, expires_at=today - timedelta(days=1)),
    ])
    db.commit()

    async def fake_get(path, params=None):
        if path == "/api/recipes":
            return response({"items": [{"slug": "soup"}], "totalPages": 1})
        return response({"name": "汤", "slug": "soup", "recipeIngredient": [
            {"food": {"name": "西红柿"}}, {"food": {"name": "盐"}},
            {"food": {"name": "马铃薯"}}, {"food": {"name": "洋葱"}},
        ]}, f"http://mealie{path}")

    monkeypatch.setattr("app.recommendations.mealie_get", fake_get)
    result = asyncio.run(build_recommendations(db, limit=10, max_missing=10, max_total_time=None, category=None, cuisine=None, owner=None, use_expiring=True, randomize=False, seed=1))
    item = result["missing_one_or_two"][0]
    assert {x["ingredient"] for x in item["matched_ingredients"]} == {"西红柿", "盐"}
    assert set(item["missing_ingredients"]) == {"马铃薯", "洋葱"}


def test_user_alias_overrides_builtin(db):
    db.add(IngredientAlias(canonical_name="红果", alias="西红柿", normalized_alias="西红柿"))
    db.commit()
    assert alias_map(db)["西红柿"] == "红果"
    assert BUILTIN_ALIASES["西红柿"] == "番茄"


def test_ignore_water_process_tool_and_scoring(db, monkeypatch):
    db.add(PantryItem(name="鸡蛋", quantity=2, expires_at=date.today() + timedelta(days=2)))
    db.add(CookingHistory(mealie_slug="eggs", recipe_name="鸡蛋", cooked_at=date.today(), owner="household"))
    db.commit()

    async def fake_get(path, params=None):
        if path == "/api/recipes":
            return response({"items": [{"slug": "eggs"}], "total": 1})
        return response({"name": "鸡蛋", "slug": "eggs", "totalTime": 10, "recipeIngredient": [
            {"food": {"name": "鸡蛋"}}, {"food": {"name": "水"}},
            {"food": {"name": "炒锅"}}, {"display": "切碎", "extras": {"role": "process"}},
        ]}, f"http://mealie{path}")

    monkeypatch.setattr("app.recommendations.mealie_get", fake_get)
    result = asyncio.run(build_recommendations(db, limit=5, max_missing=0, max_total_time=20, category=None, cuisine=None, owner="household", use_expiring=True, randomize=False, seed=None))
    item = result["ready_now"][0]
    assert item["coverage_percent"] == 100
    assert item["score"] == 90
    assert any("临期" in reason for reason in item["score_reasons"])
    assert any("最近 7 天" in reason for reason in item["score_reasons"])


def test_pagination_and_concurrency_limit(db, monkeypatch):
    active = peak = 0

    async def fake_get(path, params=None):
        nonlocal active, peak
        if path == "/api/recipes":
            page = params["page"]
            return response({"items": [{"slug": f"r{page}-{i}"} for i in range(2)], "totalPages": 2})
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return response({"name": path, "recipeIngredient": []}, f"http://mealie{path}")

    monkeypatch.setattr("app.recommendations.PAGE_SIZE", 2)
    monkeypatch.setattr("app.recommendations.DETAIL_CONCURRENCY", 2)
    monkeypatch.setattr("app.recommendations.mealie_get", fake_get)
    result = asyncio.run(build_recommendations(db, limit=10, max_missing=0, max_total_time=None, category=None, cuisine=None, owner=None, use_expiring=True, randomize=False, seed=None))
    assert result["recipes_found"] == 4
    assert result["recipes_evaluated"] == 4
    assert peak <= 2


def test_max_missing_and_total_time(db, monkeypatch):
    async def fake_get(path, params=None):
        if path == "/api/recipes":
            return response({"items": [{"slug": "slow"}, {"slug": "missing"}], "total": 2})
        if path.endswith("slow"):
            return response({"name": "slow", "totalTime": 99, "recipeIngredient": []}, f"http://mealie{path}")
        return response({"name": "missing", "totalTime": 5, "recipeIngredient": [{"food": {"name": "稀有食材"}}]}, f"http://mealie{path}")
    monkeypatch.setattr("app.recommendations.mealie_get", fake_get)
    result = asyncio.run(build_recommendations(db, limit=5, max_missing=0, max_total_time=30, category=None, cuisine=None, owner=None, use_expiring=True, randomize=False, seed=None))
    assert result["recipes_evaluated"] == 0


def test_inventory_crud_actions_auth_and_pages():
    read_api_token.cache_clear()
    with TestClient(app) as client:
        assert client.get("/api/v1/inventory").status_code == 401
        created = client.post("/api/v1/inventory", headers=TOKEN, json={"name": "牛奶", "quantity": None, "location": "fridge"})
        assert created.status_code == 201
        item_id = created.json()["id"]
        assert client.post(f"/api/v1/inventory/{item_id}/consume", headers=TOKEN).json()["quantity"] == 0
        restocked = client.post(f"/api/v1/inventory/{item_id}/restock", headers=TOKEN, json={"quantity": 2, "unit": "盒"}).json()
        assert restocked["quantity"] == 2 and restocked["opened"] is False
        assert client.post(f"/api/v1/inventory/{item_id}/open", headers=TOKEN).json()["opened_at"] == date.today().isoformat()
        assert client.patch(f"/api/v1/inventory/{item_id}", headers=TOKEN, json={"low_stock_threshold": 3}).status_code == 200
        summary = client.get("/api/v1/inventory/summary", headers=TOKEN).json()
        assert {"available_items", "out_of_stock_items", "low_stock_items"} <= summary.keys()
        assert client.delete(f"/api/v1/inventory/{item_id}", headers=TOKEN).status_code == 204
        assert "库存管理" in client.get("/pantry").text
        assert "现在就能做" in client.get("/recommendations").text


def test_old_database_migration_is_idempotent(tmp_path, monkeypatch):
    import app.database as database
    old_engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with old_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE pantry_items (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, quantity FLOAT)")
        connection.exec_driver_sql("INSERT INTO pantry_items (name, quantity) VALUES ('米', NULL)")
    monkeypatch.setattr(database, "engine", old_engine)
    database.ensure_schema_migrations()
    database.ensure_schema_migrations()
    with old_engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(pantry_items)")}
        count = connection.scalar(select(func.count()).select_from(PantryItem))
    assert {"normalized_name", "opened_at", "mealie_food_id"} <= columns
    assert count == 1
