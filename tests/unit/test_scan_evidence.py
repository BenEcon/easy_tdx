"""Original scan evidence is owner-bound, finite, exact and never refetched."""

import copy
import time
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.web import scan_evidence, task_runner, task_service
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.backtest_schemas import SignalScanRequest
from easy_tdx.web.errors import register_exception_handlers
from easy_tdx.web.routers import auth, backtest
from easy_tdx.web.schemas import DataFrameResponse
from easy_tdx.web.signal_scan import ScanTarget, run_scan
from easy_tdx.web.task_dispatch import dispatch_task, scan_task_input
from easy_tdx.web.task_payload import decode_task_input, encode_task_input, input_fingerprint
from easy_tdx.web.task_runner import BacktestTaskRunner, TaskCapacityError
from easy_tdx.web.task_store import TaskStore
from tests.market_matrix import entries, load_case


def frozen(entry_id="300450-qfq-20261002"):
    entry = next(e for e in entries() if e["id"] == entry_id)
    _, frame, snapshot = load_case(entry)
    from easy_tdx.web.market_data import closed_frame

    frame["is_closed"] = [r["is_closed"] for r in snapshot["data"]]
    frame["period_end"] = [r["period_end"] for r in snapshot["data"]]
    frame = closed_frame(frame)
    target = ScanTarget(
        "saved-1",
        "测试策略",
        "single",
        "ma_cross",
        params={"fast": 7, "slow": 31},
        symbol=f"{entry['instrument']['market']}:{entry['code']}",
        category=entry["category"],
    )
    bars = {(target.symbol, target.category): frame}
    value = scan_task_input(
        "frozen-version", SignalScanRequest(window_bars=30, adjust=entry["adjust"]), bars, [target]
    )
    return value, run_scan(bars, [target], 30)


def terminal(runner, task_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = runner.get(task_id)
        if state.status not in {"pending", "running", "cancelling"}:
            return state
        time.sleep(0.005)
    pytest.fail("task did not terminate")


@pytest.mark.parametrize(
    "entry_id", [e["id"] for e in entries() if e["instrument"]["kind"] == "stock"]
)
def test_real_original_rows_are_lossless_and_match_original_scanner(entry_id):
    value, result = frozen(entry_id)
    data = scan_evidence.evidence_row(value, result, 0)
    assert data["bars"] == DataFrameResponse.from_dataframe(value.frames[0]).data
    assert data["row"] == result["rows"][0]
    payload = encode_task_input(value)
    decoded = decode_task_input(
        payload, execution_version=value.execution_version, fingerprint=input_fingerprint(payload)
    )
    again = dispatch_task(decoded)
    assert again["rows"] == result["rows"]


@pytest.mark.parametrize("backend", ["memory", "durable"])
def test_evidence_http_owner_version_restart_and_tamper(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("EASY_TDX_TASK_BACKEND", backend)
    runner = BacktestTaskRunner()
    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(task_runner, "_RUNNER", runner)
    monkeypatch.setattr(task_service, "get_durable_store", lambda: store)
    monkeypatch.setattr(scan_evidence, "execution_version", lambda: "new-version")
    accounts = get_account_store()
    alice = accounts.create_user("receipt-alice", "receipt-qa-password")
    bob = accounts.create_user("receipt-bob", "receipt-qa-password")
    admin = accounts.create_user("receipt-admin", "receipt-qa-password", role="admin")
    value, result = frozen()
    payload = encode_task_input(value)
    if backend == "memory":
        task_id = runner.submit(
            lambda: copy.deepcopy(result),
            owner_id=alice.id,
            frozen_input=(payload, value.execution_version, input_fingerprint(payload)),
        )
        assert terminal(runner, task_id).status == "done"
    else:
        record, _ = store.submit(alice.id, value)
        task_id = record["task_id"]
        lease = store.claim(value.execution_version, "worker")
        store.finish_after_exit(lease, result=result)
        store = TaskStore(store.path)  # actual restart/read from SQLite
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(backtest.router, prefix="/api/v1")
    url = f"/api/v1/backtest/tasks/{task_id}/scan-evidence/0"
    try:
        with TestClient(app) as client:
            assert client.get(url).status_code == 401
            for other in (bob, admin):
                client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(other.id))
                assert client.get(url).status_code == 404
            client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(alice.id))
            assert client.get(url, headers={"X-Task-Owner": bob.id}).status_code == 409
            response = client.get(url, headers={"X-Task-Owner": alice.id})
            assert response.status_code == 200, response.text
            body = response.json()
            assert response.headers["cache-control"] == "no-store"
            assert (
                body["execution_version"] == "frozen-version"
                and body["current_execution_version"] == "new-version"
            )
            assert body["bars"] == DataFrameResponse.from_dataframe(value.frames[0]).data
            assert client.get(url[:-1] + "999").status_code == 409
            if backend == "memory":
                a, _ = runner.completed_input(alice.id, task_id)
                a.frames[0].loc[0, "close"] = 999.0
                assert client.get(url).status_code == 200
                runner.get(task_id).frozen_input = (
                    b"bad",
                    value.execution_version,
                    input_fingerprint(payload),
                )
            else:
                with store.connect() as db:
                    db.execute("UPDATE tasks SET payload=? WHERE id=?", (b"bad", task_id))
            assert client.get(url).status_code == 409
    finally:
        runner.shutdown()


def test_memory_payload_budget_never_evicts_active_and_drops_terminal_cache():
    runner = BacktestTaskRunner(max_workers=1, max_input_bytes=10, max_owner_input_bytes=6)
    gate = Event()
    try:
        first = runner.submit(
            lambda: gate.wait(5) and {}, owner_id="a", frozen_input=(b"123456", "v", "f")
        )
        with pytest.raises(TaskCapacityError):
            runner.submit(lambda: {}, owner_id="a", frozen_input=(b"1", "v", "f"))
        with pytest.raises(TaskCapacityError):
            runner.submit(lambda: {}, owner_id="b", frozen_input=(b"12345", "v", "f"))
        assert runner.peek(first) is not None
        gate.set()
        terminal(runner, first)
        second = runner.submit(lambda: {}, owner_id="a", frozen_input=(b"123456", "v", "f"))
        assert runner.peek(first) is None
        assert terminal(runner, second).status == "done"
    finally:
        gate.set()
        runner.shutdown()


@pytest.mark.parametrize("change", ["kind", "row", "params", "fingerprint", "adjust", "error"])
def test_bad_original_context_does_not_fall_back(change):
    from dataclasses import replace

    value, result = frozen()
    if change == "kind":
        value = replace(value, kind="backtest")
    elif change == "row":
        result["rows"] = []
    elif change == "params":
        result["rows"][0]["params"] = {"fast": 999}
    elif change == "error":
        result["rows"][0]["error"] = "failed"
    else:
        key = "data_fingerprint" if change == "fingerprint" else "actual_adjust"
        value.frames[0].attrs["snapshot_metadata"][key] = "bad"
    with pytest.raises(ValueError):
        scan_evidence.evidence_row(value, result, 0)


def test_memory_http_submission_retains_the_actual_input_after_source_changes(monkeypatch):
    from types import SimpleNamespace

    from easy_tdx.web import signal_scan, strategy_store
    from easy_tdx.web.deps import get_client, get_mac_client_optional

    monkeypatch.setenv("EASY_TDX_TASK_BACKEND", "memory")
    runner = BacktestTaskRunner(max_results=1)
    monkeypatch.setattr(task_runner, "_RUNNER", runner)
    value, expected = frozen()
    original_records = DataFrameResponse.from_dataframe(value.frames[0]).data
    bars, targets = scan_evidence._scan_data(value)
    monkeypatch.setattr(
        strategy_store, "get_store", lambda: SimpleNamespace(list_all=lambda _: [1])
    )
    monkeypatch.setattr(signal_scan, "expand_targets", lambda _: targets)
    calls = []

    async def fetch(*args, **kwargs):
        calls.append(1)
        return bars

    monkeypatch.setattr(signal_scan, "fetch_scan_bars", fetch)
    accounts = get_account_store()
    alice = accounts.create_user("scan-input-alice", "receipt-qa-password")
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(backtest.router, prefix="/api/v1")
    app.dependency_overrides[get_client] = lambda: object()
    app.dependency_overrides[get_mac_client_optional] = lambda: None
    try:
        with TestClient(app) as client:
            client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(alice.id))
            response = client.post("/api/v1/backtest/signal-scan/run/async", json=value.request)
            assert response.status_code == 202, response.text
            task_id = response.json()["task_id"]
            assert terminal(runner, task_id).status == "done"
            actual = client.get(f"/api/v1/backtest/tasks/{task_id}").json()["result"]
            assert actual["evidence_task_id"] == task_id
            assert actual["rows"] == expected["rows"]
            value.frames[0].loc[0, "close"] = 999.0
            targets[0].params["fast"] = 999
            url = f"/api/v1/backtest/tasks/{task_id}/scan-evidence/0"
            receipt = client.get(url)
            assert receipt.status_code == 200, receipt.text
            assert receipt.json()["bars"] == original_records
            assert receipt.json()["row"]["params"] == {"fast": 7, "slow": 31}
            assert len(calls) == 1
            other = runner.submit(lambda: {}, owner_id=alice.id)
            terminal(runner, other)
            unavailable = client.get(url)
            assert unavailable.status_code == 404
            assert unavailable.headers["cache-control"] == "no-store"
            assert len(calls) == 1  # Eviction never starts a replacement query.
    finally:
        runner.shutdown()


def test_unfinished_legacy_and_oversize_inputs_are_not_original_receipts():
    from easy_tdx.web.resource_admission import resource_for

    runner = BacktestTaskRunner(max_input_bytes=10, max_owner_input_bytes=6)
    gate = Event()
    try:
        with pytest.raises(TaskCapacityError, match="单次原行情"):
            runner.submit(lambda: {}, owner_id="a", frozen_input=(b"1234567", "v", "f"))
        task_id = runner.submit(lambda: gate.wait(5) and {}, owner_id="a")
        with pytest.raises(ValueError, match="尚未成功"):
            runner.completed_input("a", task_id)
        gate.set()
        terminal(runner, task_id)
        with pytest.raises(ValueError, match="未保存"):
            runner.completed_input("a", task_id)
        with pytest.raises(KeyError):
            runner.completed_input("b", task_id)
        assert resource_for(f"/api/v1/backtest/tasks/{task_id}/scan-evidence/0", "GET") == "data"
        assert resource_for(f"/api/v1/backtest/tasks/{task_id}", "GET") is None
    finally:
        gate.set()
        runner.shutdown()
