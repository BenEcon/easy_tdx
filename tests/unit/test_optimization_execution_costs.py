"""Actual frozen-market engine equivalence at non-default execution costs."""

import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.backtest.performance_sampling import performance_frame
from easy_tdx.backtest.portfolio import PortfolioTracker
from easy_tdx.backtest.strategies import presets
from easy_tdx.backtest.types import Trade
from easy_tdx.web.backtest_schemas import (
    BacktestRequest,
    OptimizeAllBacktestRequest,
    OptimizeBacktestRequest,
)
from easy_tdx.web.routers import backtest
from tests.market_matrix import entries
from tests.unit.test_real_market_consumers import input_frame


def test_integer_initial_cash_does_not_truncate_fractional_trades():
    frame = pd.DataFrame(
        {"datetime": pd.date_range("2026-01-05", periods=3), "close": [10.1, 10.2, 10.3]}
    )
    trades = [
        Trade(frame.datetime[0], "BUY", 100, 10.1, 1.23, 0),
        Trade(frame.datetime[1], "SELL", 100, 10.2, 2.34, 0),
    ]
    integer = PortfolioTracker(frame, initial_cash=10000)
    floating = PortfolioTracker(frame, initial_cash=10000.0)
    integer.apply_trades(trades)
    floating.apply_trades(trades)
    pd.testing.assert_frame_equal(integer.equity_curve, floating.equity_curve)
    assert integer.equity_curve.cash.iloc[-1] == pytest.approx(10006.43)


@pytest.mark.asyncio
@pytest.mark.parametrize("execution", ["next_open", "next_close"])
@pytest.mark.parametrize("workers", [1, 2])
async def test_nondefault_costs_match_single_and_all_optimization(monkeypatch, execution, workers):
    entry = next(e for e in entries() if e["id"] == "300450-qfq-20261002")
    frame, _ = await input_frame(entry, monkeypatch)
    params = {"fast": 7, "slow": 31}
    grid = {k: [v] for k, v in params.items()}
    common = dict(
        symbol="SZ:300450",
        category="DAY",
        count=800,
        cash=200000,
        commission=0.0002,
        min_commission=83.21,
        stamp_tax=0.004,
        slippage=0.002,
        execution=execution,
    )
    expected = backtest._run_backtest(
        frame, BacktestRequest(strategy="ma_cross", params=params, **common)
    )["performance"]
    original = backtest._run_backtest(
        frame,
        BacktestRequest(
            strategy="ma_cross",
            params=params,
            **{**common, "min_commission": 5, "stamp_tax": 0.001},
        ),
    )["performance"]
    assert expected["total_trades"] > 0
    assert expected["total_return"] != original["total_return"]
    one = backtest._run_optimize(
        frame, OptimizeBacktestRequest(strategy="ma_cross", param_grid=grid, **common)
    )
    monkeypatch.setattr(presets, "STRATEGY_PRESETS", {"ma_cross": grid})
    all_result = backtest._run_optimize_all(
        frame, OptimizeAllBacktestRequest(**common, workers=workers)
    )
    worker = backtest._optimize_one_strategy(
        "ma_cross",
        grid,
        performance_frame(frame, "DAY"),
        common["cash"],
        common["commission"],
        common["slippage"],
        execution,
        common["min_commission"],
        common["stamp_tax"],
    )
    for actual in (one["best"], all_result["best"], worker):
        for key in (
            "total_return",
            "sharpe",
            "max_drawdown",
            "total_trades",
            "win_rate",
            "profit_factor",
        ):
            assert actual[key] == pytest.approx(expected[key]), key


@pytest.mark.parametrize("schema", [OptimizeBacktestRequest, OptimizeAllBacktestRequest])
def test_cost_fields_survive_worker_payload_roundtrip_and_reject_invalid(schema):
    required = {"symbol": "SZ:300450"}
    if schema is OptimizeBacktestRequest:
        required.update(strategy="ma_cross", param_grid={"fast": [7]})
    value = schema(**required, min_commission=1.23, stamp_tax=0)
    restored = schema.model_validate(value.model_dump())
    assert restored.min_commission == 1.23 and restored.stamp_tax == 0
    assert schema(**required).min_commission == 5
    assert schema(**required).stamp_tax == 0.001
    for key, invalid in (("min_commission", -1), ("stamp_tax", -0.1), ("stamp_tax", 0.1)):
        with pytest.raises(ValidationError):
            schema(**required, **{key: invalid})
