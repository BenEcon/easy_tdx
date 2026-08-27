"""账户认证、管理员权限和会话隔离测试（离线 SQLite）。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.errors import register_exception_handlers
from easy_tdx.web.strategy_store import StrategyStore


def _client(tmp_path, monkeypatch) -> TestClient:
    from easy_tdx.web import account_store as accounts_mod
    from easy_tdx.web import strategy_store as strategies_mod
    from easy_tdx.web.routers.auth import router
    from easy_tdx.web.routers.strategies import router as strategies_router

    monkeypatch.setattr(accounts_mod, "_store", AccountStore(tmp_path / "accounts.db"))
    monkeypatch.setattr(strategies_mod, "_store", StrategyStore(tmp_path / "strategies.db"))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.include_router(strategies_router, prefix="/api/v1")
    return TestClient(app)


def test_first_user_setup_becomes_admin_and_can_manage_users(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    status = client.get("/api/v1/auth/status").json()
    assert status == {"setup_required": True, "authenticated": False, "user": None}

    created = client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "safe-password-123"},
    )
    assert created.status_code == 201
    assert created.json()["user"]["role"] == "admin"
    assert "easy_tdx_session" in client.cookies

    member = client.post(
        "/api/v1/admin/users",
        json={"username": "member", "password": "member-password", "role": "user"},
    )
    assert member.status_code == 201
    listing = client.get("/api/v1/admin/users").json()
    assert listing["count"] == 2
    assert {user["username"] for user in listing["users"]} == {"admin", "member"}


def test_login_logout_and_disabled_account(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "safe-password-123"},
    )
    member = client.post(
        "/api/v1/admin/users",
        json={"username": "member", "password": "member-password", "role": "user"},
    ).json()["user"]
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401

    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "member", "password": "member-password"}
        ).status_code
        == 200
    )
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "safe-password-123"})
    assert (
        client.patch(f"/api/v1/admin/users/{member['id']}", json={"active": False}).status_code
        == 200
    )
    client.post("/api/v1/auth/logout")
    denied = client.post(
        "/api/v1/auth/login", json={"username": "member", "password": "member-password"}
    )
    assert denied.status_code == 401


def test_standard_user_cannot_access_admin_api(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/v1/auth/setup", json={"username": "admin", "password": "safe-password-123"})
    client.post(
        "/api/v1/admin/users",
        json={"username": "member", "password": "member-password", "role": "user"},
    )
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"username": "member", "password": "member-password"})
    assert client.get("/api/v1/admin/users").status_code == 403


def test_preferences_persist_per_user(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/v1/auth/setup", json={"username": "admin", "password": "safe-password-123"})
    response = client.put(
        "/api/v1/auth/me/preferences",
        json={"preferences": {"sidebar_collapsed": True, "indicator": "MACD"}},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me").json()["user"]["preferences"] == {
        "sidebar_collapsed": True,
        "indicator": "MACD",
    }


def test_saved_strategies_are_isolated_between_accounts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/v1/auth/setup", json={"username": "admin", "password": "safe-password-123"})
    member = client.post(
        "/api/v1/admin/users",
        json={"username": "member", "password": "member-password", "role": "user"},
    ).json()["user"]
    strategy = client.post(
        "/api/v1/strategies",
        json={
            "name": "管理员策略",
            "kind": "single",
            "strategy": "ma_cross",
            "context": {"symbol": "SZ:000001"},
        },
    )
    assert strategy.status_code == 201
    strategy_id = strategy.json()["id"]

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"username": "member", "password": "member-password"})
    assert client.get("/api/v1/strategies").json()["count"] == 0
    assert client.get(f"/api/v1/strategies/{strategy_id}").status_code == 400

    member_strategy = client.post(
        "/api/v1/strategies",
        json={"name": "用户策略", "kind": "single", "strategy": "rsi_reversal"},
    )
    assert member_strategy.status_code == 201
    assert member_strategy.json()["id"] != strategy_id

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "safe-password-123"})
    listing = client.get("/api/v1/strategies").json()
    assert [item["id"] for item in listing["strategies"]] == [strategy_id]
    assert member["saved_strategy_count"] == 0
