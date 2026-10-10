"""HTTP-level task isolation, including unknown/unowned tasks and administrator accounts."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from easy_tdx.web.account_store import UserRecord
from easy_tdx.web.errors import register_exception_handlers
from easy_tdx.web.routers import backtest
from easy_tdx.web.routers.auth import get_current_user
from easy_tdx.web.task_runner import BacktestTaskRunner


@pytest.fixture
def task_app(monkeypatch):
    runner = BacktestTaskRunner(max_workers=1)
    monkeypatch.setattr(backtest, "get_runner", lambda: runner)
    actor = {"user": None}

    def identity():
        if actor["user"] is None:
            raise HTTPException(401, "请先登录")
        return actor["user"]

    app = FastAPI()
    register_exception_handlers(app)
    app.state.tdx_client = None
    app.state.mac_client = None
    app.include_router(backtest.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = identity
    with TestClient(app) as client:
        yield client, runner, actor
    runner.shutdown()


def test_tasks_require_login_and_never_disclose_foreign_or_unowned_tasks(task_app):
    client, runner, actor = task_app
    a = runner.submit(lambda: {"secret": "alice"}, owner_id="alice")
    b = runner.submit(lambda: {"secret": "bob"}, owner_id="bob")
    unowned = runner.submit(lambda: {"secret": "legacy"})
    assert client.get("/api/v1/backtest/tasks").status_code == 401
    assert client.get(f"/api/v1/backtest/tasks/{a}").status_code == 401
    actor["user"] = UserRecord(id="alice", username="Alice")
    assert [r["task_id"] for r in client.get("/api/v1/backtest/tasks").json()["tasks"]] == [a]
    assert client.get(f"/api/v1/backtest/tasks/{a}").status_code == 200
    foreign = client.get(f"/api/v1/backtest/tasks/{b}")
    absent = client.get("/api/v1/backtest/tasks/does-not-exist")
    assert foreign.status_code == absent.status_code == 404
    assert foreign.json() == absent.json()
    assert client.get(f"/api/v1/backtest/tasks/{unowned}").status_code == 404
    # Account administration does not grant access to other users' strategies/results.
    actor["user"] = UserRecord(id="admin", username="Admin", role="admin")
    assert client.get("/api/v1/backtest/tasks").json()["tasks"] == []
    assert client.get(f"/api/v1/backtest/tasks/{a}").status_code == 404


def test_submission_captures_owner_and_list_limits_are_bounded(task_app, monkeypatch):
    client, runner, actor = task_app
    actor["user"] = UserRecord(id="alice", username="Alice")
    monkeypatch.setattr(backtest, "_run_backtest", lambda *_: {"ok": True})
    bar = dict(open=10, high=11, low=9, close=10, vol=100, amount=1000)
    response = client.post(
        "/api/v1/backtest/run/async",
        json={
            "strategy": "ma_cross",
            "ohlcv": [dict(bar, datetime="2026-09-01"), dict(bar, datetime="2026-09-02")],
        },
    )
    assert response.status_code == 202
    task = runner.get(response.json()["task_id"])
    assert task.owner_id == "alice"
    for limit in (0, -1, 101):
        assert client.get(f"/api/v1/backtest/tasks?limit={limit}").status_code == 422
    actor["user"] = UserRecord(id="bob", username="Bob")
    assert client.get("/api/v1/backtest/tasks?limit=1").json()["count"] == 0


@pytest.mark.parametrize(
    "endpoint",
    [
        "run",
        "portfolio/run",
        "multi-strategy/run",
        "optimize/run",
        "optimize-all/run",
        "signal-scan/run",
    ],
)
def test_every_background_submission_requires_identity(task_app, endpoint):
    client, _, _ = task_app
    response = client.post(f"/api/v1/backtest/{endpoint}/async", json={})
    assert response.status_code == 401


def test_cancel_is_owner_only_and_idempotent(task_app, monkeypatch):
    from threading import Event

    client, runner, actor = task_app
    release = Event()
    audits = []

    class AuditStore:
        def audit_operation(self, *args, **kwargs):
            audits.append((args, kwargs))

    monkeypatch.setattr(backtest, "get_account_store", lambda: AuditStore())
    try:
        runner.submit(lambda: release.wait(3) or {})
        own = runner.submit(lambda: {}, owner_id="alice")
        foreign = runner.submit(lambda: {}, owner_id="bob")
        assert client.post(f"/api/v1/backtest/tasks/{own}/cancel").status_code == 401
        actor["user"] = UserRecord(id="alice", username="Alice")
        missing = client.post("/api/v1/backtest/tasks/missing/cancel")
        denied = client.post(f"/api/v1/backtest/tasks/{foreign}/cancel")
        assert missing.status_code == denied.status_code == 404
        assert missing.json() == denied.json()
        response = client.post(f"/api/v1/backtest/tasks/{own}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert response.json()["result"] is None
        assert client.post(f"/api/v1/backtest/tasks/{own}/cancel").json()["status"] == "cancelled"
        assert len(audits) == 1
        actor["user"] = UserRecord(id="admin", username="Admin", role="admin")
        assert client.post(f"/api/v1/backtest/tasks/{foreign}/cancel").status_code == 404
        assert runner.get(foreign).status == "pending"
    finally:
        release.set()


def test_submission_capacity_returns_retryable_429(task_app):
    from threading import Event

    client, runner, actor = task_app
    release = Event()
    actor["user"] = UserRecord(id="alice", username="Alice")
    try:
        for _ in range(3):
            runner.submit(lambda: release.wait(3) or {}, owner_id="alice")
        bar = dict(open=10, high=11, low=9, close=10, vol=100, amount=1000)
        response = client.post(
            "/api/v1/backtest/run/async",
            json={
                "strategy": "ma_cross",
                "ohlcv": [dict(bar, datetime="2026-09-01"), dict(bar, datetime="2026-09-02")],
            },
        )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
        assert len(runner.list_recent(100)) == 3
    finally:
        release.set()
