"""Run-local matching index, with exact intraday identity and legacy daily support."""

from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest import bar_time, orders
from easy_tdx.backtest.orders import OrderSimulator
from easy_tdx.backtest.slippage import FixedSlippage
from easy_tdx.backtest.types import Signal
from easy_tdx.computation import ComputationStopped


class LegacyLookup(OrderSimulator):
    """Uses a fresh lookup per signal, without the run-local index."""


def frame(values):
    result = pd.DataFrame({"datetime": values})
    result["open"] = np.arange(len(result), dtype=float) + 20
    result["close"] = result["open"] + 0.2
    result["high"] = result["open"] + 1
    result["low"] = result["open"] - 1
    result["vol"] = 10000
    result.index = [f"row-{index * 2}" for index in range(len(result))]
    return result


@pytest.mark.parametrize(
    "values,dates,indexed",
    [
        ([20260103, 20260101, 20260101, 20260102], [20260101, 20260103, 0], True),
        (
            pd.Series([20260103, 20260101, 20260101, 20260102], dtype="Int64"),
            [20260101, np.int64(20260103), 0],
            True,
        ),
        (
            pd.Series([2**63 + 5, 2**63 + 9, 2**63 + 5], dtype="uint64"),
            [2**63 + 5, 2**63 + 9, 0],
            True,
        ),
        (
            pd.to_datetime(["2026-01-03", "2026-01-01", "2026-01-01", "2026-01-02"]),
            [20260101, 20260103, 0],
            True,
        ),
        (
            pd.date_range("2026-01-01 00:15", periods=4, freq="12h", tz="Asia/Shanghai"),
            [pd.Timestamp("2026-01-01 00:15", tz="Asia/Shanghai"), 0],
            True,
        ),
        (
            pd.date_range("2026-11-01 00:15", periods=4, freq="h", tz="America/New_York"),
            [pd.Timestamp("2026-11-01 00:15", tz="America/New_York"), 0],
            True,
        ),
        ([20260101.0, 20260102.0, np.nan], [20260101, 20260102, 0], False),
        (pd.Series([20260101, 20260102, 20260103], dtype=object), [20260101, 20260102, 0], False),
        (["20260101", "20260102", "20260103"], [20260101, 20260102, 0], False),
        (pd.Series([20260101, pd.NA, 20260103], dtype="Int64"), [20260101, 20260103, 0], False),
    ],
)
@pytest.mark.parametrize("execution", ["next_open", "next_close"])
def test_index_preserves_first_positional_match_and_exact_trades(values, dates, indexed, execution):
    df = frame(values)
    fast = OrderSimulator(df, execution=execution, position_mode="fixed")
    legacy = LegacyLookup(df, execution=execution, position_mode="fixed")
    mapping = fast._build_bar_positions()
    assert (mapping is not None) == indexed
    if mapping is not None:
        assert [mapping.get(day) for day in dates] == [legacy._find_bar_index(day) for day in dates]
    signals = [
        Signal(day, direction, 100, price=price, source=source)
        for day in dates
        for direction in ["BUY", "SELL"]
        for price, source in [(None, "strategy"), (20.125, "strategy"), (20.125, "stop")]
    ]
    pd.testing.assert_frame_equal(
        pd.DataFrame([asdict(t) for t in fast.simulate(signals, 100000, 100)]),
        pd.DataFrame([asdict(t) for t in legacy.simulate(signals, 100000, 100)]),
        check_exact=True,
    )


def test_datetime_column_is_indexed_once_per_simulate_not_once_per_signal(monkeypatch):
    df = frame(pd.date_range("2026-01-01", periods=200))
    signals = [Signal(20260101, "BUY", 100)] * 200
    original = orders.BarTimeIndex
    calls = []

    def count(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(orders, "BarTimeIndex", count)
    sim = OrderSimulator(df, position_mode="fixed")
    sim.simulate(signals, 1000000, 0)
    assert len(calls) == 1
    sim.simulate(signals, 1000000, 0)
    assert len(calls) == 2  # no stale cache across runs


def test_index_rebuilt_after_in_place_date_edit_and_frame_replacement():
    sim = OrderSimulator(frame([20260101, 20260102, 20260103]), position_mode="fixed")
    signals = [Signal(20260101, "BUY", 100)]
    assert sim.simulate(signals, 100000, 0)[0].price == 21
    sim.df.iloc[0, sim.df.columns.get_loc("datetime")] = 20260104
    assert sim.simulate(signals, 100000, 0) == []
    sim.df = frame([20260102, 20260101, 20260103])
    assert sim.simulate(signals, 100000, 0)[0].price == 22


def test_empty_signals_do_not_access_or_validate_dates(monkeypatch):
    sim = OrderSimulator(pd.DataFrame())
    monkeypatch.setattr(sim, "_build_bar_positions", lambda: pytest.fail("unexpected index"))
    assert sim.simulate([], 100000, 0) == []


def test_nat_keeps_legacy_error_instead_of_silently_skipping():
    df = frame(pd.to_datetime(["2026-01-01", None, "2026-01-03"]))
    for cls in [LegacyLookup, OrderSimulator]:
        with pytest.raises(ValueError):
            cls(df).simulate([Signal(20260101, "BUY", 100)], 100000, 0)


def test_exact_timestamp_signal_can_use_same_positional_index():
    df = frame(pd.date_range("2026-01-01", periods=3))
    signals = [Signal(pd.Timestamp("2026-01-01"), "BUY", 100)]
    sim = OrderSimulator(df)
    assert sim.simulate(signals, 100000, 0) == LegacyLookup(df).simulate(signals, 100000, 0)


@pytest.mark.parametrize("kind", ["subclass", "slippage"])
def test_custom_mutating_models_keep_per_signal_date_lookup(kind):
    df = frame([20260101, 20260102, 20260103])

    class MutatingSimulator(OrderSimulator):
        def _simulate_signal(self, signal, *args):
            result = super()._simulate_signal(signal, *args)
            self.df.iloc[1, self.df.columns.get_loc("datetime")] = 20260104
            return result

    class MutatingSlippage(FixedSlippage):
        def compute(self, *args, **kwargs):
            df.iloc[1, df.columns.get_loc("datetime")] = 20260104
            return super().compute(*args, **kwargs)

    sim = (
        MutatingSimulator(df, position_mode="fixed")
        if kind == "subclass"
        else OrderSimulator(df, position_mode="fixed", slippage_model=MutatingSlippage())
    )
    signals = [Signal(20260101, "BUY", 100), Signal(20260104, "SELL", 100)]
    trades = sim.simulate(signals, 100000, 0)
    assert len(trades) == 2
    assert trades[1].price == 22


def test_index_build_observes_cancellation_before_matching(monkeypatch):
    sim = OrderSimulator(frame(list(range(3000))))
    calls = []

    def cancel():
        calls.append(True)
        if len(calls) == 2:
            raise ComputationStopped("cancelled")

    monkeypatch.setattr(orders, "computation_checkpoint", cancel)
    monkeypatch.setattr(bar_time, "computation_checkpoint", cancel)
    monkeypatch.setattr(sim, "_simulate_signal", lambda *a, **kw: pytest.fail("matched after stop"))
    with pytest.raises(ComputationStopped):
        sim.simulate([Signal(1, "BUY", 100)], 100000, 0)
    assert len(calls) == 2
