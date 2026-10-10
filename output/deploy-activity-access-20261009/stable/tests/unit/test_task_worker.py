"""Actual child processes: staged results, cancellation, death and restart."""

import signal
import sqlite3
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import pytest

from easy_tdx.web.backtest_schemas import BacktestRequest
from easy_tdx.web.routers.backtest import _ohlcv_to_df, _run_backtest
from easy_tdx.web.task_dispatch import dispatch_task, scan_task_input
from easy_tdx.web.task_guard import TaskGuard, guard_path
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_store import TaskLimits, TaskStore
from easy_tdx.web.task_supervisor import TaskSupervisor, WorkerLimits

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX resource supervisor; Windows must fail closed"
)


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.db", limits=TaskLimits(executing=1))


@pytest.fixture
def supervisor(store):
    instance = TaskSupervisor(store, owner_active=lambda owner: owner == "alice")
    yield instance
    instance.close()


def job(version):
    closes = 30 + 4 * np.sin(np.arange(100) / 5)
    records = [
        dict(
            datetime=str(day.date()),
            open=float(price - 0.1),
            high=float(price + 1),
            low=float(price - 1),
            close=float(price),
            vol=100000,
            amount=float(price * 100000),
        )
        for day, price in zip(pd.bdate_range("2026-01-05", periods=100), closes)
    ]
    req = BacktestRequest(strategy="ma_cross", symbol="SZ:300750", params={"fast": 5, "slow": 10})
    return TaskInput("backtest", version, req.model_dump(), (_ohlcv_to_df(records),), {})


def drain(supervisor, timeout=15):
    deadline = time.monotonic() + timeout
    while supervisor.active_count and time.monotonic() < deadline:
        supervisor.step(admit=False)
        time.sleep(0.01)
    assert supervisor.active_count == 0


def test_real_worker_stages_but_cannot_publish_before_observed_exit(supervisor, store):
    value = job(supervisor.version)
    record, _ = store.submit("alice", value)
    supervisor.step()
    child = supervisor._running[record["task_id"]].process
    assert child.wait(timeout=15) == 0
    # Worker has exited, but nobody has published its private staged result yet.
    assert store.get("alice", record["task_id"])["status"] == "running"
    assert store.get("alice", record["task_id"])["result"] is None
    supervisor.step(admit=False)
    result = store.get("alice", record["task_id"])
    assert result["status"] == "done", result
    assert result["result"] == _run_backtest(
        value.frames[0], BacktestRequest.model_validate(value.request)
    )


@pytest.mark.parametrize(
    "kind", ["portfolio", "multi_strategy", "optimize", "optimize_all", "signal_scan"]
)
def test_remaining_kinds_execute_in_actual_child_with_equivalent_results(supervisor, store, kind):
    from easy_tdx.web.backtest_schemas import (
        MultiStrategyBacktestRequest,
        OptimizeAllBacktestRequest,
        OptimizeBacktestRequest,
        PortfolioBacktestRequest,
        SignalScanRequest,
    )
    from easy_tdx.web.signal_scan import ScanTarget

    frame = job(supervisor.version).frames[0]
    context = {}
    frames = (frame,)
    if kind == "portfolio":
        request = PortfolioBacktestRequest(
            strategy="ma_cross", stocks=["SZ:300750", "SH:600699"], params={"fast": 5, "slow": 10}
        )
        frames = (frame, frame)
    elif kind == "multi_strategy":
        request = MultiStrategyBacktestRequest(
            items=[
                {"strategy": "ma_cross", "symbol": "SZ:300750", "params": {"fast": 5, "slow": 10}},
                {"strategy": "rsi_reversal", "symbol": "SH:600699", "params": {"n": 7}},
            ]
        )
        frames = (frame, frame)
    elif kind == "optimize":
        request = OptimizeBacktestRequest(
            strategy="ma_cross", symbol="SZ:300750", param_grid={"slow": [10, 20], "fast": [5]}
        )
    elif kind == "optimize_all":
        request = OptimizeAllBacktestRequest(symbol="SZ:300750", workers=8)
    else:
        value = scan_task_input(
            supervisor.version,
            SignalScanRequest(),
            {("SZ:300750", "DAY"): frame},
            [ScanTarget("saved-1", "测试策略", "single", "ma_cross", symbol="SZ:300750")],
        )
        request = SignalScanRequest()
        context = value.context
    value = TaskInput(kind, supervisor.version, request.model_dump(), frames, context)
    expected = dispatch_task(value)
    record, _ = store.submit("alice", value)
    supervisor.step()
    drain(supervisor, timeout=90)
    state = store.get("alice", record["task_id"])
    assert state["status"] == "done", state
    actual = state["result"]
    if kind == "signal_scan":
        actual.pop("elapsed")
        expected.pop("elapsed")
    assert actual == expected


def test_actual_stopped_child_is_killed_before_cancelled_slot_released(supervisor, store):
    supervisor.limits = WorkerLimits(stop_grace_seconds=0.03)
    record, _ = store.submit("alice", job(supervisor.version))
    supervisor.step()
    child = supervisor._running[record["task_id"]].process
    child.send_signal(signal.SIGSTOP)
    store.cancel("alice", record["task_id"])
    supervisor.step(admit=False)
    assert child.poll() is None
    assert store.get("alice", record["task_id"])["status"] == "cancelling"
    assert store.claim(supervisor.version, "other-worker") is None
    drain(supervisor)
    assert child.returncode is not None
    result = store.get("alice", record["task_id"])
    assert result["status"] == "cancelled" and result["result"] is None


def test_real_child_wall_timeout_no_partial_result(supervisor, store):
    supervisor.limits = WorkerLimits(wall_seconds=0.01, stop_grace_seconds=0.01)
    record, _ = store.submit("alice", job(supervisor.version))
    supervisor.step()
    child = supervisor._running[record["task_id"]].process
    child.send_signal(signal.SIGSTOP)
    drain(supervisor)
    assert child.returncode is not None
    assert store.get("alice", record["task_id"])["status"] == "timed_out"
    assert store.get("alice", record["task_id"])["result"] is None


def test_worker_death_is_failed_and_never_done(supervisor, store):
    record, _ = store.submit("alice", job(supervisor.version))
    supervisor.step()
    child = supervisor._running[record["task_id"]].process
    child.kill()
    child.wait(timeout=5)
    supervisor.step(admit=False)
    result = store.get("alice", record["task_id"])
    assert result["status"] == "failed" and result["result"] is None
    assert str(child.returncode) in result["error"]


def test_source_version_mismatch_refused_by_actual_worker(supervisor, store):
    supervisor.version = "deliberately-wrong-source-version"
    record, _ = store.submit("alice", job(supervisor.version))
    supervisor.step()
    drain(supervisor)
    result = store.get("alice", record["task_id"])
    assert result["status"] == "failed", result
    assert "版本不一致" in result["error"]


def test_revoked_account_is_not_started_and_active_one_is_stopped(supervisor, store):
    record, _ = store.submit("bob", job(supervisor.version))
    supervisor.step()
    assert supervisor.active_count == 0
    assert store.get("bob", record["task_id"])["status"] == "cancelled"
    active, _ = store.submit("alice", job(supervisor.version))
    supervisor.step()
    supervisor._owner_active = lambda owner: False
    drain(supervisor)
    assert store.get("alice", active["task_id"])["status"] == "cancelled"


def test_account_lookup_error_fails_closed(supervisor, store):
    def unavailable(owner):
        raise RuntimeError("account store unavailable")

    supervisor._owner_active = unavailable
    record, _ = store.submit("alice", job(supervisor.version))
    supervisor.step()
    assert supervisor.active_count == 0
    assert store.get("alice", record["task_id"])["status"] == "cancelled"


def test_graceful_supervisor_close_requeues_only_after_killing_owned_child(supervisor, store):
    record, _ = store.submit("alice", job(supervisor.version))
    supervisor.step()
    running = supervisor._running[record["task_id"]]
    running.process.send_signal(signal.SIGSTOP)
    supervisor.close()
    assert running.process.returncode is not None
    assert store.get("alice", record["task_id"])["status"] == "pending"
    with TaskStore(store.path).connect() as conn:
        assert conn.execute("SELECT staged_result FROM tasks").fetchone()[0] is None
    restarted = TaskSupervisor(TaskStore(store.path), owner_active=lambda owner: True)
    try:
        restarted.step()
        assert (
            restarted._running[record["task_id"]].lease.generation == running.lease.generation + 1
        )
        drain(restarted)
        assert store.get("alice", record["task_id"])["status"] == "done"
    finally:
        restarted.close()


def test_parent_pipe_loss_stops_child_without_faking_completed_status(supervisor, store):
    record, _ = store.submit("alice", job(supervisor.version))
    supervisor.step()
    child = supervisor._running[record["task_id"]].process
    child.stdin.close()
    assert child.wait(timeout=15) != 0
    supervisor.step(admit=False)
    assert store.get("alice", record["task_id"])["status"] == "failed"


def test_shutdown_stops_owned_child_even_when_database_is_unavailable(
    supervisor, store, monkeypatch
):
    record, _ = store.submit("alice", job(supervisor.version))
    supervisor.step()
    child = supervisor._running[record["task_id"]].process
    child.send_signal(signal.SIGSTOP)

    def unavailable():
        raise sqlite3.OperationalError("database unavailable during shutdown")

    with monkeypatch.context() as scoped:
        scoped.setattr(store, "connect", unavailable)
        with pytest.raises(RuntimeError, match="关闭"):
            supervisor.close()
        assert child.poll() is not None
        assert supervisor.active_count == 1  # Keep uncommitted bookkeeping for retry.
        assert TaskGuard.acquire(guard_path(store.path, supervisor.worker_id)) is None
    assert store.get("alice", record["task_id"])["status"] == "running"
    supervisor.close()
    assert supervisor.active_count == 0
    assert store.get("alice", record["task_id"])["status"] == "pending"


def test_cannot_run_after_supervisor_is_closed(supervisor):
    supervisor.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        supervisor.step()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"wall_seconds": 0},
        {"wall_seconds": float("nan")},
        {"stop_grace_seconds": -1},
        {"cpu_seconds": True},
        {"address_space_bytes": -1},
    ],
)
def test_invalid_resource_limits(kwargs):
    with pytest.raises(ValueError):
        WorkerLimits(**kwargs)


def test_actual_cpu_limit_terminates_noncooperative_child():
    code = "from easy_tdx.web.task_worker import _limits; _limits(1, None)\nwhile True: pass"
    result = subprocess.run(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=8,
    )
    assert result.returncode in (-signal.SIGXCPU, -signal.SIGKILL)


def test_worker_does_not_raise_existing_host_resource_limits(monkeypatch):
    import resource

    from easy_tdx.web.task_worker import _limits

    calls = []
    monkeypatch.setattr(
        resource, "getrlimit", lambda kind: (3, 4) if kind == resource.RLIMIT_CPU else (128, 256)
    )
    monkeypatch.setattr(resource, "setrlimit", lambda kind, limits: calls.append((kind, limits)))
    _limits(600, 512)
    assert calls == [
        (resource.RLIMIT_CORE, (0, 0)),
        (resource.RLIMIT_CPU, (3, 4)),
        (resource.RLIMIT_AS, (128, 256)),
    ]
