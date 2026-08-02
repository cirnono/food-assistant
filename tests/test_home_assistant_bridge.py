from __future__ import annotations

from collections.abc import Generator

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.home_assistant as bridge
from app.api_auth import read_api_token
from app.database import Base, get_db
from app.main import app
from app.models import CookingHistory, HomeAssistantSelection


TOKEN = {"X-Food-Assistant-Token": "example-development-token-00000000"}


def recipe(slug: str) -> dict:
    return {
        "name": slug.upper(),
        "slug": slug,
        "score": 90.0,
        "coverage_percent": 90.0,
        "missing_ingredients": [],
        "expiring_inventory_matches": [],
        "score_reasons": ["库存覆盖 90.0%"],
        "total_time_minutes": 15,
        "category": "主菜",
        "cuisine": None,
        "mealie_url": f"http://mealie.example/g/home/r/{slug}",
    }


def result(slugs=("a", "b", "c")) -> dict:
    rows = [recipe(slug) for slug in slugs]
    return {
        "ready_now": rows,
        "missing_one_or_two": rows,
        "use_soon": rows,
        "random_pick": rows,
    }


@pytest.fixture()
def bridge_client(tmp_path, monkeypatch) -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/ha.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)

    def override_db():
        yield session

    async def fake_recommendations(*args, **kwargs):
        return result()

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(bridge, "build_recommendations", fake_recommendations)
    read_api_token.cache_clear()
    with TestClient(app) as client:
        yield client, session
    app.dependency_overrides.clear()
    session.close()


def test_state_requires_auth_and_is_stable_without_secret_leak(bridge_client):
    client, session = bridge_client
    assert client.get("/api/v1/home-assistant/state").status_code == 401
    first = client.get("/api/v1/home-assistant/state", headers=TOKEN)
    second = client.get("/api/v1/home-assistant/state", headers=TOKEN)
    assert first.status_code == second.status_code == 200
    assert first.json()["selected_recipe"]["slug"] == "a"
    assert second.json()["selected_recipe"]["slug"] == "a"
    assert "example-development-token" not in second.text
    assert session.scalar(select(func.count()).select_from(HomeAssistantSelection)) == 1


def test_next_avoids_repeat_and_owners_are_independent(bridge_client):
    client, session = bridge_client
    client.get("/api/v1/home-assistant/state", headers=TOKEN)
    payload = {
        "owner": "household",
        "mode": "ready_now",
        "max_missing": 2,
        "confirm_owner": "household",
    }
    changed = client.post(
        "/api/v1/home-assistant/selection/next",
        headers=TOKEN,
        json=payload,
    )
    assert changed.status_code == 200
    assert changed.json()["selected_recipe"]["slug"] != "a"
    other = client.get(
        "/api/v1/home-assistant/state?owner=guest",
        headers=TOKEN,
    )
    assert other.status_code == 200
    owners = set(session.scalars(select(HomeAssistantSelection.owner)).all())
    assert owners == {"household", "guest"}
    payload["confirm_owner"] = "guest"
    assert client.post(
        "/api/v1/home-assistant/selection/next",
        headers=TOKEN,
        json=payload,
    ).status_code == 409


def test_empty_group_returns_409(bridge_client, monkeypatch):
    client, _ = bridge_client

    async def empty(*args, **kwargs):
        return result(())

    monkeypatch.setattr(bridge, "build_recommendations", empty)
    response = client.post(
        "/api/v1/home-assistant/selection/next",
        headers=TOKEN,
        json={
            "owner": "household",
            "mode": "ready_now",
            "confirm_owner": "household",
        },
    )
    assert response.status_code == 409
    assert "No recipe candidates" in response.json()["detail"]


def test_mark_cooked_confirmation_idempotency_and_select_next(bridge_client):
    client, session = bridge_client
    client.get("/api/v1/home-assistant/state", headers=TOKEN)
    endpoint = "/api/v1/home-assistant/selection/mark-cooked"
    bad = client.post(endpoint, headers=TOKEN, json={
        "owner": "household",
        "confirm_slug": "wrong",
    })
    assert bad.status_code == 409
    payload = {
        "owner": "household",
        "confirm_slug": "a",
        "select_next": False,
    }
    assert client.post(endpoint, headers=TOKEN, json=payload).status_code == 200
    assert client.post(endpoint, headers=TOKEN, json=payload).status_code == 200
    assert session.scalar(select(func.count()).select_from(CookingHistory)) == 1
    payload["select_next"] = True
    changed = client.post(endpoint, headers=TOKEN, json=payload)
    assert changed.status_code == 200
    assert changed.json()["selected_recipe"]["slug"] != "a"
    assert session.scalar(select(func.count()).select_from(CookingHistory)) == 1


def test_missing_selected_recipe_recovers(bridge_client, monkeypatch):
    client, _ = bridge_client
    first = client.get("/api/v1/home-assistant/state", headers=TOKEN)
    assert first.json()["selected_recipe"]["slug"] == "a"

    async def without_a(*args, **kwargs):
        return result(("b", "c"))

    monkeypatch.setattr(bridge, "build_recommendations", without_a)
    recovered = client.get("/api/v1/home-assistant/state", headers=TOKEN)
    assert recovered.json()["selected_recipe"]["slug"] == "b"


def test_refresh_cache_is_opt_in(bridge_client, monkeypatch):
    client, _ = bridge_client
    clears = 0

    async def clear():
        nonlocal clears
        clears += 1

    monkeypatch.setattr(bridge, "clear_recipe_detail_cache", clear)
    endpoint = "/api/v1/home-assistant/refresh"
    assert client.post(endpoint, headers=TOKEN, json={"owner": "household"}).status_code == 200
    assert clears == 0
    assert client.post(endpoint, headers=TOKEN, json={
        "owner": "household",
        "refresh_recipe_cache": True,
    }).status_code == 200
    assert clears == 1


class SecretLoader(yaml.SafeLoader):
    pass


SecretLoader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))


def test_home_assistant_yaml_examples_parse_and_contain_no_credentials():
    paths = [
        "integrations/home-assistant/food_assistant_package.yaml.example",
        "integrations/home-assistant/lovelace-kitchen.yaml.example",
    ]
    for path in paths:
        text = open(path, encoding="utf-8").read()
        assert yaml.load(text, Loader=SecretLoader)
        assert "192.168." not in text
        assert "10.0." not in text
        assert "X-Food-Assistant-Token" not in text
        assert "example-development-token" not in text


def test_selection_tables_are_added_without_touching_old_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE pantry_items (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO pantry_items (name) VALUES ('米')")
    Base.metadata.create_all(engine)
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        tables = {row[0] for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        count = connection.exec_driver_sql("SELECT COUNT(*) FROM pantry_items").scalar_one()
    assert "home_assistant_selections" in tables
    assert "home_assistant_selection_history" in tables
    assert count == 1
