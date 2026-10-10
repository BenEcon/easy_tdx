"""Lossless, fenced, quota-accounted checkpoints and real process resume."""

import math
import multiprocessing
import signal
import sqlite3
import struct
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.checkpoints import checkpoint_scope
from easy_tdx.computation import ComputationStopped
from easy_tdx.web.backtest_schemas import OptimizeAllBacktestRequest, OptimizeBacktestRequest
from easy_tdx.web.routers.backtest import _ohlcv_to_df
from easy_tdx.web.task_checkpoints import TaskCheckpoints
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_store import StaleTaskLease, TaskLimits, TaskStore, TaskStoreFull
from easy_tdx.web.task_supervisor import TaskSupervisor


def frozen(rows=100):
    prices = 30 + 4 * np.sin(np.arange(rows) / 5)
    frame = _ohlcv_to_df(
        [
            dict(
                datetime=str(day.date()),
                open=float(p),
                high=float(p + 1),
                low=float(p - 1),
                close=float(p),
                vol=1000,
                amount=float(p * 1000),
            )
            for day, p in zip(pd.bdate_range("2026-01-05", periods=rows), prices)
        ]
    )
    req = OptimizeBacktestRequest(
        strategy="ma_cross", symbol="SZ:300750", param_grid={"fast": [2, 5, 5, 20], "slow": [5, 10]}
    )
    return TaskInput("optimize", "v1", req.model_dump(), (frame,), {})


@pytest.fixture
def active(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    record, _ = store.submit("alice", frozen())
    return store, store.claim("v1", "first"), record["task_id"]


def usage(store):
    with store.connect() as conn:
        return conn.execute(
            "SELECT retained_bytes,length(payload),COALESCE(length(checkpoint),0),"
            "COALESCE(length(staged_result),0),COALESCE(length(result),0) FROM tasks"
        ).fetchone()


def test_lossless_checkpoint_survives_restart_and_is_never_public_result(active):
    store, lease, task_id = active
    journal = TaskCheckpoints(store, lease, "v1")
    nan = struct.unpack(">d", bytes.fromhex("7ff8000000000042"))[0]
    values = {
        "exact": 1.2345678901234567,
        "negative_zero": -0.0,
        "nan": nan,
        "infinity": float("inf"),
        "big": 2**61 + 1,
        "numpy": np.float32(0.3),
    }
    journal.save("test", values)
    values["exact"] = 0
    result = TaskCheckpoints(TaskStore(store.path), lease, "v1").restore("test")
    assert result["exact"] == 1.2345678901234567
    assert math.copysign(1, result["negative_zero"]) == -1
    assert struct.pack(">d", result["nan"]).hex() == "7ff8000000000042"
    assert result["infinity"] == float("inf") and result["big"] == 2**61 + 1
    assert result["numpy"].dtype == np.dtype("float32")
    public = store.get("alice", task_id)
    assert public["result"] is None and "checkpoint" not in public
    count = usage(store)
    assert count[0] == count[1] + count[2] and count[2] > 0


def test_recovery_fences_old_lease_and_preserves_checkpoint_bytes(active):
    store, old, task_id = active
    journal = TaskCheckpoints(store, old, "v1")
    journal.save("test", {"cursor": 2})
    store.requeue_after_exit(old)
    count = usage(store)
    assert count[0] == count[1] + count[2]
    new = store.claim("v1", "second")
    for callback in (
        lambda: journal.save("test", {"cursor": 1}),
        lambda: TaskCheckpoints(store, old, "v1"),
    ):
        with pytest.raises(StaleTaskLease):
            callback()
    assert TaskCheckpoints(store, new, "v1").restore("test") == {"cursor": 2}
    with pytest.raises(ValueError, match="版本"):
        TaskCheckpoints(store, new, "different-version")
    store.stage_result(new, result={"all": True})
    count = usage(store)
    assert count[0] == count[1] + count[2] + count[3]
    store.finish_staged_after_exit(new, 0)
    count = usage(store)
    assert count[2] == 0 and count[0] == count[1] + count[4]
    assert store.get("alice", task_id)["result"] == {"all": True}


def test_same_lease_cas_and_write_failure_preserve_last_valid_snapshot(active):
    store, lease, _ = active
    first, stale = TaskCheckpoints(store, lease, "v1"), TaskCheckpoints(store, lease, "v1")
    first.save("test", {"cursor": 1})
    with pytest.raises(StaleTaskLease):
        stale.save("test", {"cursor": 0})
    with store.connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_checkpoint BEFORE UPDATE OF checkpoint ON tasks "
            "BEGIN SELECT RAISE(ABORT,'storage failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        first.save("test", {"cursor": 2})
    assert first.restore("test") == {"cursor": 1}
    assert TaskCheckpoints(store, lease, "v1").restore("test") == {"cursor": 1}


@pytest.mark.parametrize("stop", ["cancelled", "timed_out"])
def test_stop_never_resumes_or_publishes_checkpoint(active, stop):
    store, lease, task_id = active
    journal = TaskCheckpoints(store, lease, "v1")
    journal.save("test", {"cursor": 1})
    if stop == "cancelled":
        store.cancel("alice", task_id)
    else:
        store.request_timeout(lease)
    with pytest.raises(ComputationStopped) as caught:
        journal.save("test", {"cursor": 2})
    assert caught.value.reason == stop
    with pytest.raises(ComputationStopped):
        TaskCheckpoints(store, lease, "v1")
    store.requeue_after_exit(lease)
    assert store.claim("v1", "next") is None
    assert store.get("alice", task_id)["status"] == stop
    assert usage(store)[2] == 0


def test_pending_cancellation_releases_recovered_checkpoint(active):
    store, lease, task_id = active
    TaskCheckpoints(store, lease, "v1").save("test", {"cursor": 1})
    store.requeue_after_exit(lease)
    store.cancel("alice", task_id)
    assert usage(store)[0] == usage(store)[1] and usage(store)[2] == 0


@pytest.mark.parametrize("column", ["checkpoint", "checkpoint_fingerprint", "fingerprint", "kind"])
def test_corruption_or_other_input_cannot_be_silently_restarted(active, column):
    store, lease, _ = active
    TaskCheckpoints(store, lease, "v1").save("test", {"cursor": 1})
    with store.connect() as conn:
        conn.execute(
            f"UPDATE tasks SET {column}=?", (b"broken" if column == "checkpoint" else "broken",)
        )
    with pytest.raises(ValueError):
        TaskCheckpoints(store, lease, "v1")


def test_quota_failure_keeps_old_checkpoint_and_counts_all_namespaces(tmp_path):
    limits = TaskLimits(retained_bytes=100000, retained_bytes_per_owner=100000)
    store = TaskStore(tmp_path / "tasks.db", limits=limits)
    store.submit("alice", frozen())
    lease = store.claim("v1", "worker")
    journal = TaskCheckpoints(store, lease, "v1")
    journal.save("first", {"value": 1})
    journal.save("second", {"value": 2})
    before = tuple(usage(store))
    with pytest.raises(TaskStoreFull):
        journal.save("third", {"value": "x" * 100000})
    assert tuple(usage(store)) == before
    fresh = TaskCheckpoints(store, lease, "v1")
    assert fresh.restore("first") == {"value": 1} and fresh.restore("second") == {"value": 2}
    assert fresh.restore("third") is None


def _compute(path, lease, pause, ready, output):
    from easy_tdx.backtest.engine import BacktestEngine

    store = TaskStore(Path(path))
    value = store.load_input(lease, execution_version="v1")
    journal = TaskCheckpoints(store, lease, "v1")
    save = journal.save
    calls = []
    run = BacktestEngine.run

    def counted(self, *args, **kwargs):
        calls.append(True)
        return run(self, *args, **kwargs)

    def save_then_pause(key, state):
        save(key, state)
        if len(state["points"]) == 2:
            ready.set()
            multiprocessing.Event().wait(30)
            raise AssertionError("parent did not kill the interrupted process")

    BacktestEngine.run = counted
    if pause:
        journal.save = save_then_pause
    with checkpoint_scope(journal):
        result = dispatch_task(value)
    output.put((result, len(calls)))


def test_actual_process_restart_only_executes_remaining_grid_points(active):
    store, lease, task_id = active
    context = multiprocessing.get_context("spawn")
    ready, output = context.Event(), context.Queue()
    first = context.Process(target=_compute, args=(store.path, lease, True, ready, output))
    second = None
    try:
        first.start()
        assert ready.wait(20)
        first.kill()
        first.join(10)
        assert first.exitcode is not None and first.exitcode != 0
        assert store.get("alice", task_id)["result"] is None
        store.requeue_after_exit(lease, reason="supervisor_lost")
        new = store.claim("v1", "replacement")
        second = context.Process(target=_compute, args=(store.path, new, False, ready, output))
        second.start()
        result, remaining_calls = output.get(timeout=30)
        second.join(10)
        assert second.exitcode == 0
        assert remaining_calls == 2  # two successful earlier points are not rerun
        assert store.summary("alice", task_id)["resumed_grid_points"] == 2
        assert store.summary("alice", task_id)["checkpoint_grid_points"] == 8
        assert result == dispatch_task(store.load_input(new, execution_version="v1"))
        points = TaskCheckpoints(store, new, "v1").restore("optimizer-grid/ma_cross")["points"]
        assert len(points) == 8  # includes duplicate parameters and invalid combinations
        assert sum(point["status"] == "invalid" for point in points) == 4
    finally:
        for child in (first, second):
            if child is not None and child.is_alive():
                child.kill()
                child.join(5)
        output.close()
        output.join_thread()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX supervised worker protocol")
def test_actual_worker_shutdown_and_replacement_reuse_verified_checkpoint(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    first = TaskSupervisor(store, owner_active=lambda _: True)
    second = None
    try:
        original = frozen(rows=600)
        request = {
            **original.request,
            "param_grid": {"fast": list(range(2, 12)), "slow": list(range(30, 50))},
        }
        value = replace(original, execution_version=first.version, request=request)
        record, _ = store.submit("alice", value)
        task_id = record["task_id"]
        first.step()
        child = first._running[task_id].process
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = store.summary("alice", task_id)
            if state["checkpoint_grid_points"]:
                break
            assert child.poll() is None
            time.sleep(0.005)
        saved = state["checkpoint_grid_points"]
        assert 0 < saved < 200
        child.send_signal(signal.SIGSTOP)
        # Do not read SQLite while a suspended child might hold a commit lock.
        first.close()  # observes actual exit before retaining the partial journal
        state = store.summary("alice", task_id)
        assert state["status"] == "pending" and state["resumed_grid_points"] == 0
        second = TaskSupervisor(store, owner_active=lambda _: True)
        second.step()
        deadline = time.monotonic() + 40
        while second.active_count and time.monotonic() < deadline:
            second.step(admit=False)
            time.sleep(0.01)
        assert second.active_count == 0
        state = store.get("alice", task_id)
        assert state["status"] == "done", state
        assert state["resumed_grid_points"] >= saved
        assert state["checkpoint_grid_points"] == 0  # scratch journal released on completion
        assert state["result"] == dispatch_task(value)
    finally:
        first.close()
        if second is not None:
            second.close()


def test_all_strategy_journals_preserve_every_grid_and_need_no_recomputation(tmp_path, monkeypatch):
    from easy_tdx.backtest.engine import BacktestEngine
    from easy_tdx.backtest.strategies import presets

    monkeypatch.setattr(
        presets,
        "STRATEGY_PRESETS",
        {
            "ma_cross": {"fast": [2, 5], "slow": [5, 10]},
            "rsi_reversal": {"n": [7, 14]},
        },
    )
    base = frozen()
    value = TaskInput(
        "optimize_all",
        "v1",
        OptimizeAllBacktestRequest(symbol="SZ:300750", workers=8).model_dump(),
        base.frames,
        {},
    )
    store = TaskStore(tmp_path / "tasks.db")
    record, _ = store.submit("alice", value)
    lease = store.claim("v1", "first")
    with checkpoint_scope(TaskCheckpoints(store, lease, "v1")):
        expected = dispatch_task(value)
    store.requeue_after_exit(lease)
    fresh = store.claim("v1", "second")
    monkeypatch.setattr(
        BacktestEngine, "run", lambda *_args: pytest.fail("completed grid was rerun")
    )
    with checkpoint_scope(TaskCheckpoints(store, fresh, "v1")):
        assert dispatch_task(value) == expected
    assert store.summary("alice", record["task_id"])["resumed_grid_points"] == 6
