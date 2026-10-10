"""Resume actual signal-loop state, not a bar index over a reset strategy."""

import multiprocessing
import signal
import sys
import time
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategies import get_registry
from easy_tdx.backtest.strategies.builtin import MaCrossStrategy
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.checkpoints import checkpoint_scope
from easy_tdx.computation import ComputationControl, ComputationStopped, computation_scope
from easy_tdx.web.backtest_schemas import (
    BacktestRequest,
    MultiStrategyBacktestRequest,
    PortfolioBacktestRequest,
)
from easy_tdx.web.routers.backtest import _ohlcv_to_df
from easy_tdx.web.task_checkpoints import TaskCheckpoints
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_store import TaskStore
from easy_tdx.web.task_supervisor import TaskSupervisor


def frame(rows=160):
    prices = 30 + np.sin(np.arange(rows) / 4) * 3
    return _ohlcv_to_df(
        [
            dict(
                datetime=str(day.date()),
                open=float(price),
                close=float(price),
                high=float(price + 1),
                low=float(price - 1),
                vol=1000,
                amount=10000,
            )
            for day, price in zip(pd.bdate_range("2025-01-06", periods=rows), prices)
        ]
    )


class Journal:
    def __init__(self, fail_at=None):
        self.entries = {}
        self.used_counts = {}
        self.fail_at = fail_at

    def restore(self, key):
        return deepcopy(self.entries.get(key))

    def save(self, key, state):
        if self.fail_at is not None and state.get("completed_bars") == self.fail_at:
            raise OSError("checkpoint unavailable")
        self.entries[key] = deepcopy(state)

    def used(self, key, count):
        self.used_counts[key] = count


class StatefulStops(Strategy):
    """Counter-dependent strategy with a live stop precisely at the checkpoint."""

    calls = []

    def init(self):
        self.counter = 0

    def next(self):
        self.calls.append(self._bar_index)
        self.counter += 1
        if self.counter % 63 == 0 and self.position["size"] == 0:
            self.buy(size=100, stop_loss=27, take_profit=33)
        elif self.counter % 71 == 0 and self.position["size"] > 0:
            self.sell()

    def checkpoint_identity(self):
        return {"contract": "test-counter-v1"}

    def checkpoint_state(self):
        return {"counter": self.counter}

    def restore_checkpoint_state(self, state):
        if set(state) != {"counter"} or type(state["counter"]) is not int:
            raise ValueError("invalid counter")
        self.counter = state["counter"]


def assert_result_equal(actual, expected):
    pd.testing.assert_series_equal(
        pd.Series(actual.performance), pd.Series(expected.performance), check_exact=True
    )
    assert actual.config == expected.config
    assert actual.diagnostic == expected.diagnostic
    for name in ("equity_curve", "trades", "positions"):
        pd.testing.assert_frame_equal(
            getattr(actual, name), getattr(expected, name), check_exact=True
        )


@pytest.mark.parametrize("warmup", [0, 20, 80, 200])
def test_partial_state_resumes_without_rerunning_saved_bars(warmup):
    data = frame()
    expected = BacktestEngine(StatefulStops, warmup_bars=warmup).run(data)
    journal = Journal(fail_at=128)
    with checkpoint_scope(journal), pytest.raises(OSError):
        BacktestEngine(StatefulStops, warmup_bars=warmup).run(data, checkpoint_key="one")
    saved = journal.entries["one"]
    assert saved["completed_bars"] == 64
    if warmup == 0:
        assert saved["position"] == 100
        assert saved["stops"] == [{"stop_loss": 27, "take_profit": 33}]
        assert saved["state"]["counter"] == 64
    StatefulStops.calls.clear()
    journal.fail_at = None
    with checkpoint_scope(journal):
        actual = BacktestEngine(StatefulStops, warmup_bars=warmup).run(data, checkpoint_key="one")
    assert StatefulStops.calls == list(range(max(warmup, 64), len(data)))
    assert journal.used_counts == {"one": 64}
    assert_result_equal(actual, expected)
    StatefulStops.calls.clear()
    with checkpoint_scope(journal):
        complete = BacktestEngine(StatefulStops, warmup_bars=warmup).run(data, checkpoint_key="one")
    assert not StatefulStops.calls
    assert_result_equal(complete, expected)


@pytest.mark.parametrize(
    "damage",
    [
        "cursor",
        "cash",
        "position",
        "stops",
        "signals",
        "future",
        "state",
        "unknown",
        "params",
        "frame",
    ],
)
def test_invalid_checkpoint_never_becomes_restarted_or_partial_success(damage):
    data = frame()
    journal = Journal(fail_at=128)
    with checkpoint_scope(journal), pytest.raises(OSError):
        BacktestEngine(StatefulStops).run(data, checkpoint_key="one")
    saved = journal.entries["one"]
    if damage == "cursor":
        saved["completed_bars"] = True
    elif damage in {"cash", "position"}:
        saved[damage] = float("nan")
    elif damage == "stops":
        saved["stops"][0]["take_profit"] = "33"
    elif damage == "signals":
        saved["signals"][0]["direction"] = "UNKNOWN"
    elif damage == "future":
        saved["signals"][0]["datetime"] = 20990101
    elif damage == "state":
        saved["state"]["counter"] = "64"
    elif damage == "params":
        saved["identity"]["contract"] = "other"
    elif damage == "frame":
        data.loc[0, "close"] += 1
    else:
        saved["unexpected"] = True
    StatefulStops.calls.clear()
    journal.fail_at = None
    with checkpoint_scope(journal), pytest.raises(ValueError):
        BacktestEngine(StatefulStops).run(data, checkpoint_key="one")
    assert not StatefulStops.calls and not journal.used_counts


def test_ordinary_strategies_and_external_builtin_subclasses_do_not_claim_stateless_resume(
    monkeypatch,
):
    class Undeclared(StatefulStops):
        checkpoint_identity = Strategy.checkpoint_identity

    class CustomMa(MaCrossStrategy):
        pass

    assert CustomMa().checkpoint_identity() is None
    calls = []
    original = Strategy._call_next

    def counted(self):
        calls.append(self._bar_index)
        return original(self)

    monkeypatch.setattr(Strategy, "_call_next", counted)
    for strategy in (Undeclared, CustomMa):
        journal = Journal()
        with checkpoint_scope(journal):
            expected = BacktestEngine(strategy).run(frame(), checkpoint_key="unsupported")
        assert "unsupported" not in journal.entries and not journal.used_counts
        assert all(
            entry["schema"] != "backtest-signal-bars-v1" for entry in journal.entries.values()
        )
        calls.clear()
        with checkpoint_scope(journal):
            actual = BacktestEngine(strategy).run(frame(), checkpoint_key="unsupported")
        assert calls == list(range(160))  # strategy itself still runs all bars
        assert "unsupported" not in journal.used_counts
        assert_result_equal(actual, expected)  # deterministic later phases may safely resume


@pytest.mark.parametrize("name", [entry.name for entry in get_registry().all()])
def test_builtin_strategies_resume_exact_results(name):
    # Includes the actual Chanlun strategy's prefix calculation; no synthetic
    # substitution for its buy/sell arrays or underlying strict structure.
    data = frame(130)
    entry = get_registry().get(name)
    expected = BacktestEngine(entry.build({})).run(data)
    journal = Journal(fail_at=128)
    with checkpoint_scope(journal), pytest.raises(OSError):
        BacktestEngine(entry.build({})).run(data, checkpoint_key="one")
    journal.fail_at = None
    with checkpoint_scope(journal):
        actual = BacktestEngine(entry.build({})).run(data, checkpoint_key="one")
    assert journal.used_counts == {"one": 64}
    assert_result_equal(actual, expected)


def _child(path, lease, stop, ready, output):
    store = TaskStore(Path(path))
    value = store.load_input(lease, execution_version="test-bars-v1")
    journal = TaskCheckpoints(store, lease, "test-bars-v1")
    original = journal.save

    def save(key, state):
        original(key, state)
        if stop and state["completed_bars"] == 64:
            ready.set()
            # Parent terminates this exact child after observing the durable checkpoint.
            multiprocessing.Event().wait(30)

    journal.save = save
    StatefulStops.calls.clear()
    with checkpoint_scope(journal):
        result = BacktestEngine(StatefulStops).run(value.frames[0], checkpoint_key="one")
    output.put((StatefulStops.calls, result.to_json()))


def test_actual_process_death_restores_counter_stops_and_unrounded_results(tmp_path):
    data = frame()
    request = BacktestRequest(strategy="ma_cross", symbol="SZ:300750")
    store = TaskStore(tmp_path / "tasks.db")
    record, _ = store.submit(
        "alice", TaskInput("backtest", "test-bars-v1", request.model_dump(), (data,), {})
    )
    lease = store.claim("test-bars-v1", "first")
    ctx = multiprocessing.get_context("spawn")
    ready, output = ctx.Event(), ctx.Queue()
    first = ctx.Process(target=_child, args=(str(store.path), lease, True, ready, output))
    second = None
    try:
        first.start()
        assert ready.wait(20)
        first.terminate()
        first.join(10)
        assert not first.is_alive() and first.exitcode != 0
        store.requeue_after_exit(lease)
        fresh = store.claim("test-bars-v1", "second")
        second = ctx.Process(target=_child, args=(str(store.path), fresh, False, ready, output))
        second.start()
        calls, result = output.get(timeout=30)
        second.join(10)
        assert second.exitcode == 0
        assert calls == list(range(64, len(data)))
        assert result == BacktestEngine(StatefulStops).run(data).to_json()
        state = store.summary("alice", record["task_id"])
        assert state["resumed_signal_bars"] == 64 and state["checkpoint_signal_bars"] == len(data)
        assert state["resumed_grid_points"] == state["resumed_scan_targets"] == 0
    finally:
        for child in (first, second):
            if child is not None and child.is_alive():
                child.terminate()
                child.join(10)
        output.close()
        output.join_thread()


def task_value(kind, rows=160, version="test-bars-v1"):
    data = frame(rows)
    if kind == "backtest":
        request = BacktestRequest(strategy="ma_cross", symbol="SZ:300750")
        frames = (data,)
    elif kind == "portfolio":
        request = PortfolioBacktestRequest(strategy="ma_cross", stocks=["SZ:300750", "SH:600699"])
        other = data.copy(deep=True)
        other[["open", "high", "low", "close"]] *= 2
        frames = (data, other)
    else:
        request = MultiStrategyBacktestRequest(
            items=[
                {"strategy": "ma_cross", "symbol": "SZ:300750", "params": {"fast": 2, "slow": 5}},
                {"strategy": "rsi_reversal", "symbol": "SH:600699", "params": {"n": 7}},
            ]
        )
        frames = (data, data)
    return TaskInput(kind, version, request.model_dump(), frames, {})


@pytest.mark.parametrize("kind", ["backtest", "portfolio", "multi_strategy"])
def test_real_dispatch_complete_signal_prefix_skips_all_next_calls(tmp_path, monkeypatch, kind):
    value = task_value(kind)
    expected = dispatch_task(value)
    store = TaskStore(tmp_path / "tasks.db")
    record, _ = store.submit("alice", value)
    lease = store.claim(value.execution_version, "first")
    with checkpoint_scope(TaskCheckpoints(store, lease, value.execution_version)):
        assert dispatch_task(value) == expected
    store.requeue_after_exit(lease)
    fresh = store.claim(value.execution_version, "second")
    monkeypatch.setattr(
        Strategy, "_call_next", lambda *_: pytest.fail("saved bars must not replay")
    )
    with checkpoint_scope(TaskCheckpoints(store, fresh, value.execution_version)):
        assert dispatch_task(value) == expected
    state = store.summary("alice", record["task_id"])
    assert state["resumed_signal_bars"] == sum(len(item) for item in value.frames)
    assert state["status"] == "running"  # signal completion is not whole-task completion
    store.finish_after_exit(fresh, result=expected)
    assert store.summary("alice", record["task_id"])["checkpoint_signal_bars"] == 0


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX worker recovery")
@pytest.mark.parametrize("kind", ["backtest", "portfolio", "multi_strategy"])
def test_actual_supervisor_replacement_resumes_signal_bars(tmp_path, kind):
    store = TaskStore(tmp_path / "tasks.db")
    first = TaskSupervisor(store, owner_active=lambda _: True)
    second = None
    try:
        value = task_value(kind, rows=2000, version=first.version)
        record, _ = store.submit("alice", value)
        task_id = record["task_id"]
        first.step()
        child = first._running[task_id].process
        deadline = time.monotonic() + 20
        saved = 0
        while time.monotonic() < deadline and not saved:
            assert child.poll() is None
            saved = store.summary("alice", task_id)["checkpoint_signal_bars"]
            time.sleep(0.002)
        assert 0 < saved < sum(len(item) for item in value.frames)
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
        state = store.get("alice", task_id)
        assert state["status"] == "done", state
        assert state["resumed_signal_bars"] >= saved
        assert state["checkpoint_signal_bars"] == 0
        assert state["result"] == dispatch_task(value)
    finally:
        first.close()
        if second is not None:
            second.close()


def test_changed_commission_cannot_consume_old_position_estimate():
    journal = Journal(fail_at=128)
    data = frame()
    with checkpoint_scope(journal), pytest.raises(OSError):
        BacktestEngine(MaCrossStrategy()).run(data, checkpoint_key="one")
    with checkpoint_scope(journal), pytest.raises(ValueError, match="配置"):
        BacktestEngine(MaCrossStrategy(), commission=0.1).run(data, checkpoint_key="one")
    assert not journal.used_counts


@pytest.mark.parametrize("reason", ["cancelled", "timed_out"])
def test_cancelled_or_timed_out_computation_cannot_consume_signal_checkpoint(reason):
    journal = Journal(fail_at=128)
    data = frame()
    with checkpoint_scope(journal), pytest.raises(OSError):
        BacktestEngine(StatefulStops).run(data, checkpoint_key="one")
    original = deepcopy(journal.entries)
    control = ComputationControl()
    with pytest.raises(ComputationStopped), checkpoint_scope(journal), computation_scope(control):
        control.request(reason)
        BacktestEngine(StatefulStops).run(data, checkpoint_key="one")
    assert not journal.used_counts and journal.entries == original
