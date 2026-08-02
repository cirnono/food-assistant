from __future__ import annotations

import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.cooking_sessions as cooking
import app.home_assistant as bridge
from app.api_auth import read_api_token
from app.database import Base, get_db
from app.main import app
from app.models import (
    CookingHistory,
    CookingSession,
    CookingTimer,
    HomeAssistantSelection,
)


TOKEN = {"X-Food-Assistant-Token": "example-development-token-00000000"}


def recipe(slug: str = "tomato-eggs") -> dict:
    return {
        "name": "番茄炒蛋",
        "slug": slug,
        "recipeIngredient": [
            {"food": {"name": "鸡蛋"}, "quantity": 2, "unit": {"name": "个"}},
            {"display": "番茄 2 个", "food": {"name": "番茄"}, "note": "切块"},
        ],
        "recipeInstructions": [
            {"title": "准备", "text": "鸡蛋打散，番茄切块。"},
            {"text": "炒熟鸡蛋后加入番茄。"},
        ],
        "totalTime": 15,
        "recipeCategory": {"name": "主菜"},
        "recipeCuisine": "中餐",
    }


@pytest.fixture()
def cooking_client(tmp_path, monkeypatch) -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/cooking.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)

    def override_db():
        yield session

    async def fake_detail(slug: str):
        return recipe(slug), None

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(cooking, "get_recipe_detail_cached", fake_detail)
    read_api_token.cache_clear()
    with TestClient(app) as client:
        yield client, session
    app.dependency_overrides.clear()
    session.close()


def start(client: TestClient, owner: str = "household", slug: str = "tomato-eggs"):
    return client.post(
        "/api/v1/cooking-sessions/start",
        headers=TOKEN,
        json={"owner": owner, "mealie_slug": slug, "confirm_slug": slug},
    )


def action(client: TestClient, session_id: int, name: str, **extra):
    return client.post(
        f"/api/v1/cooking-sessions/{session_id}/{name}",
        headers=TOKEN,
        json={"owner": "household", "confirm_session_id": session_id, **extra},
    )


def test_start_confirmation_active_limit_owners_and_snapshot(cooking_client, monkeypatch):
    client, session = cooking_client
    assert client.post("/api/v1/cooking-sessions/start", headers=TOKEN, json={
        "owner": "household", "mealie_slug": "a", "confirm_slug": "b",
    }).status_code == 409
    response = start(client)
    assert response.status_code == 201
    payload = response.json()
    assert payload["recipe"]["ingredients"][0]["name"] == "鸡蛋"
    assert payload["recipe"]["instructions"][0]["title"] == "准备"
    assert start(client).status_code == 409
    assert start(client, owner="guest", slug="other").status_code == 201

    async def changed(slug: str):
        return {**recipe(slug), "name": "上游已修改"}, None

    monkeypatch.setattr(cooking, "get_recipe_detail_cached", changed)
    stored = client.get(
        f"/api/v1/cooking-sessions/{payload['id']}?owner=household", headers=TOKEN
    )
    assert stored.json()["recipe_name"] == "番茄炒蛋"
    assert session.scalar(select(func.count()).select_from(CookingSession)) == 2


def test_start_from_selection_and_reject_recipe_without_steps(cooking_client, monkeypatch):
    client, session = cooking_client
    session.add(HomeAssistantSelection(
        owner="household",
        mode="ready_now",
        selected_slug="selected",
        selected_name="Selected",
        selected_payload_json="{}",
        filters_json="{}",
    ))
    session.commit()
    response = client.post("/api/v1/cooking-sessions/start", headers=TOKEN, json={
        "owner": "household", "mealie_slug": None, "confirm_slug": "selected",
    })
    assert response.status_code == 201
    action(client, response.json()["id"], "cancel")

    async def no_steps(slug: str):
        return {"name": slug, "ingredients": [], "instructions": []}, None

    monkeypatch.setattr(cooking, "get_recipe_detail_cached", no_steps)
    assert start(client, slug="empty").status_code == 422


def test_snapshot_supports_compatibility_field_names():
    snapshot = cooking.build_recipe_snapshot({
        "name": "兼容菜谱",
        "ingredients": ["盐", {"name": "水", "quantityValue": 1, "unit": "杯"}],
        "instructions": ["混合", {"name": "完成", "summary": "装盘"}],
        "total_time_minutes": 5,
    }, "compat")
    assert [item["text"] for item in snapshot["instructions"]] == ["混合", "装盘"]
    assert snapshot["ingredients"][0]["display"] == "盐"
    assert snapshot["ingredients"][1]["unit"] == "杯"


def test_steps_and_checked_ingredients_are_bounded_and_persistent(cooking_client):
    client, _ = cooking_client
    row = start(client).json()
    session_id = row["id"]
    assert action(client, session_id, "previous-step").status_code == 422
    assert action(client, session_id, "next-step").json()["current_step_index"] == 1
    assert action(client, session_id, "next-step").status_code == 422
    assert action(client, session_id, "set-step", step_index=0).status_code == 200
    toggled = action(client, session_id, "toggle-ingredient", ingredient_index=1)
    assert toggled.json()["checked_ingredient_indexes"] == [1]
    assert action(client, session_id, "toggle-ingredient", ingredient_index=9).status_code == 422
    restored = client.get(
        f"/api/v1/cooking-sessions/{session_id}?owner=household", headers=TOKEN
    )
    assert restored.json()["checked_ingredient_indexes"] == [1]


def test_finish_writes_history_once_cancel_does_not_and_inventory_is_read_only(cooking_client):
    client, session = cooking_client
    session_id = start(client).json()["id"]
    timer = client.post(
        f"/api/v1/cooking-sessions/{session_id}/timers", headers=TOKEN,
        json={"owner": "household", "confirm_session_id": session_id,
              "label": "完成前计时", "duration_seconds": 60},
    ).json()
    finished = action(client, session_id, "finish", select_next=False)
    assert finished.status_code == 200
    assert finished.json()["status"] == "completed"
    assert all(
        item["requires_manual_confirmation"]
        for item in finished.json()["inventory_consumption_preview"]
    )
    assert action(client, session_id, "finish", select_next=False).status_code == 409
    assert session.scalar(select(func.count()).select_from(CookingHistory)) == 1
    assert session.get(CookingTimer, timer["id"]).state == "finished"


def test_finish_select_next_reuses_home_assistant_service(cooking_client, monkeypatch):
    client, session = cooking_client
    session_id = start(client).json()["id"]
    session.add(HomeAssistantSelection(
        owner="household", mode="ready_now", selected_slug="tomato-eggs",
        selected_name="番茄炒蛋", selected_payload_json="{}",
        filters_json=json.dumps({"owner": "household", "mode": "ready_now",
                                 "max_missing": 2, "max_total_time": None,
                                 "category": None, "cuisine": None}),
    ))
    session.commit()
    called = 0

    async def fake_next(db, filters, *, commit=True):
        nonlocal called
        called += 1
        return session.scalar(select(HomeAssistantSelection))

    monkeypatch.setattr(cooking, "select_next_for_owner", fake_next)
    assert action(client, session_id, "finish", select_next=True).status_code == 200
    assert called == 1
    other = start(client, slug="second").json()
    assert action(client, other["id"], "cancel").json()["status"] == "cancelled"
    assert session.scalar(select(func.count()).select_from(CookingHistory)) == 1


def test_timer_deadline_pause_resume_overdue_and_terminal_states(cooking_client, monkeypatch):
    client, session = cooking_client
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(cooking, "clock_now", lambda: now)
    session_id = start(client).json()["id"]
    endpoint = f"/api/v1/cooking-sessions/{session_id}/timers"
    created = client.post(endpoint, headers=TOKEN, json={
        "owner": "household", "confirm_session_id": session_id,
        "label": "焖煮", "duration_seconds": 480, "start_immediately": True,
    })
    assert created.status_code == 201
    timer_id = created.json()["id"]
    assert created.json()["deadline_at"].endswith("+00:00")

    now += timedelta(seconds=125)
    paused = client.post(f"{endpoint}/{timer_id}/pause", headers=TOKEN, json={
        "owner": "household", "confirm_session_id": session_id,
    })
    assert paused.json()["remaining_seconds"] == 355
    resumed = client.post(f"{endpoint}/{timer_id}/resume", headers=TOKEN, json={
        "owner": "household", "confirm_session_id": session_id,
    })
    assert resumed.json()["state"] == "running"
    now += timedelta(seconds=356)
    state = client.get(
        "/api/v1/cooking-sessions/active-state?owner=household", headers=TOKEN
    )
    assert state.json()["timers"][0]["state"] == "finished"
    assert client.post(f"{endpoint}/{timer_id}/resume", headers=TOKEN, json={
        "owner": "household", "confirm_session_id": session_id,
    }).status_code == 409
    assert session.get(CookingTimer, timer_id).finished_at is not None
    assert client.delete(
        f"{endpoint}/{timer_id}?owner=household&confirm_session_id={session_id}",
        headers=TOKEN,
    ).status_code == 204

    cancelled = client.post(endpoint, headers=TOKEN, json={
        "owner": "household", "confirm_session_id": session_id,
        "label": "取消", "duration_seconds": 30, "start_immediately": False,
    }).json()
    assert client.post(f"{endpoint}/{cancelled['id']}/cancel", headers=TOKEN, json={
        "owner": "household", "confirm_session_id": session_id,
    }).status_code == 200
    assert client.post(f"{endpoint}/{cancelled['id']}/resume", headers=TOKEN, json={
        "owner": "household", "confirm_session_id": session_id,
    }).status_code == 409


def test_timer_limit_and_active_state_is_local_and_authenticated(cooking_client, monkeypatch):
    client, _ = cooking_client
    assert client.get("/api/v1/cooking-sessions/active-state").status_code == 401
    session_id = start(client).json()["id"]

    async def external_call_forbidden(*args, **kwargs):
        raise AssertionError("active-state must remain local")

    monkeypatch.setattr(cooking, "get_recipe_detail_cached", external_call_forbidden)
    monkeypatch.setattr(bridge, "build_recommendations", external_call_forbidden)
    for number in range(8):
        response = client.post(
            f"/api/v1/cooking-sessions/{session_id}/timers",
            headers=TOKEN,
            json={
                "owner": "household", "confirm_session_id": session_id,
                "label": f"timer {number}", "duration_seconds": 60,
                "start_immediately": False,
            },
        )
        assert response.status_code == 201
    assert client.post(
        f"/api/v1/cooking-sessions/{session_id}/timers", headers=TOKEN,
        json={"owner": "household", "confirm_session_id": session_id,
              "label": "extra", "duration_seconds": 60},
    ).status_code == 409
    state = client.get(
        "/api/v1/cooking-sessions/active-state?owner=household", headers=TOKEN
    )
    assert state.status_code == 200
    assert state.json()["status"] == "active"
    assert "example-development-token" not in state.text


def test_partial_unique_index_and_old_database_migration(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE pantry_items (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO pantry_items (name) VALUES ('米')")
    Base.metadata.create_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        snapshot = json.dumps({"ingredients": [], "instructions": [{"text": "cook"}]})
        session.add(CookingSession(
            owner="household", mealie_slug="a", recipe_name="A",
            recipe_snapshot_json=snapshot, status="active",
        ))
        session.commit()
        session.add(CookingSession(
            owner="household", mealie_slug="b", recipe_name="B",
            recipe_snapshot_json=snapshot, status="active",
        ))
        with pytest.raises(IntegrityError):
            session.commit()
    with engine.connect() as connection:
        tables = {row[0] for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        count = connection.exec_driver_sql("SELECT COUNT(*) FROM pantry_items").scalar_one()
    assert {"cooking_sessions", "cooking_timers"} <= tables
    assert count == 1


def test_cook_page_uses_shared_token_storage_and_has_confirmations(cooking_client):
    client, _ = cooking_client
    response = client.get("/cook")
    assert response.status_code == 200
    assert "foodAssistantApiToken" in response.text
    assert "确认完成烹饪" in response.text
    assert "确认取消本次烹饪" in response.text
