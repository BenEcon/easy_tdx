"""Single-security factor tasks retain inputs, errors, identity and cancellation."""

import copy
import json
import time
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from easy_tdx.factor.snapshot import restore_input
from easy_tdx.progress import ProgressPublicationError, progress_scope
from easy_tdx.web import account_store, task_store
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.activity_queries import record_query
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.errors import register_exception_handlers
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import auth, backtest, research
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_runner import BacktestTaskRunner
from easy_tdx.web.task_store import TaskStore
from easy_tdx.web.task_supervisor import TaskSupervisor
from easy_tdx.web.user_activity import get_activity_store
from tests.unit.test_factor_tasks import round_trip

URL = "/api/v1/research/factors/compute/async"


@pytest.fixture
def value():
    result = json.loads(
        (Path(__file__).parents[1] / "fixtures/factor_archive/series.json").read_text()
    )["result"]
    return TaskInput(
        "factor_series",
        "test-series-v1",
        result["settings"],
        tuple(restore_input(s) for s in result["input_snapshots"]),
        {"symbol": "SZ:000001", "category": "DAY"},
    )


def test_series_frozen_dispatch_matches_sync_including_missing_factor_and_full_archive(value):
    request = research.FactorComputeRequest.model_validate(value.request)
    expected = research._factor_result(request, value.frames[0]).data
    events = []
    with progress_scope(events.append):
        result = dispatch_task(round_trip(value))
    assert result == expected
    assert result["count"] == 160 and result["output_truncated"] is False
    assert "pe_ratio" in result["errors"] and len(result["computed"]) == 2
    assert [p["completed"] for p in events if p["phase"] == "factor_series"] == [0, 1, 2, 3]
    assert events[-1]["phase"] == "result_validation" and events[-1]["completed"] == 1
    validate_factor_archive(
        {
            "format": "factor-research-v1",
            "mode": "series",
            "title": "完整单股任务",
            "savedAt": "2026-10-10T00:00:00Z",
            "result": result,
        }
    )


@pytest.mark.parametrize("mutation", ["symbol", "category", "extra", "missing", "frames"])
def test_series_mapping_rejects_wrong_identity_or_silent_default(value, monkeypatch, mutation):
    context, request, frames = (
        copy.deepcopy(value.context),
        copy.deepcopy(value.request),
        value.frames,
    )
    if mutation in {"symbol", "category"}:
        context[mutation] = "incorrect"
    elif mutation == "extra":
        request["unknown"] = 1
    elif mutation == "missing":
        request.pop("adjust")
    else:
        frames = frames + frames
    monkeypatch.setattr(research, "_factor_result", lambda *a: pytest.fail("must reject first"))
    with pytest.raises(ValueError):
        dispatch_task(replace(value, context=context, request=request, frames=frames))


@pytest.mark.parametrize("bad", ["adjust", "quality", "empty", "too_many"])
def test_series_input_does_not_fall_back_or_trim(value, bad):
    frame = value.frames[0].copy(deep=True)
    frame.attrs = copy.deepcopy(frame.attrs)
    request = copy.deepcopy(value.request)
    if bad == "adjust":
        frame.attrs["snapshot_metadata"]["actual_adjust"] = "QFQ"
    elif bad == "quality":
        frame.attrs["snapshot_metadata"]["quality"] = {"status": "error"}
    elif bad == "empty":
        frame = frame.iloc[:0]
    else:
        request["count"] = 60
    with pytest.raises(ValueError):
        dispatch_task(replace(value, frames=(frame,), request=request))


def test_series_progress_storage_failure_is_not_a_missing_factor_diagnostic(value):
    def fail(p):
        if p["phase"] == "factor_series" and p["completed"] == 1:
            raise OSError("progress lost")

    with progress_scope(fail), pytest.raises(ProgressPublicationError):
        dispatch_task(value)


@pytest.fixture(params=["memory", "durable"])
def site(request, value, tmp_path, monkeypatch):
    monkeypatch.setenv("EASY_TDX_TASK_BACKEND", request.param)
    accounts = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(account_store, "_store", accounts)
    alice = accounts.create_user("alice", "series-task-password")
    bob = accounts.create_user("bob", "series-task-password")
    runner = BacktestTaskRunner(max_workers=1)
    monkeypatch.setattr(backtest, "get_runner", lambda: runner)
    fetched = []

    async def fetch(req, client, mac):
        fetched.append(req.model_dump())
        return value.frames[0].copy(deep=True)

    monkeypatch.setattr(research, "_series_frame", fetch)
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_client] = lambda: object()
    app.dependency_overrides[get_mac_client_optional] = lambda: None
    for router in (research.router, backtest.router):
        app.include_router(router, prefix="/api/v1", dependencies=[Depends(record_query)])
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(alice.id))
        try:
            yield client, accounts, alice, bob, fetched
        finally:
            runner.shutdown()


def test_series_http_owner_isolation_and_manual_vs_automatic_activity(site, value):
    client, accounts, alice, bob, fetched = site
    assert client.post(URL, json=value.request, headers={"X-Task-Owner": bob.id}).status_code == 409
    assert fetched == []
    for origin in ("system", "user"):
        response = client.post(
            URL,
            json=value.request,
            headers={
                "X-Task-Owner": alice.id,
                "X-Query-Origin": origin,
            },
        )
        assert response.status_code == 202, response.text
        assert response.headers["Cache-Control"] == "no-store"
        task_url = f"/api/v1/backtest/tasks/{response.json()['task_id']}"
        assert client.get(task_url).json()["kind"] == "factor_series"
        assert len(get_activity_store().events(days=1)["items"]) == (origin == "user")
    event = get_activity_store().events(days=1)["items"][0]
    assert event["feature"] == "因子序列任务" and event["details"]["code"] == "000001"
    client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(bob.id))
    assert client.get(task_url).status_code == 404
    assert client.post(task_url + "/cancel").status_code == 404
    client.cookies.clear()
    assert client.post(URL, json=value.request).status_code == 401
    assert len(fetched) == 2


def test_series_real_worker_result_and_reopen(value, tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    supervisor = TaskSupervisor(store, owner_active=lambda owner: owner == "alice")
    try:
        frozen = replace(value, execution_version=supervisor.version)
        expected = dispatch_task(frozen)
        state, _ = store.submit("alice", frozen)
        supervisor.step()
        deadline = time.monotonic() + 40
        while supervisor.active_count and time.monotonic() < deadline:
            supervisor.step(admit=False)
            time.sleep(0.02)
        assert supervisor.active_count == 0
        result = TaskStore(store.path).get("alice", state["task_id"])
        assert result["status"] == "done", result.get("error")
        assert result["result"] == expected and result["kind"] == "factor_series"
        assert result["progress"]["phase"] == "result_validation"
        reused, hit = store.submit("alice", frozen)
        assert hit and reused["task_id"] == state["task_id"]
    finally:
        supervisor.close()


def test_series_memory_cancel_and_full_result_budget(value, monkeypatch):
    original = research._factor_result
    reached, release = Event(), Event()

    def delayed(*args):
        reached.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(research, "_factor_result", delayed)
    runner = BacktestTaskRunner(max_workers=1)
    try:
        task = runner.submit(lambda: dispatch_task(value), owner_id="alice")
        assert reached.wait(2)
        runner.cancel(task)
        release.set()
        deadline = time.monotonic() + 5
        while runner.get(task).status == "cancelling" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runner.get(task).status == "cancelled" and runner.get(task).result is None
        monkeypatch.setattr(task_store, "MAX_RESULT_BYTES", 128)
        with pytest.raises(ValueError, match="完整结果超过"):
            dispatch_task(value)
    finally:
        release.set()
        runner.shutdown()
