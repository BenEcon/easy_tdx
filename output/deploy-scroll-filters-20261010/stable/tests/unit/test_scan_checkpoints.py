"""Radar row checkpoints keep identity, errors, provenance and order intact."""

import multiprocessing
import signal
import sys
import time
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.checkpoints import checkpoint_scope
from easy_tdx.web import signal_scan
from easy_tdx.web.backtest_schemas import OptimizeBacktestRequest, SignalScanRequest
from easy_tdx.web.routers.backtest import _ohlcv_to_df
from easy_tdx.web.signal_scan import ScanTarget, run_scan
from easy_tdx.web.task_checkpoints import TaskCheckpoints
from easy_tdx.web.task_dispatch import dispatch_task, scan_task_input
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_store import TaskStore
from easy_tdx.web.task_supervisor import TaskSupervisor


def scan_data(rows=100):
    prices = 30 + 4 * np.sin(np.arange(rows) / 5)
    frame = _ohlcv_to_df(
        [
            dict(
                datetime=str(day.date()),
                open=float(price),
                high=float(price + 1),
                low=float(price - 1),
                close=float(price),
                vol=1000,
                amount=float(price * 1000),
            )
            for day, price in zip(pd.bdate_range("2025-01-06", periods=rows), prices)
        ]
    )
    targets = [
        ScanTarget(
            "one",
            "正常策略",
            "single",
            "ma_cross",
            params={"fast": 2, "slow": 5},
            symbol="SZ:300750",
        ),
        ScanTarget("bad", "未知策略", "single", "not_registered", symbol="SZ:300750"),
        ScanTarget(
            "one",
            "正常策略",
            "single",
            "ma_cross",
            params={"fast": 2, "slow": 5},
            symbol="SZ:300750",
        ),
        ScanTarget("missing", "无行情", "portfolio", "ma_cross", symbol="SH:600699"),
        ScanTarget("broken", "损坏的组合", "multi", "ma_cross", error="组合条目缺少 symbol"),
        ScanTarget(
            "last", "最后策略", "single", "rsi_reversal", params={"n": 7}, symbol="SZ:300750"
        ),
    ]
    return {("SZ:300750", "DAY"): frame, ("SH:600699", "DAY"): None}, targets


def without_elapsed(result):
    return {key: value for key, value in result.items() if key != "elapsed"}


class Journal:
    def __init__(self, fail_at=None):
        self.state = None
        self.fail_at = fail_at
        self.reused = 0

    def restore(self, key):
        assert key == "signal-scan/targets"
        return deepcopy(self.state)

    def save(self, key, state):
        if len(state["rows"]) == self.fail_at:
            raise OSError("checkpoint storage unavailable")
        self.state = deepcopy(state)

    def used(self, key, completed):
        self.reused += completed


def test_write_failure_propagates_and_resume_does_not_retry_saved_error_or_duplicate(monkeypatch):
    bars, targets = scan_data()
    expected = run_scan(bars, targets, 10)
    journal = Journal(fail_at=3)
    with checkpoint_scope(journal), pytest.raises(OSError):
        run_scan(bars, targets, 10)
    assert len(journal.state["rows"]) == 2
    calls = []
    evaluate = signal_scan.evaluate_signals

    def counted(*args):
        calls.append(True)
        return evaluate(*args)

    monkeypatch.setattr(signal_scan, "evaluate_signals", counted)
    journal.fail_at = None
    previous_elapsed = journal.state["elapsed_seconds"]
    with checkpoint_scope(journal):
        result = run_scan(bars, targets, 10)
    assert len(calls) == 2 and journal.reused == 2
    assert without_elapsed(result) == without_elapsed(expected)
    assert result["elapsed"] >= round(previous_elapsed, 2)
    assert result["rows"][0] == result["rows"][2]  # original duplicate retained
    assert result["error_count"] == 3 and len(result["rows"]) == 6
    assert result["rows"][0]["metadata"] == bars[("SZ:300750", "DAY")].attrs["snapshot_metadata"]


@pytest.mark.parametrize(
    "damage",
    [
        "schema",
        "window",
        "targets",
        "identity",
        "source",
        "missing",
        "signal",
        "elapsed",
        "error",
        "incomplete",
        "future",
    ],
)
def test_corrupt_row_or_context_rejected_before_calculation(monkeypatch, damage):
    bars, targets = scan_data()
    journal = Journal()
    with checkpoint_scope(journal):
        run_scan(bars, targets, 10)
    if damage == "schema":
        journal.state["schema"] = "unknown"
    elif damage == "window":
        journal.state["window"] = 9
    elif damage == "targets":
        journal.state["targets"].reverse()
    elif damage == "identity":
        journal.state["rows"][0]["symbol"] = "SH:000001"
    elif damage == "source":
        journal.state["rows"][0]["metadata"] = {"invented": True}
    elif damage == "missing":
        del journal.state["rows"][0]["position"]
    elif damage == "signal":
        journal.state["rows"][0]["recent_signals"] = [{"date": "2026-01-01", "direction": "HOLD"}]
    elif damage == "elapsed":
        journal.state["elapsed_seconds"] = float("nan")
    elif damage == "incomplete":
        journal.state["rows"][0]["last_close"] = None
    elif damage == "future":
        row = journal.state["rows"][0]
        row["latest_signal"] = "BUY"
        row["signal_date"] = "2099-01-01"
        row["recent_signals"] = [{"date": "2099-01-01", "direction": "BUY"}]
    else:
        journal.state["rows"][4]["error"] = None
    monkeypatch.setattr(
        signal_scan, "evaluate_signals", lambda *_: pytest.fail("must validate before compute")
    )
    with checkpoint_scope(journal), pytest.raises(ValueError, match="检查点"):
        run_scan(bars, targets, 10)
    assert journal.reused == 0


def test_complete_and_empty_scans_do_not_invent_work(monkeypatch):
    bars, targets = scan_data()
    journal = Journal()
    with checkpoint_scope(journal):
        expected = run_scan(bars, targets, 10)
    monkeypatch.setattr(
        signal_scan, "evaluate_signals", lambda *_: pytest.fail("already completed")
    )
    with checkpoint_scope(journal):
        assert without_elapsed(run_scan(bars, targets, 10)) == without_elapsed(expected)
    assert journal.reused == len(targets)
    empty = Journal()
    with checkpoint_scope(empty):
        assert run_scan({}, [], 10)["total"] == 0
    assert empty.state is None and empty.reused == 0


def _scan_child(path, lease, pause, ready, output):
    store = TaskStore(Path(path))
    value = store.load_input(lease, execution_version="scan-test-v1")
    journal = TaskCheckpoints(store, lease, "scan-test-v1")
    original_save, original_evaluate = journal.save, signal_scan.evaluate_signals
    calls = []

    def save_then_pause(key, state):
        original_save(key, state)
        if len(state["rows"]) == 2:
            ready.set()
            multiprocessing.Event().wait(30)
            raise AssertionError("parent did not kill interrupted scanner")

    def counted(*args):
        calls.append(True)
        return original_evaluate(*args)

    signal_scan.evaluate_signals = counted
    if pause:
        journal.save = save_then_pause
    with checkpoint_scope(journal):
        result = dispatch_task(value)
    output.put((result, len(calls)))


def test_actual_process_death_restores_only_remaining_scan_targets(tmp_path):
    bars, targets = scan_data()
    value = scan_task_input("scan-test-v1", SignalScanRequest(window_bars=10), bars, targets)
    store = TaskStore(tmp_path / "tasks.db")
    record, _ = store.submit("alice", value)
    lease = store.claim("scan-test-v1", "first")
    context = multiprocessing.get_context("spawn")
    ready, output = context.Event(), context.Queue()
    first = context.Process(target=_scan_child, args=(store.path, lease, True, ready, output))
    second = None
    try:
        first.start()
        assert ready.wait(20)
        first.kill()
        first.join(10)
        assert first.exitcode is not None and first.exitcode != 0
        assert store.summary("alice", record["task_id"])["checkpoint_scan_targets"] == 2
        store.requeue_after_exit(lease, reason="supervisor_lost")
        new = store.claim("scan-test-v1", "second")
        second = context.Process(target=_scan_child, args=(store.path, new, False, ready, output))
        second.start()
        result, count = output.get(timeout=30)
        second.join(10)
        assert second.exitcode == 0 and count == 2
        assert without_elapsed(result) == without_elapsed(dispatch_task(value))
        state = store.summary("alice", record["task_id"])
        assert state["checkpoint_scan_targets"] == 6 and state["resumed_scan_targets"] == 2
        assert state["checkpoint_grid_points"] == state["resumed_grid_points"] == 0
    finally:
        for child in (first, second):
            if child is not None and child.is_alive():
                child.kill()
                child.join(5)
        output.close()
        output.join_thread()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX independent worker protocol")
def test_real_supervised_scanner_resumes_after_shutdown(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    first = TaskSupervisor(store, owner_active=lambda _: True)
    second = None
    try:
        bars, targets = scan_data(rows=600)
        targets = [deepcopy(targets[0]) for _ in range(60)]
        value = scan_task_input(
            first.version,
            SignalScanRequest(window_bars=10),
            bars={key: frame for key, frame in bars.items() if frame is not None},
            targets=targets,
        )
        record, _ = store.submit("alice", value)
        task_id = record["task_id"]
        first.step()
        child = first._running[task_id].process
        deadline = time.monotonic() + 20
        state = store.summary("alice", task_id)
        while time.monotonic() < deadline and state["checkpoint_scan_targets"] == 0:
            assert child.poll() is None
            time.sleep(0.005)
            state = store.summary("alice", task_id)
        saved = state["checkpoint_scan_targets"]
        assert 0 < saved < len(targets)
        child.send_signal(signal.SIGSTOP)
        first.close()
        assert store.summary("alice", task_id)["status"] == "pending"
        second = TaskSupervisor(store, owner_active=lambda _: True)
        second.step()
        deadline = time.monotonic() + 40
        while second.active_count and time.monotonic() < deadline:
            second.step(admit=False)
            time.sleep(0.01)
        assert second.active_count == 0
        result = store.get("alice", task_id)
        assert result["status"] == "done", result
        assert result["resumed_scan_targets"] >= saved
        assert result["checkpoint_scan_targets"] == 0
        assert without_elapsed(result["result"]) == without_elapsed(dispatch_task(value))
    finally:
        first.close()
        if second is not None:
            second.close()


@pytest.mark.parametrize("source_version", [4, 5])
def test_schema4_5_migration_preserves_existing_checkpoint(tmp_path, source_version):
    bars, _ = scan_data()
    store = TaskStore(tmp_path / "tasks.db")
    if source_version == 4:
        request = OptimizeBacktestRequest(
            strategy="ma_cross", symbol="SZ:300750", param_grid={"fast": [2], "slow": [5]}
        )
        value = TaskInput(
            "optimize", "scan-test-v1", request.model_dump(), (bars[("SZ:300750", "DAY")],), {}
        )
    else:
        bars, targets = scan_data()
        value = scan_task_input("scan-test-v1", SignalScanRequest(), bars, targets)
    store.submit("alice", value)
    lease = store.claim("scan-test-v1", "worker")
    journal = TaskCheckpoints(store, lease, "scan-test-v1")
    with checkpoint_scope(journal):
        expected = dispatch_task(value)
    with store.connect() as conn:
        before = tuple(
            conn.execute(
                "SELECT payload,checkpoint,checkpoint_fingerprint,retained_bytes FROM tasks"
            ).fetchone()
        )
        if source_version == 4:
            conn.execute("ALTER TABLE tasks DROP COLUMN checkpoint_scan_targets")
            conn.execute("ALTER TABLE tasks DROP COLUMN resumed_scan_targets")
        conn.execute("ALTER TABLE tasks DROP COLUMN checkpoint_signal_bars")
        conn.execute("ALTER TABLE tasks DROP COLUMN resumed_signal_bars")
        for unit in ("order_signals", "pnl_trades", "equity_bars"):
            for prefix in ("checkpoint", "resumed"):
                conn.execute(f"ALTER TABLE tasks DROP COLUMN {prefix}_{unit}")
        conn.execute(f"PRAGMA user_version={source_version}")
    migrated = TaskStore(store.path)
    restored = TaskCheckpoints(migrated, lease, "scan-test-v1")
    if source_version == 4:
        assert restored.restore("optimizer-grid/ma_cross")["schema"] == "optimizer-grid-v1"
    else:
        assert restored.restore("signal-scan/targets")["schema"] == "signal-scan-rows-v1"
    with migrated.connect() as conn:
        assert (
            tuple(
                conn.execute(
                    "SELECT payload,checkpoint,checkpoint_fingerprint,retained_bytes FROM tasks"
                ).fetchone()
            )
            == before
        )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    with checkpoint_scope(restored):
        assert without_elapsed(dispatch_task(value)) == without_elapsed(expected)
