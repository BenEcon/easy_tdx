"""Expected UI owner must match the authenticated cookie before dispatching work."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.deps import get_client, get_mac_client_optional


@pytest.fixture
def session(tmp_path, monkeypatch):
    from easy_tdx.web import account_store, task_service
    from easy_tdx.web.routers.auth import router as auth
    from easy_tdx.web.routers.backtest import router

    monkeypatch.setattr(account_store, "_store", AccountStore(tmp_path / "accounts.db"))
    monkeypatch.setattr(task_service, "task_backend", lambda: "memory")
    app = FastAPI()
    app.dependency_overrides[get_client] = lambda: object()
    app.dependency_overrides[get_mac_client_optional] = lambda: None
    app.include_router(auth, prefix="/api/v1")
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        owner = client.post(
            "/api/v1/auth/setup",
            json={
                "username": "owner",
                "password": "local-test-owner-pass",
            },
        ).json()["user"]["id"]
        yield client, owner


CASES = [
    ("POST", "/run", {"strategy": "ma_cross", "symbol": "SZ:300450"}),
    ("GET", "/tasks", None),
    ("GET", "/tasks/foreign", None),
    ("GET", "/tasks/foreign/portfolio-evidence", None),
    ("POST", "/tasks/foreign/cancel", None),
    ("DELETE", "/tasks/foreign", None),
    ("POST", "/run/async", {"strategy": "ma_cross", "symbol": "SZ:300450"}),
    ("POST", "/portfolio/run/async", {"strategy": "ma_cross", "stocks": ["SZ:300450"]}),
    (
        "POST",
        "/multi-strategy/run/async",
        {"items": [{"strategy": "ma_cross", "symbol": "SZ:300450"}]},
    ),
    (
        "POST",
        "/optimize/run/async",
        {"strategy": "ma_cross", "symbol": "SZ:300450", "param_grid": {"fast": [5]}},
    ),
    ("POST", "/optimize-all/run/async", {"symbol": "SZ:300450"}),
    ("POST", "/signal-scan/run/async", {}),
]


@pytest.mark.parametrize("method,path,body", CASES)
def test_changed_cookie_rejects_old_owner_before_work(session, method, path, body):
    client, owner = session
    other = client.post(
        "/api/v1/admin/users",
        json={
            "username": "other",
            "password": "local-test-other-pass",
            "role": "user",
        },
    ).json()["user"]["id"]
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/login", json={"username": "other", "password": "local-test-other-pass"}
    )
    response = client.request(
        method, f"/api/v1/backtest{path}", json=body, headers={"X-Task-Owner": owner}
    )
    assert response.status_code == 409
    assert "账户已变化" in response.json()["detail"]
    assert (
        client.get("/api/v1/backtest/tasks", headers={"X-Task-Owner": other}).json()["tasks"] == []
    )


def test_matching_owner_legacy_and_anonymous_access(session):
    client, owner = session
    for headers in [{}, {"X-Task-Owner": owner}]:
        assert client.get("/api/v1/backtest/tasks", headers=headers).status_code == 200
        assert client.get("/api/v1/backtest/tasks/missing", headers=headers).status_code == 404
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/backtest/tasks", headers={"X-Task-Owner": owner}).status_code == 401
