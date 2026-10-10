"""A strategy request remains bound to its expected account across cookie changes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.errors import register_exception_handlers
from easy_tdx.web.strategy_store import StrategyStore


@pytest.fixture
def session(tmp_path, monkeypatch):
    from easy_tdx.web import account_store, strategy_store
    from easy_tdx.web.routers.auth import router as auth
    from easy_tdx.web.routers.strategies import router

    monkeypatch.setattr(account_store, "_store", AccountStore(tmp_path / "accounts.db"))
    monkeypatch.setattr(strategy_store, "_store", StrategyStore(tmp_path / "strategies.db"))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth, prefix="/api/v1")
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        owner = client.post(
            "/api/v1/auth/setup",
            json={"username": "owner", "password": "owner-test-password"},
        ).json()["user"]["id"]
        yield client, owner


def payload():
    return {
        "name": "Saved context",
        "kind": "single",
        "strategy": "ma_cross",
        "params": {"fast": 7, "slow": 31},
        "context": {"symbol": "SH:510300", "category": "MIN_30", "adjust": "NONE"},
        "trade_config": {"cash": 500, "min_commission": 1.23, "stamp_tax": 0},
    }


def test_matching_owner_preserves_context_and_legacy_reads(session):
    client, owner = session
    headers = {"X-Strategy-Owner": owner}
    response = client.post("/api/v1/strategies", json=payload(), headers=headers)
    assert response.status_code == 201
    url = f"/api/v1/strategies/{response.json()['id']}"
    for requested_headers in [headers, {}]:
        saved = client.get(url, headers=requested_headers)
        assert saved.status_code == 200
        for key in ["context", "trade_config", "params"]:
            assert saved.json()[key] == payload()[key]
    updated = {**payload(), "name": "Updated"}
    assert client.put(url, json=updated, headers=headers).json()["name"] == "Updated"


@pytest.mark.parametrize("method", ["get", "post", "put", "delete", "list"])
def test_cookie_account_change_rejects_old_owner_without_mutation(session, method):
    client, owner = session
    saved = client.post("/api/v1/strategies", json=payload()).json()
    client.post(
        "/api/v1/admin/users",
        json={
            "username": "other",
            "password": "other-test-password",
            "role": "user",
        },
    )
    client.post("/api/v1/auth/logout")
    other = client.post(
        "/api/v1/auth/login",
        json={
            "username": "other",
            "password": "other-test-password",
        },
    ).json()["user"]["id"]
    url = "/api/v1/strategies" + (f"/{saved['id']}" if method in {"get", "put", "delete"} else "")
    response = client.request(
        "get" if method == "list" else method,
        url,
        headers={"X-Strategy-Owner": owner},
        **({"json": payload()} if method in {"post", "put"} else {}),
    )
    assert response.status_code == 409
    assert (
        client.get("/api/v1/strategies", headers={"X-Strategy-Owner": other}).json()["count"] == 0
    )
    assert (
        client.get(
            f"/api/v1/strategies/{saved['id']}", headers={"X-Strategy-Owner": other}
        ).status_code
        == 400
    )
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"username": "owner", "password": "owner-test-password"})
    assert client.get(f"/api/v1/strategies/{saved['id']}").json() == saved


def test_owner_header_does_not_authenticate_anonymous_client(session):
    client, owner = session
    client.post("/api/v1/auth/logout")
    assert (
        client.post(
            "/api/v1/strategies", json=payload(), headers={"X-Strategy-Owner": owner}
        ).status_code
        == 401
    )
