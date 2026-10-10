"""Minute bars must retain causal execution, holdings and recoverable time identity."""

import multiprocessing
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.bar_time import BAR_TIME_CONTRACT, BarTimeIndex, signal_times
from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.execution import ImmediateExecution
from easy_tdx.backtest.multi_strategy_engine import MultiStrategyEngine, StrategySlot
from easy_tdx.backtest.orders import OrderSimulator
from easy_tdx.backtest.portfolio import PortfolioTracker
from easy_tdx.backtest.portfolio_engine import PortfolioBacktestEngine, StockData
from easy_tdx.backtest.strategies.builtin import MaCrossStrategy
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import Signal, Trade
from easy_tdx.checkpoints import checkpoint_scope
from easy_tdx.web.backtest_schemas import (
    BacktestRequest,
    MultiStrategyBacktestRequest,
    PortfolioBacktestRequest,
)
from easy_tdx.web.bar_snapshot import annotate_snapshot
from easy_tdx.web.task_checkpoints import TaskCheckpoints
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_store import TaskStore


def frame(minutes=5, *, cross_day=False, tz=None, rows=8):
    dates = pd.date_range("2026-10-09 09:35", periods=rows, freq=f"{minutes}min", tz=tz)
    if cross_day:
        dates = dates[:4].append(dates[4:] + pd.Timedelta(days=3))
    values = np.arange(rows, dtype=float) + 20
    result = pd.DataFrame(
        dict(
            datetime=dates,
            open=values,
            close=values + 0.2,
            high=values + 1,
            low=values - 1,
            vol=10000,
            amount=100000,
        )
    )
    result.index = [f"bar-{index * 3}" for index in range(rows)]
    return result


class TimedOrders(Strategy):
    def init(self):
        pass

    def next(self):
        if self._bar_index == 3:
            self.buy(size=100)
        elif self._bar_index == 5:
            self.sell(size=100)


@pytest.mark.parametrize("minutes", [5, 15, 30, 60])
@pytest.mark.parametrize("cross_day", [False, True])
@pytest.mark.parametrize("execution", ["next_open", "next_close", "custom"])
def test_signals_trade_on_the_correct_next_bar_and_hold_only_between_fills(
    minutes, cross_day, execution
):
    data = frame(minutes, cross_day=cross_day)
    engine = BacktestEngine(
        TimedOrders,
        cash=100000.0,
        position_mode="fixed",
        execution="next_open" if execution == "custom" else execution,
        execution_model=ImmediateExecution() if execution == "custom" else None,
    )
    signals = engine._generate_signals(data, None)
    assert [sig.datetime for sig in signals] == list(data["datetime"].iloc[[3, 5]])
    result = engine.run(data)
    assert list(result.trades["datetime"]) == list(data["datetime"].iloc[[4, 6]])
    assert list(result.trades["price"]) == ([24.2, 26.2] if execution == "next_close" else [24, 26])
    assert list(result.positions["size"]) == [0, 0, 0, 0, 100, 100, 0, 0]
    assert list(result.equity_curve["cash"].iloc[:4]) == [100000.0] * 4
    assert (
        list(result.equity_curve["cash"].iloc[4:6])
        == [100000.0 - result.trades.iloc[0].price * 100 - 5] * 2
    )
    assert result.trades.iloc[1].pnl == pytest.approx(
        200 - 5 - 5 - result.trades.iloc[1].price * 0.1
    )
    # Independent prefix run cannot contain a later fill or change earlier positions.
    prefix = engine.run(data.iloc[:6])
    pd.testing.assert_frame_equal(prefix.trades, result.trades.iloc[:1], check_exact=True)
    pd.testing.assert_frame_equal(prefix.positions, result.positions.iloc[:6], check_exact=True)


@pytest.mark.parametrize("tz", [None, "Asia/Shanghai", "America/New_York"])
def test_full_timestamp_preserves_timezone_and_subseconds(tz):
    data = frame(tz=tz)
    data["datetime"] += pd.Timedelta(nanoseconds=123)
    result = BacktestEngine(TimedOrders, position_mode="fixed").run(data)
    assert list(result.trades.datetime) == list(data.datetime.iloc[[4, 6]])
    assert all(value.nanosecond == 123 for value in result.trades.datetime)
    assert list(result.positions["size"]) == [0, 0, 0, 0, 100, 100, 0, 0]


def test_dst_repeated_wall_time_resolves_distinct_instants():
    dates = pd.date_range("2026-11-01 00:30", periods=6, freq="30min", tz="America/New_York")
    index = BarTimeIndex(pd.Series(dates))
    assert dates[1].hour == dates[3].hour == 1
    assert index.get(dates[1]) == 1
    assert index.get(dates[3]) == 3
    assert index.get(dates[3].tz_convert("UTC")) == 3
    with pytest.raises(ValueError, match="完整时间"):
        index.get(20261101)


def test_midnight_with_other_bars_is_not_collapsed_to_date():
    column = pd.Series(pd.date_range("2026-10-09", periods=3, freq="5min"))
    assert signal_times(column) == list(column)
    assert BarTimeIndex(column).get(column[0]) == 0
    with pytest.raises(ValueError, match="完整时间"):
        BarTimeIndex(column).get(20261009)


def test_date_only_intraday_signal_and_trade_rejected_instead_of_guessed():
    data = frame()
    with pytest.raises(ValueError, match="完整时间"):
        OrderSimulator(data).simulate([Signal(20261009, "BUY", 100)], 100000, 0)
    with pytest.raises(ValueError, match="完整时间"):
        PortfolioTracker(data).apply_trades([Trade(20261009, "BUY", 100, 24, 5, 0)])


def test_daily_integer_and_midnight_timestamp_compatibility():
    for values in [
        [20261009, 20261012, 20261013],
        pd.to_datetime(["2026-10-09", "2026-10-12", "2026-10-13"]),
    ]:
        times = signal_times(pd.Series(values))
        assert times == [20261009, 20261012, 20261013]
        index = BarTimeIndex(pd.Series(values))
        assert index.get(20261012) == 1
        assert index.get(pd.Timestamp("2026-10-12")) == 1
        assert index.get(pd.Timestamp("2026-10-12 09:35")) is None


def test_intraday_stop_keeps_trigger_bar_and_executes_next_bar_adverse_gap():
    class Stopped(Strategy):
        def init(self):
            pass

        def next(self):
            if self._bar_index == 1:
                self.buy(size=100, stop_loss=19)

    data = frame()
    data.iloc[4, data.columns.get_loc("low")] = 18
    data.iloc[5, data.columns.get_loc("open")] = 17
    engine = BacktestEngine(Stopped, position_mode="fixed")
    signals = engine._generate_signals(data, None)
    assert [(sig.datetime, sig.source) for sig in signals] == [
        (data.datetime.iloc[1], "strategy"),
        (data.datetime.iloc[4], "stop"),
    ]
    result = engine.run(data)
    assert list(result.trades.datetime) == list(data.datetime.iloc[[2, 5]])
    assert list(result.trades.price) == [22, 17]
    assert list(result.positions["size"]) == [0, 0, 100, 100, 100, 0, 0, 0]


@pytest.mark.parametrize("kind", ["portfolio", "multi_strategy"])
def test_combined_equity_keeps_minute_rows_and_individual_holdings(kind):
    data = frame(cross_day=True)
    if kind == "portfolio":
        result = PortfolioBacktestEngine(
            TimedOrders, [StockData("300750", "SZ", data), StockData("600699", "SH", data)]
        ).run()
    else:
        result = MultiStrategyEngine(
            [
                StrategySlot("one", "SZ:300750", TimedOrders(), data),
                StrategySlot("two", "SH:600699", TimedOrders(), data),
            ]
        ).run()
    assert list(result.combined_equity.datetime) == list(data.datetime)
    for individual in result.individual_results.values():
        assert list(individual.trades.datetime) == list(data.datetime.iloc[[4, 6]])
        bought = individual.trades.iloc[0]["size"]
        assert bought > 0  # these engines retain their existing full-position sizing
        assert list(individual.positions["size"]) == [0, 0, 0, 0, bought, bought, 0, 0]


class Journal:
    def __init__(self):
        self.entries, self.used_counts = {}, {}

    def restore(self, key):
        return deepcopy(self.entries.get(key))

    def save(self, key, state):
        self.entries[key] = deepcopy(state)

    def used(self, key, count):
        self.used_counts[key] = count


@pytest.mark.parametrize("part", ["signals", "orders", "pnl", "equity"])
def test_old_date_only_checkpoint_contract_is_not_accepted(part):
    data = frame(rows=160)
    data["close"] = 30 + 3 * np.sin(np.arange(len(data)) * 1.2)
    journal = Journal()
    with checkpoint_scope(journal):
        BacktestEngine(MaCrossStrategy(fast=2, slow=5)).run(data, checkpoint_key="test")
    key = "test" if part == "signals" else "test/" + part
    assert journal.entries[key].pop("bar_time_contract") == BAR_TIME_CONTRACT
    journal.used_counts.clear()
    with checkpoint_scope(journal), pytest.raises(ValueError, match="不匹配"):
        BacktestEngine(MaCrossStrategy(fast=2, slow=5)).run(data, checkpoint_key="test")
    assert key not in journal.used_counts


def frozen(kind):
    # Web inputs use exchange-local naive times; timezone support is tested at
    # the core engine boundary, not by relaxing the Web provenance contract.
    data = frame(rows=600)
    price = 30 + 3 * np.sin(np.arange(len(data)) * 1.2)
    for name, offset in [("open", 0), ("close", 0.2), ("high", 1), ("low", -1)]:
        data[name] = price + offset
    # Freeze evidence too, just as the HTTP intake does. Otherwise each direct
    # dispatch correctly reports a different observation time for unknown input.
    data.attrs["snapshot_metadata"] = annotate_snapshot(
        data.to_dict("records"),
        "MIN_5",
        source="SYNTHETIC_TEST",
        requested_adjust="QFQ",
        actual_adjust="UNKNOWN",
        bar_time="end",
        now=pd.Timestamp("2026-10-13").to_pydatetime(),
    )["metadata"]
    params = {"fast": 2, "slow": 5}
    if kind == "backtest":
        request = BacktestRequest(
            strategy="ma_cross", symbol="SZ:300750", category="MIN_5", params=params
        )
        frames = (data,)
    elif kind == "portfolio":
        request = PortfolioBacktestRequest(
            strategy="ma_cross", stocks=["SZ:300750", "SH:600699"], category="MIN_5", params=params
        )
        frames = (data, data)
    else:
        request = MultiStrategyBacktestRequest(
            items=[
                {"strategy": "ma_cross", "symbol": symbol, "category": "MIN_5", "params": params}
                for symbol in ["SZ:300750", "SH:600699"]
            ]
        )
        frames = (data, data)
    return TaskInput(kind, "intraday-identity-test", request.model_dump(), frames, {})


def _child(path, lease, phase, pause, ready, output):
    store = TaskStore(Path(path))
    journal = TaskCheckpoints(store, lease, "intraday-identity-test")
    save = journal.save

    def intercepted(key, state):
        save(key, state)
        completed = state.get("completed_bars", state.get("completed_units"))
        if pause and state["schema"] == phase and completed == 64:
            ready.set()
            multiprocessing.Event().wait(30)

    journal.save = intercepted
    with checkpoint_scope(journal):
        result = dispatch_task(store.load_input(lease, execution_version="intraday-identity-test"))
    output.put(result)


@pytest.mark.parametrize("kind", ["backtest", "portfolio", "multi_strategy"])
@pytest.mark.parametrize(
    "phase,unit",
    [
        ("backtest-signal-bars-v1", "signal_bars"),
        ("backtest-order-signals-v1", "order_signals"),
        ("backtest-pnl-trades-v1", "pnl_trades"),
        ("backtest-equity-bars-v1", "equity_bars"),
    ],
)
def test_actual_process_recovery_preserves_full_minute_identity(tmp_path, kind, phase, unit):
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
        assert store.summary("alice", record["task_id"])[f"resumed_{unit}"] == 64
    finally:
        for child in (first, second):
            if child is not None and child.is_alive():
                child.terminate()
                child.join(10)
        output.close()
        output.join_thread()
