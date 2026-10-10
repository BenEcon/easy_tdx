"""Real authenticated HTTP + frozen queue + actual independent calculation."""

import sqlite3
import sys
import time
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.web import task_service
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.errors import register_exception_handlers
from easy_tdx.web.routers import auth, backtest
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_store import TaskStore
from easy_tdx.web.task_supervisor import TaskSupervisor
from easy_tdx.web.task_version import execution_version


def app():
    value = FastAPI()
    value.state.tdx_client = None
    value.state.mac_client = None
    register_exception_handlers(value)
    value.include_router(auth.router, prefix="/api/v1")
    value.include_router(backtest.router, prefix="/api/v1")
    return value


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setenv("EASY_TDX_TASK_BACKEND", "durable")
    accounts = get_account_store()
    users = [
        accounts.create_user(name, "TestOnly-password-20261009", role)
        for name, role in [("alice", "user"), ("bob", "user"), ("admin", "admin")]
    ]
    with TestClient(app()) as client:
        client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(users[0].id))
        yield client, accounts, users


@pytest.fixture
def records():
    return [
        dict(datetime=str(day.date()), open=30, high=32, low=29, close=31, vol=10000, amount=310000)
        for day in pd.bdate_range("2026-01-05", periods=40)
    ]


def submit(client, records):
    return client.post(
        "/api/v1/backtest/run/async", json={"strategy": "ma_cross", "ohlcv": records}
    )


def test_authenticated_queue_survives_new_app_and_store_instances(site, records):
    client, accounts, (alice, bob, admin) = site
    response = submit(client, records)
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    assert response.json() == {
        "task_id": task_id,
        "status": "pending",
        "storage": "persistent",
        "reused": False,
    }
    task_service._store.cache_clear()
    with TestClient(app()) as restarted:
        url = f"/api/v1/backtest/tasks/{task_id}"
        assert restarted.get(url).status_code == 401
        restarted.cookies.set(auth.SESSION_COOKIE, accounts.create_session(alice.id))
        state = restarted.get(url).json()
        assert state["storage"] == "persistent" and state["execution_compatible"] is True
        assert state["kind"] == "backtest" and state["recovery_count"] == 0
        listing = restarted.get("/api/v1/backtest/tasks").json()
        assert listing["storage"] == "persistent" and listing["count"] == 1
        assert "result" not in listing["tasks"][0]
        for forbidden in ("owner", "payload", "lease", "worker_id", "fingerprint", "version"):
            assert forbidden not in state
        for stranger in (bob, admin):
            restarted.cookies.set(auth.SESSION_COOKIE, accounts.create_session(stranger.id))
            assert restarted.get("/api/v1/backtest/tasks").json()["count"] == 0
            for method, suffix in [("get", ""), ("post", "/cancel"), ("delete", "")]:
                denied = getattr(restarted, method)(url + suffix)
                absent = getattr(restarted, method)("/api/v1/backtest/tasks/missing" + suffix)
                assert denied.status_code == absent.status_code == 404
                assert denied.json() == absent.json()


def test_cancel_delete_and_capacity_are_real_persistent_transitions(site, records):
    client, accounts, (alice, _, _) = site
    task_id = submit(client, records).json()["task_id"]
    url = f"/api/v1/backtest/tasks/{task_id}"
    assert client.delete(url).status_code == 400
    assert client.post(url + "/cancel").json()["status"] == "cancelled"
    assert client.post(url + "/cancel").json()["status"] == "cancelled"
    assert len(accounts.list_audit(action="task_cancel")["items"]) == 1
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    audit = accounts.list_audit(action="task_delete")["items"]
    assert len(audit) == 1 and audit[0]["details"] == {"task_id": task_id}
    assert audit[0]["actor_id"] == alice.id
    for cash in (100000, 200000, 300000):
        assert (
            client.post(
                "/api/v1/backtest/run/async",
                json={
                    "strategy": "ma_cross",
                    "cash": cash,
                    "ohlcv": records,
                },
            ).status_code
            == 202
        )
    blocked = client.post(
        "/api/v1/backtest/run/async",
        json={
            "strategy": "ma_cross",
            "cash": 400000,
            "ohlcv": records,
        },
    )
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "5"
    assert len(task_service.get_durable_store().list_tasks(alice.id)) == 3


@pytest.mark.parametrize("operation", ["cancel", "delete"])
def test_audit_failure_rolls_back_task_operation_and_http_reports_unconfirmed(
    site, records, operation
):
    client, accounts, (alice, _, _) = site
    task_id = submit(client, records).json()["task_id"]
    store = task_service.get_durable_store()
    if operation == "delete":
        store.cancel(alice.id, task_id)
    before = store.summary(alice.id, task_id)["status"]
    with accounts._connect() as conn:
        conn.execute(
            "CREATE TRIGGER reject_audit BEFORE INSERT ON account_audit "
            "BEGIN SELECT RAISE(ABORT, 'private audit disk failure'); END"
        )
    url = f"/api/v1/backtest/tasks/{task_id}"
    response = client.post(url + "/cancel") if operation == "cancel" else client.delete(url)
    assert response.status_code == 503
    assert "private" not in response.text
    assert store.summary(alice.id, task_id)["status"] == before
    assert accounts.list_audit(action="task_" + operation)["items"] == []
    with accounts._connect() as conn:
        conn.execute("DROP TRIGGER reject_audit")
    response = client.post(url + "/cancel") if operation == "cancel" else client.delete(url)
    assert response.status_code == (200 if operation == "cancel" else 204)
    assert len(accounts.list_audit(action="task_" + operation)["items"]) == 1


def test_changed_execution_version_is_visible_without_mutating_old_task(site, records, monkeypatch):
    client, _, (alice, _, _) = site
    task_id = submit(client, records).json()["task_id"]
    store = task_service.get_durable_store()
    lease = store.claim(execution_version(), "test-old-worker")
    store.requeue_after_exit(lease, reason="supervisor_lost")
    monkeypatch.setattr(task_service, "execution_version", lambda: "changed-code")
    state = client.get(f"/api/v1/backtest/tasks/{task_id}").json()
    assert state["execution_compatible"] is False and state["status"] == "pending"
    assert state["recovery_count"] == 1 and state["last_recovery_reason"] == "supervisor_lost"
    assert client.get("/api/v1/backtest/tasks").json()["tasks"][0]["execution_compatible"] is False
    assert store.claim("changed-code", "new-worker") is None
    old = store.claim(execution_version(), "compatible-worker")
    store.finish_after_exit(old, result={"original": True})
    completed = client.get(f"/api/v1/backtest/tasks/{task_id}").json()
    assert completed["status"] == "done" and completed["result"] == {"original": True}


def test_exact_frozen_input_reuses_success_without_false_running_state(site, records, monkeypatch):
    client, _, (alice, _, _) = site
    frame = backtest._ohlcv_to_df(records)
    monkeypatch.setattr(backtest, "_ohlcv_to_df", lambda *_args, **_kwargs: frame)
    first = submit(client, records).json()
    duplicate = submit(client, records).json()
    assert duplicate["task_id"] == first["task_id"] and duplicate["reused"] is True
    store = task_service.get_durable_store()
    lease = store.claim(execution_version(), "test-worker")
    store.finish_after_exit(lease, result={"complete": True})
    reused = submit(client, records).json()
    assert reused["task_id"] == first["task_id"] and reused["status"] == "done"
    assert reused["reused"] is True


def test_storage_failure_never_falls_back_to_memory(site, records, monkeypatch):
    client, _, _ = site

    def broken(_path):
        raise sqlite3.OperationalError("private-path-or-other-user-input")

    monkeypatch.setattr(task_service, "_store", broken)
    monkeypatch.setattr(backtest, "get_runner", lambda: pytest.fail("silently used memory"))
    response = submit(client, records)
    assert response.status_code == 503
    assert "private-path" not in response.text
    assert client.get("/api/v1/backtest/tasks").status_code == 503


def test_deactivated_account_is_rechecked_after_market_loading(site, records, monkeypatch):
    client, accounts, (alice, _, _) = site
    frame = backtest._ohlcv_to_df(records)

    def deactivate(*_args, **_kwargs):
        accounts.update_user(alice.id, active=False)
        return frame

    monkeypatch.setattr(backtest, "_ohlcv_to_df", deactivate)
    assert submit(client, records).status_code == 401
    assert task_service.get_durable_store().list_tasks(alice.id) == []


@pytest.mark.skipif(sys.platform == "win32", reason="Independent POSIX worker")
@pytest.mark.parametrize(
    "kind", ["backtest", "portfolio", "multi_strategy", "optimize", "optimize_all", "signal_scan"]
)
def test_six_http_submissions_execute_frozen_inputs_in_actual_worker(
    site, records, monkeypatch, kind
):
    from easy_tdx.backtest.multi_strategy_engine import StrategySlot
    from easy_tdx.backtest.portfolio_engine import StockData
    from easy_tdx.backtest.strategies import get_registry
    from easy_tdx.web import signal_scan, strategy_store

    client, _, (alice, _, _) = site
    frame = backtest._ohlcv_to_df(records)
    request = {"strategy": "ma_cross", "ohlcv": records}
    route = "run"
    if kind == "portfolio":
        route = "portfolio/run"
        request = {"strategy": "ma_cross", "stocks": ["SZ:300750", "SH:600699"]}

        async def stocks(*_args, **_kwargs):
            return [
                StockData(market="SZ", code="300750", df=frame),
                StockData(market="SH", code="600699", df=frame),
            ]

        monkeypatch.setattr(backtest, "_fetch_portfolio_bars", stocks)
    elif kind == "multi_strategy":
        route = "multi-strategy/run"
        request = {"items": [{"strategy": "ma_cross", "symbol": "SZ:300750"}]}

        async def slots(*_args, **_kwargs):
            entry = get_registry().get("ma_cross")
            return [
                StrategySlot(
                    label=entry.label, symbol="SZ:300750", strategy=entry.build({}), df=frame
                )
            ]

        monkeypatch.setattr(backtest, "_fetch_multi_strategy_bars", slots)
    elif kind == "optimize":
        route = "optimize/run"
        request["param_grid"] = {"fast": [5], "slow": [10]}
    elif kind == "optimize_all":
        route = "optimize-all/run"
        request = {"ohlcv": records, "workers": 8}
    elif kind == "signal_scan":
        route = "signal-scan/run"
        request = {}
        target = signal_scan.ScanTarget(
            "frozen-saved", "真实冻结策略", "single", "ma_cross", symbol="SZ:300750"
        )
        monkeypatch.setattr(
            strategy_store,
            "get_store",
            lambda: SimpleNamespace(list_all=lambda _owner: [{"id": "test"}]),
        )
        monkeypatch.setattr(signal_scan, "expand_targets", lambda _records: [target])

        async def bars(*_args, **_kwargs):
            return {("SZ:300750", "DAY"): frame}

        monkeypatch.setattr(signal_scan, "fetch_scan_bars", bars)
    response = client.post(f"/api/v1/backtest/{route}/async", json=request)
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]
    store = task_service.get_durable_store()
    supervisor = TaskSupervisor(store)
    try:
        supervisor.step()
        running = supervisor._running[task_id]
        frozen = store.load_input(running.lease, execution_version=supervisor.version)
        assert frozen.kind == kind
        expected = dispatch_task(frozen)
        deadline = time.monotonic() + 60
        while supervisor.active_count and time.monotonic() < deadline:
            supervisor.step(admit=False)
            time.sleep(0.01)
        assert supervisor.active_count == 0
        task_service._store.cache_clear()
        with TestClient(app()) as new_http:
            new_http.cookies.update(client.cookies)
            actual = new_http.get(f"/api/v1/backtest/tasks/{task_id}").json()
        assert actual["status"] == "done", actual
        if kind == "signal_scan":
            assert actual["result"].pop("evidence_task_id") == task_id
            actual["result"].pop("elapsed")
            expected.pop("elapsed")
        assert actual["result"] == expected
        assert TaskStore(store.path).get(alice.id, task_id)["result"] is not None
    finally:
        supervisor.close()


def test_invalid_backend_configuration_does_not_select_memory(monkeypatch):
    monkeypatch.setenv("EASY_TDX_TASK_BACKEND", "typo")
    with pytest.raises(ValueError, match="拒绝静默回退"):
        task_service.task_backend()
