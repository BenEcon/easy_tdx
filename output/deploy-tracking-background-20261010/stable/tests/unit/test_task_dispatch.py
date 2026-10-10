"""Six frozen input kinds reproduce their existing calculation path."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.multi_strategy_engine import StrategySlot
from easy_tdx.backtest.portfolio_engine import StockData
from easy_tdx.backtest.strategies import get_registry
from easy_tdx.web.backtest_schemas import (
    BacktestRequest,
    MultiStrategyBacktestRequest,
    OptimizeAllBacktestRequest,
    OptimizeBacktestRequest,
    PortfolioBacktestRequest,
    SignalScanRequest,
)
from easy_tdx.web.routers import backtest
from easy_tdx.web.signal_scan import ScanTarget, run_scan
from easy_tdx.web.task_dispatch import dispatch_task, scan_task_input
from easy_tdx.web.task_payload import (
    TaskInput,
    decode_task_input,
    encode_task_input,
    input_fingerprint,
)


@pytest.fixture
def frame():
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
    return backtest._ohlcv_to_df(records)


def round_trip(value):
    payload = encode_task_input(value)
    return decode_task_input(
        payload, execution_version=value.execution_version, fingerprint=input_fingerprint(payload)
    )


def test_backtest_exact_result(frame):
    request = BacktestRequest(
        strategy="ma_cross", symbol="SZ:300750", params={"fast": 5, "slow": 10}
    )
    value = TaskInput("backtest", "v1", request.model_dump(), (frame,), {})
    expected = backtest._run_backtest(frame, request)
    assert dispatch_task(round_trip(value)) == expected
    assert expected["trades"]


def test_portfolio_exact_result_and_source_mapping(frame):
    request = PortfolioBacktestRequest(
        strategy="ma_cross", stocks=["SZ:300750", "SH:600699"], params={"fast": 5, "slow": 10}
    )
    other = frame.copy(deep=True)
    other[["open", "high", "low", "close"]] *= 2
    value = TaskInput("portfolio", "v1", request.model_dump(), (frame, other), {})
    expected = backtest._run_portfolio_backtest(
        [StockData("300750", "SZ", frame), StockData("600699", "SH", other)], request
    )
    assert dispatch_task(round_trip(value)) == expected
    with pytest.raises(ValueError, match="分仓"):
        dispatch_task(replace(value, frames=(frame,)))


def test_multi_strategy_rebuilds_from_registry_not_live_instances(frame):
    request = MultiStrategyBacktestRequest(
        items=[
            {
                "strategy": "ma_cross",
                "symbol": "SZ:300750",
                "params": {"fast": 5, "slow": 10},
                "strategy_label": "我的均线",
            },
            {"strategy": "rsi_reversal", "symbol": "SH:600699", "params": {"n": 7}},
        ]
    )
    value = TaskInput("multi_strategy", "v1", request.model_dump(), (frame, frame), {})
    slots = [
        StrategySlot(
            item.strategy_label or get_registry().get(item.strategy).label,
            item.symbol,
            get_registry().get(item.strategy).build(item.params),
            frame,
        )
        for item in request.items
    ]
    assert dispatch_task(round_trip(value)) == backtest._run_multi_strategy_backtest(slots, request)


def test_optimize_retains_grid_order_and_complete_result(frame):
    request = OptimizeBacktestRequest(
        strategy="ma_cross", symbol="SZ:300750", param_grid={"slow": [10, 20], "fast": [3, 5]}
    )
    value = TaskInput("optimize", "v1", request.model_dump(), (frame,), {})
    actual = dispatch_task(round_trip(value))
    assert actual == backtest._run_optimize(frame, request)
    assert actual["param_names"] == ["slow", "fast"]
    assert len(actual["results"]) == 4


def test_all_strategy_budget_disallows_nested_pool_without_changing_request(frame, monkeypatch):
    import concurrent.futures

    from easy_tdx.backtest.strategies import presets

    monkeypatch.setattr(
        presets,
        "STRATEGY_PRESETS",
        {"ma_cross": {"fast": [5], "slow": [10]}, "rsi_reversal": {"n": [7]}},
    )
    monkeypatch.setattr(
        concurrent.futures,
        "ProcessPoolExecutor",
        lambda **kwargs: pytest.fail("nested process pool forbidden"),
    )
    request = OptimizeAllBacktestRequest(symbol="SZ:300750", workers=8)
    value = TaskInput("optimize_all", "v1", request.model_dump(), (frame,), {})
    actual = dispatch_task(round_trip(value))
    expected = backtest._run_optimize_all(frame, request.model_copy(update={"workers": 1}))
    expected["data_provenance"]["request"]["workers"] = 8
    assert actual == expected
    assert request.workers == 8
    assert len(actual["ranking"]) == 2


def scan_value(frame):
    targets = [
        ScanTarget(
            "s1", "均线", "single", "ma_cross", params={"fast": 5, "slow": 10}, symbol="SZ:300750"
        ),
        ScanTarget(
            "s2", "缺数据", "single", "ma_cross", symbol="SH:600699", error="固定行情失败原因"
        ),
        ScanTarget("s3", "缺标的", "single", "ma_cross", error="未指定标的"),
    ]
    bars = {("SZ:300750", "DAY"): frame, ("SH:600699", "DAY"): None}
    value = scan_task_input("v1", SignalScanRequest(window_bars=5), bars, targets)
    return value, bars, targets


def test_scan_preserves_error_rows_missing_frames_and_evidence(frame):
    value, bars, targets = scan_value(frame)
    expected = run_scan(bars, targets, 5)
    actual = dispatch_task(round_trip(value))
    actual.pop("elapsed")
    expected.pop("elapsed")
    assert actual == expected
    assert actual["total"] == 3 and actual["error_count"] == 2


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.context["bar_keys"][0].update(frame=True),
        lambda v: v.context["bar_keys"][0].update(frame=20),
        lambda v: v.context["bar_keys"].append(dict(v.context["bar_keys"][0])),
        lambda v: v.context["bar_keys"].clear(),
        lambda v: v.context["targets"][0].update(import_path="arbitrary.code"),
        lambda v: v.context.update(extra="unknown"),
    ],
)
def test_scan_mismatches_are_not_silently_remapped(frame, mutation):
    value, _, _ = scan_value(frame)
    mutation(value)
    with pytest.raises(ValueError):
        dispatch_task(value)


@pytest.mark.parametrize("budget", [0, -1, True, 2.5])
def test_invalid_execution_budget(frame, budget):
    with pytest.raises(ValueError, match="预算"):
        backtest._run_optimize_all(
            frame, OptimizeAllBacktestRequest(symbol="SZ:300750"), process_budget=budget
        )


def test_unregistered_task_rejected(frame):
    with pytest.raises(ValueError, match="未知"):
        dispatch_task(TaskInput("os.system", "v1", {}, (frame,), {}))
