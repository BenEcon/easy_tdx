"""Factor tasks use the shared queue, frozen data and authenticated control plane."""

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
from easy_tdx.web import account_store
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.activity_queries import record_query
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.errors import register_exception_handlers
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import auth, backtest, research
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_payload import (
    TaskInput,
    decode_task_input,
    encode_task_input,
    input_fingerprint,
)
from easy_tdx.web.task_runner import BacktestTaskRunner
from easy_tdx.web.task_store import TaskStore
from easy_tdx.web.task_supervisor import TaskSupervisor
from easy_tdx.web.user_activity import get_activity_store


@pytest.fixture
def value():
    payload = json.loads(
        (Path(__file__).parents[1] / "fixtures/factor_archive/multi-horizon.json").read_text()
    )
    settings = dict(payload["result"]["settings"])
    settings.pop("category")
    inputs = payload["result"]["input_snapshots"]
    return TaskInput(
        "factor_evaluation",
        "test-v1",
        settings,
        tuple(restore_input(item) for item in inputs),
        {"symbols": [item["symbol"] for item in inputs]},
    )


def round_trip(value):
    data = encode_task_input(value)
    return decode_task_input(
        data, execution_version=value.execution_version, fingerprint=input_fingerprint(data)
    )


def test_frozen_dispatch_equals_sync_result_and_keeps_all_archive_inputs(value, monkeypatch):
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("live fetch"))
    request = research.FactorEvaluationRequest.model_validate(value.request)
    frames = dict(zip(value.context["symbols"], value.frames, strict=True))
    expected = research.evaluation_result(request, frames)
    result = dispatch_task(round_trip(value))
    assert result == expected
    assert len(result["input_snapshots"]) == len(request.stocks)
    assert result["settings"]["horizons"] == [1, 5, 10, 20]
    validate_factor_archive(
        {
            "format": "factor-research-v1",
            "mode": "evaluation",
            "title": "后台冻结检验",
            "savedAt": "2026-10-10T00:00:00Z",
            "result": result,
        }
    )


@pytest.mark.parametrize("mutation", ["missing", "reorder", "extra", "duplicate", "count"])
def test_mismatched_pool_rejected_before_calculation(value, monkeypatch, mutation):
    context = copy.deepcopy(value.context)
    frames = value.frames
    if mutation == "missing":
        context = {}
    elif mutation == "reorder":
        context["symbols"].reverse()
    elif mutation == "extra":
        context["ignored"] = True
    elif mutation == "duplicate":
        context["symbols"][1] = context["symbols"][0]
    else:
        frames = frames[:-1]
    monkeypatch.setattr(research, "evaluation_result", lambda *a: pytest.fail("must reject first"))
    with pytest.raises(ValueError, match="冻结行情"):
        dispatch_task(replace(value, context=context, frames=frames))


@pytest.fixture(params=["memory", "durable"])
def site(request, value, tmp_path, monkeypatch):
    backend = request.param
    monkeypatch.setenv("EASY_TDX_TASK_BACKEND", backend)
    accounts = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(account_store, "_store", accounts)
    alice = accounts.create_user("alice", "factor-tasks-test-password")
    bob = accounts.create_user("bob", "factor-tasks-test-password")
    runner = BacktestTaskRunner(max_workers=1)
    monkeypatch.setattr(backtest, "get_runner", lambda: runner)
    fetched = []

    async def fetch(req, client, mac_client):
        fetched.append(req.model_dump())
        return {s: df.copy(deep=True) for s, df in zip(value.context["symbols"], value.frames)}

    monkeypatch.setattr(research, "_evaluation_frames", fetch)
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_client] = lambda: object()
    app.dependency_overrides[get_mac_client_optional] = lambda: None
    app.include_router(research.router, prefix="/api/v1", dependencies=[Depends(record_query)])
    app.include_router(backtest.router, prefix="/api/v1", dependencies=[Depends(record_query)])
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(alice.id))
        try:
            yield client, accounts, alice, bob, runner, fetched, backend
        finally:
            runner.shutdown()


URL = "/api/v1/research/factors/evaluate/async"


def test_submit_auth_ownership_and_manual_activity(site, value):
    client, accounts, alice, bob, runner, fetched, backend = site
    wrong = client.post(URL, json=value.request, headers={"X-Task-Owner": bob.id})
    assert wrong.status_code == 409 and fetched == []
    response = client.post(
        URL,
        json=value.request,
        headers={
            "X-Task-Owner": alice.id,
            "X-Query-Origin": "user",
        },
    )
    assert response.status_code == 202, response.text
    assert response.headers["Cache-Control"] == "no-store"
    task_id = response.json()["task_id"]
    task_url = f"/api/v1/backtest/tasks/{task_id}"
    assert len(fetched) == 1
    for _ in range(3):
        assert client.get(task_url).status_code == 200
    assert client.get(task_url).json()["kind"] == "factor_evaluation"
    assert client.get("/api/v1/backtest/tasks").json()["tasks"][0]["kind"] == "factor_evaluation"
    activity = get_activity_store()
    events = activity.events(days=1)["items"]
    assert len(events) == 1 and events[0]["feature"] == "因子截面检验任务"
    assert activity.summary(1)[alice.id]["queries"] == 1
    client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(bob.id))
    assert client.get(task_url).status_code == 404
    assert client.post(task_url + "/cancel").status_code == 404
    client.cookies.clear()
    assert client.post(URL, json=value.request).status_code == 401
    assert len(fetched) == 1


def test_system_submission_and_polling_are_not_manual_queries(site, value):
    client, _, _, _, _, _, _ = site
    response = client.post(URL, json=value.request, headers={"X-Query-Origin": "system"})
    assert response.status_code == 202
    assert client.get(f"/api/v1/backtest/tasks/{response.json()['task_id']}").status_code == 200
    assert not get_activity_store().events(days=1)["items"]


def test_actual_independent_worker_publishes_complete_factor_result(value, tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    with_supervisor = TaskSupervisor(store, owner_active=lambda owner: owner == "alice")
    try:
        frozen = replace(value, execution_version=with_supervisor.version)
        expected = dispatch_task(frozen)
        state, reused = store.submit("alice", frozen)
        assert not reused
        with_supervisor.step()
        deadline = time.monotonic() + 40
        while with_supervisor.active_count and time.monotonic() < deadline:
            with_supervisor.step(admit=False)
            time.sleep(0.02)
        assert with_supervisor.active_count == 0
        result = store.get("alice", state["task_id"])
        assert result["status"] == "done", result.get("error")
        assert result["result"] == expected
        assert result["progress"]["phase"] == "result_validation"
        assert result["progress"]["completed"] == 1
        cached, reused = store.submit("alice", frozen)
        assert reused and cached["task_id"] == state["task_id"]
        other, reused = store.submit("bob", frozen)
        assert not reused and other["task_id"] != state["task_id"]
    finally:
        with_supervisor.close()


def test_memory_cancellation_drops_late_factor_result(value, monkeypatch):
    started, release = Event(), Event()
    original = research.evaluation_result

    def delayed(*args):
        started.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(research, "evaluation_result", delayed)
    runner = BacktestTaskRunner(max_workers=1)
    try:
        task_id = runner.submit(lambda: dispatch_task(round_trip(value)), owner_id="alice")
        assert started.wait(2)
        assert runner.cancel(task_id).status == "cancelling"
        release.set()
        deadline = time.monotonic() + 5
        while runner.get(task_id).status == "cancelling" and time.monotonic() < deadline:
            time.sleep(0.01)
        state = runner.get(task_id)
        assert state.status == "cancelled" and state.result is None
    finally:
        release.set()
        runner.shutdown()


def test_full_result_limit_fails_instead_of_publishing_truncated_memory_result(value, monkeypatch):
    from easy_tdx.web import task_store

    monkeypatch.setattr(task_store, "MAX_RESULT_BYTES", 128)
    runner = BacktestTaskRunner(max_workers=1)
    try:
        task_id = runner.submit(lambda: dispatch_task(value), owner_id="alice")
        deadline = time.monotonic() + 10
        while runner.get(task_id).status in {"pending", "running"} and time.monotonic() < deadline:
            time.sleep(0.01)
        state = runner.get(task_id)
        assert state.status == "failed" and state.result is None
        assert "完整结果超过" in state.error
    finally:
        runner.shutdown()
