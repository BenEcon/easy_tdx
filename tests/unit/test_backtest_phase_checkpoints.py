"""Exact execution/accounting recovery, including no-fill and rejected signals."""

import multiprocessing
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest import engine as engine_module
from easy_tdx.backtest import portfolio as portfolio_module
from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.orders import OrderSimulator
from easy_tdx.backtest.portfolio import PortfolioTracker
from easy_tdx.backtest.slippage import FixedSlippage
from easy_tdx.backtest.strategies.builtin import MaCrossStrategy
from easy_tdx.backtest.types import Signal
from easy_tdx.checkpoints import checkpoint_scope
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


def data(rows=200):
    prices = 30 + 3 * np.sin(np.arange(rows) * 1.2)
    return _ohlcv_to_df(
        [
            dict(
                datetime=str(day.date()),
                open=float(price),
                close=float(price + 0.2),
                high=float(price + 1),
                low=float(price - 1),
                vol=10000,
                amount=float(price * 10000),
            )
            for day, price in zip(pd.bdate_range("2025-01-06", periods=rows), prices)
        ]
    )


def inputs(frame):
    signals = [
        Signal(
            int(day.strftime("%Y%m%d")),
            "BUY" if index % 2 == 0 else "SELL",
            100000000 if index % 13 == 0 else 100,
            price=float(frame.iloc[index]["close"]) if index % 7 == 0 else None,
            source="stop" if index % 17 == 0 else "strategy",
        )
        for index, day in enumerate(frame["datetime"])
    ]
    signals[11].datetime = 19990101  # no matching bar; still a processed input
    signals[-1].source = "stop"  # preserve last-bar stop fallback
    signals.append(Signal(int(frame.iloc[-1]["datetime"].strftime("%Y%m%d")), "BUY", 100))
    return signals


class Journal:
    def __init__(self, schema, fail_at=128):
        self.entries = {}
        self.reused = {}
        self.schema = schema
        self.fail_at = fail_at

    def restore(self, key):
        return deepcopy(self.entries.get(key))

    def save(self, key, state):
        if state["schema"] == self.schema and state.get("completed_units") == self.fail_at:
            raise OSError("phase checkpoint unavailable")
        self.entries[key] = deepcopy(state)

    def used(self, key, count):
        self.reused[key] = count


@pytest.mark.parametrize("execution", ["next_open", "next_close"])
@pytest.mark.parametrize("mode", ["full", "fixed", "percent"])
@pytest.mark.parametrize("reject", ["reduce", "skip"])
def test_matching_resume_keeps_rejections_skips_prices_and_costs(
    monkeypatch, execution, mode, reject
):
    frame = data()
    frame.index = pd.RangeIndex(100, 100 + len(frame))
    signals = inputs(frame)
    if mode == "percent":
        for item in signals:
            item.size = 0.4
    sim = OrderSimulator(
        frame,
        execution=execution,
        position_mode=mode,
        reject_policy=reject,
        commission=0.0007,
        slippage=0.02,
    )
    expected = sim.simulate(signals, 100000.0, 100.0)
    journal = Journal("backtest-order-signals-v1")
    with checkpoint_scope(journal), pytest.raises(OSError):
        sim.simulate(signals, 100000.0, 100.0, checkpoint_key="orders")
    assert journal.entries["orders"]["completed_units"] == 64
    assert journal.entries["orders"]["state"]["processed"][11] is None
    seen = []
    original = OrderSimulator._simulate_signal

    def count(self, signal, *args, **kwargs):
        seen.append(signal)
        return original(self, signal, *args, **kwargs)

    monkeypatch.setattr(OrderSimulator, "_simulate_signal", count)
    journal.fail_at = None
    with checkpoint_scope(journal):
        actual = sim.simulate(signals, 100000.0, 100.0, checkpoint_key="orders")
    assert seen == signals[64:]
    assert [asdict(item) for item in actual] == [asdict(item) for item in expected]
    assert journal.reused == {"orders": 64}
    seen.clear()
    with checkpoint_scope(journal):
        assert sim.simulate(signals, 100000.0, 100.0, checkpoint_key="orders") == expected
    assert not seen
    assert journal.reused["orders"] == len(signals)  # includes no-fill input


def raw_trades(frame):
    return OrderSimulator(frame, position_mode="fixed", reject_policy="skip").simulate(
        inputs(frame), 100000.0, 100.0
    )


def test_cost_basis_resumes_real_partial_position_without_recalculating_prefix(monkeypatch):
    frame = data()
    trades = raw_trades(frame)
    assert len(trades) > 128
    engine = BacktestEngine(MaCrossStrategy)
    expected = engine._compute_pnls(deepcopy(trades))
    journal = Journal("backtest-pnl-trades-v1")
    with checkpoint_scope(journal), pytest.raises(OSError):
        engine._compute_pnls(deepcopy(trades), df=frame, checkpoint_key="pnl")
    assert journal.entries["pnl"]["completed_units"] == 64
    calls = []
    monkeypatch.setattr(engine_module, "computation_checkpoint", lambda: calls.append(True))
    journal.fail_at = None
    with checkpoint_scope(journal):
        actual = engine._compute_pnls(deepcopy(trades), df=frame, checkpoint_key="pnl")
    assert len(calls) == len(trades) - 64
    assert actual == expected
    assert journal.reused == {"pnl": 64}


@pytest.mark.parametrize("cash", [100000, 100000.12345678901])
def test_equity_restores_exact_typed_prefix_and_only_applies_remaining_bars(monkeypatch, cash):
    frame = data()
    trades = raw_trades(frame)
    expected = PortfolioTracker(frame, initial_cash=cash)
    expected.apply_trades(trades)
    journal = Journal("backtest-equity-bars-v1")
    with checkpoint_scope(journal), pytest.raises(OSError):
        PortfolioTracker(frame, initial_cash=cash).apply_trades(trades, checkpoint_key="equity")
    saved = journal.entries["equity"]
    assert saved["completed_units"] == 64
    calls = []
    monkeypatch.setattr(portfolio_module, "computation_checkpoint", lambda: calls.append(True))
    journal.fail_at = None
    actual = PortfolioTracker(frame, initial_cash=cash)
    with checkpoint_scope(journal):
        actual.apply_trades(trades, checkpoint_key="equity")
    assert len(calls) == len(trades) + len(frame) - 64
    assert journal.reused == {"equity": 64}
    pd.testing.assert_frame_equal(actual.equity_curve, expected.equity_curve, check_exact=True)
    pd.testing.assert_frame_equal(actual.positions, expected.positions, check_exact=True)
    assert actual._cash.dtype == expected._cash.dtype


@pytest.mark.parametrize("phase", ["orders", "pnl", "equity"])
@pytest.mark.parametrize("damage", ["cursor", "input", "state", "partial", "nan"])
def test_phase_corruption_is_rejected_not_restarted(phase, damage):
    frame = data()
    trades, signals = raw_trades(frame), inputs(frame)
    schema = {"orders": "order-signals", "pnl": "pnl-trades", "equity": "equity-bars"}[phase]
    journal = Journal(f"backtest-{schema}-v1")

    def run():
        if phase == "orders":
            return OrderSimulator(frame).simulate(signals, 100000.0, 0.0, checkpoint_key=phase)
        if phase == "pnl":
            return BacktestEngine(MaCrossStrategy)._compute_pnls(
                deepcopy(trades), df=frame, checkpoint_key=phase
            )
        return PortfolioTracker(frame).apply_trades(trades, checkpoint_key=phase)

    with checkpoint_scope(journal), pytest.raises(OSError):
        run()
    saved = journal.entries[phase]
    if damage == "cursor":
        saved["completed_units"] = True
    elif damage == "input":
        saved["input_records"][0]["direction"] = "OTHER"
    elif damage == "state":
        saved["state"]["unknown"] = 0
    else:
        field = {"orders": "processed", "pnl": "processed", "equity": "cash"}[phase]
        if damage == "partial":
            saved["state"][field].pop()
        elif phase == "equity":
            saved["state"][field][0] = np.float64("nan")
        else:
            saved["state"]["cash" if phase == "orders" else "position_cost"] = float("nan")
    journal.fail_at = None
    with checkpoint_scope(journal), pytest.raises(ValueError):
        run()
    assert not journal.reused


def test_custom_slippage_does_not_claim_stateless_execution_resume():
    frame = data()
    journal = Journal("backtest-order-signals-v1", fail_at=None)
    sim = OrderSimulator(frame, slippage_model=FixedSlippage(0.03))
    with checkpoint_scope(journal):
        sim.simulate(inputs(frame), 100000.0, 0.0, checkpoint_key="orders")
    assert not journal.entries


def test_valid_numeric_cash_that_disagrees_with_trades_is_rejected():
    frame = data()
    journal = Journal("backtest-order-signals-v1")
    sim = OrderSimulator(frame)
    with checkpoint_scope(journal), pytest.raises(OSError):
        sim.simulate(inputs(frame), 100000.0, 0.0, checkpoint_key="orders")
    journal.entries["orders"]["state"]["cash"] += 1
    with checkpoint_scope(journal), pytest.raises(ValueError, match="成交前缀"):
        sim.simulate(inputs(frame), 100000.0, 0.0, checkpoint_key="orders")
    assert not journal.reused


def frozen(kind):
    frame = data(600)
    if kind == "backtest":
        request = BacktestRequest(
            strategy="ma_cross", symbol="SZ:300750", params={"fast": 2, "slow": 5}
        )
        frames = (frame,)
    elif kind == "portfolio":
        request = PortfolioBacktestRequest(
            strategy="ma_cross", stocks=["SZ:300750", "SH:600699"], params={"fast": 2, "slow": 5}
        )
        frames = (frame, frame)
    else:
        request = MultiStrategyBacktestRequest(
            items=[
                {"strategy": "ma_cross", "symbol": "SZ:300750", "params": {"fast": 2, "slow": 5}},
                {"strategy": "ma_cross", "symbol": "SH:600699", "params": {"fast": 2, "slow": 5}},
            ]
        )
        frames = (frame, frame)
    return TaskInput(kind, "phase-test-v1", request.model_dump(), frames, {})


def test_schema6_real_signal_checkpoint_migrates_without_rewriting_old_state(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    value = frozen("backtest")
    record, _ = store.submit("alice", value)
    lease = store.claim(value.execution_version, "first")
    journal = TaskCheckpoints(store, lease, value.execution_version)
    strategy = MaCrossStrategy(fast=2, slow=5)
    with checkpoint_scope(journal):
        BacktestEngine(strategy, cash=value.request["cash"])._generate_signals(
            value.frames[0], None, checkpoint_key="backtest/signals"
        )
    with store.connect() as conn:
        before = tuple(
            conn.execute(
                "SELECT payload,checkpoint,checkpoint_fingerprint,retained_bytes FROM tasks"
            ).fetchone()
        )
        for unit in ("order_signals", "pnl_trades", "equity_bars"):
            for prefix in ("checkpoint", "resumed"):
                conn.execute(f"ALTER TABLE tasks DROP COLUMN {prefix}_{unit}")
        conn.execute("PRAGMA user_version=6")
    migrated = TaskStore(store.path)
    with migrated.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        assert (
            tuple(
                conn.execute(
                    "SELECT payload,checkpoint,checkpoint_fingerprint,retained_bytes FROM tasks"
                ).fetchone()
            )
            == before
        )
    with checkpoint_scope(TaskCheckpoints(migrated, lease, value.execution_version)):
        actual = dispatch_task(value)
    assert actual == dispatch_task(value)
    state = migrated.summary("alice", record["task_id"])
    assert state["resumed_signal_bars"] == len(value.frames[0])
    assert state["checkpoint_equity_bars"] == len(value.frames[0])
    assert state["resumed_equity_bars"] == 0  # not present in the old checkpoint


def _child(path, lease, phase, pause, ready, output):
    store = TaskStore(Path(path))
    journal = TaskCheckpoints(store, lease, "phase-test-v1")
    save = journal.save

    def intercepted(key, state):
        save(key, state)
        if pause and state["schema"] == phase and state.get("completed_units") == 64:
            ready.set()
            multiprocessing.Event().wait(30)

    journal.save = intercepted
    with checkpoint_scope(journal):
        result = dispatch_task(store.load_input(lease, execution_version="phase-test-v1"))
    output.put(result)


@pytest.mark.parametrize("kind", ["backtest", "portfolio", "multi_strategy"])
@pytest.mark.parametrize(
    "phase,unit",
    [
        ("backtest-order-signals-v1", "order_signals"),
        ("backtest-pnl-trades-v1", "pnl_trades"),
        ("backtest-equity-bars-v1", "equity_bars"),
    ],
)
def test_actual_process_dies_mid_phase_and_replacement_completes_exact_result(
    tmp_path, kind, phase, unit
):
    store = TaskStore(tmp_path / "tasks.db")
    value = frozen(kind)
    record, _ = store.submit("alice", value)
    lease = store.claim(value.execution_version, "first")
    ctx = multiprocessing.get_context("spawn")
    ready, output = ctx.Event(), ctx.Queue()
    first = ctx.Process(target=_child, args=(str(store.path), lease, phase, True, ready, output))
    second = None
    try:
        first.start()
        assert ready.wait(25)
        first.terminate()
        first.join(10)
        assert not first.is_alive() and first.exitcode != 0
        assert store.summary("alice", record["task_id"])[f"checkpoint_{unit}"] == 64
        store.requeue_after_exit(lease)
        fresh = store.claim(value.execution_version, "second")
        second = ctx.Process(
            target=_child, args=(str(store.path), fresh, phase, False, ready, output)
        )
        second.start()
        result = output.get(timeout=40)
        second.join(10)
        assert second.exitcode == 0
        assert result == dispatch_task(value)
        state = store.summary("alice", record["task_id"])
        assert state[f"resumed_{unit}"] == 64
        assert state["status"] == "running"  # not published just because a phase completed
        store.finish_after_exit(fresh, result=result)
        assert store.summary("alice", record["task_id"])[f"checkpoint_{unit}"] == 0
    finally:
        for child in (first, second):
            if child is not None and child.is_alive():
                child.terminate()
                child.join(10)
        output.close()
        output.join_thread()
