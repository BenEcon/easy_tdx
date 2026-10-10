"""Numerical and cross-consumer regression for explicit performance periods."""

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.combined_performance import aggregate_performance, combine_equity
from easy_tdx.backtest.performance import PerformanceAnalyzer
from easy_tdx.backtest.performance_sampling import performance_frame, resolve_category
from easy_tdx.backtest.types import BacktestResult


def equity(dates, values):
    values = np.asarray(values, dtype=float)
    peak = np.maximum.accumulate(values)
    return pd.DataFrame(
        {
            "datetime": pd.to_datetime(dates),
            "total": values,
            "drawdown": peak - values,
            "drawdown_pct": (peak - values) / peak,
        }
    )


def trades():
    return pd.DataFrame(columns=["datetime", "direction", "pnl", "rejected", "size"])


@pytest.mark.parametrize(
    "category,dates,periods",
    [
        ("DAY", ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17"], 252),
        ("WEEK", ["2026-08-07", "2026-08-14", "2026-08-21", "2026-08-28"], 52),
        ("MONTH", ["2026-01-30", "2026-02-27", "2026-03-31", "2026-04-30"], 12),
        ("SEASON", ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"], 4),
        ("YEAR", ["2023-12-29", "2024-12-31", "2025-12-31", "2026-12-31"], 1),
    ],
)
def test_declared_frequency_drives_all_annualized_metrics(category, dates, periods):
    curve = equity(dates, [100, 102, 101, 104])
    analyzer = PerformanceAnalyzer(curve, trades(), category=category)
    metrics = analyzer.compute()
    returns = np.diff(curve.total) / curve.total.to_numpy()[:-1]
    assert metrics["total_return"] == pytest.approx(0.04)
    assert metrics["annual_return"] == pytest.approx(1.04 ** (periods / 3) - 1)
    assert metrics["volatility"] == pytest.approx(np.std(returns) * np.sqrt(periods))
    assert metrics["sharpe"] == pytest.approx(
        np.mean(returns - 0.03 / periods) / np.std(returns) * np.sqrt(periods)
    )
    assert analyzer.basis["annual_periods"] == periods
    assert analyzer.basis["return_count"] == 3
    assert analyzer.basis["unavailable_reason"] is None


@pytest.mark.parametrize("category", ["MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60", "MIN_120"])
def test_minute_frequency_does_not_change_close_to_close_metrics(category):
    days = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17"]
    daily = equity(days, [100, 102, 101, 104])
    expected = PerformanceAnalyzer(daily, trades(), category="DAY").compute()
    dates = [f"{day} {clock}" for day in days for clock in ["10:00", "15:00"]]
    curve = equity(dates, [99, 100, 150, 102, 40, 101, 98, 104])
    analyzer = PerformanceAnalyzer(curve, trades(), category=category)
    actual = analyzer.compute()
    for key in ["annual_return", "sharpe", "sortino", "volatility"]:
        assert actual[key] == pytest.approx(expected[key], nan_ok=True)
    assert actual["max_drawdown"] > expected["max_drawdown"]  # intraday risk not discarded
    assert actual["total_return"] == pytest.approx(104 / 99 - 1)
    assert analyzer.basis["sample_count"] == 4


def test_start_labels_and_explicit_period_ends_agree_without_mutation():
    curve = equity(["2026-09-14 14:55", "2026-09-15 14:55", "2026-09-16 14:55"], [100, 102, 101])
    source = curve.copy()
    source.attrs["snapshot_metadata"] = {"category": "MIN_5", "bar_time": "start"}
    first = PerformanceAnalyzer(curve, trades(), source=source)
    a = first.compute()
    source["period_end"] = source.datetime + pd.Timedelta(minutes=5)
    second = PerformanceAnalyzer(curve, trades(), source=source)
    b = second.compute()
    pd.testing.assert_series_equal(pd.Series(a), pd.Series(b), check_exact=True)
    assert first.basis["sample_end"] == "2026-09-16T15:00:00"
    assert curve.datetime.iloc[-1].minute == 55


@pytest.mark.parametrize(
    "dates,category,reason",
    [
        (["2026-09-14 10:00", "2026-09-14 10:05", "2026-09-14 10:10"], "MIN_5", "不足"),
        (["2026-09-14", "2026-09-16", "2026-09-17"], "DAY", "缺少交易日"),
        (["2026-01-30", "2026-03-31", "2026-04-30"], "MONTH", "周期重复或缺失"),
        (["2027-01-04", "2027-01-05", "2027-01-06"], "DAY", "未覆盖"),
        (["2026-09-14 10:00", "2026-09-14 11:00", "2026-09-15 11:00"], "DAY", "同一天"),
    ],
)
def test_unavailable_sampling_retains_real_total_and_drawdown(dates, category, reason):
    analyzer = PerformanceAnalyzer(equity(dates, [100, 110, 105]), trades(), category=category)
    metrics = analyzer.compute()
    assert metrics["total_return"] == pytest.approx(0.05)
    assert metrics["max_drawdown"] == pytest.approx(5 / 110)
    for key in ["annual_return", "sharpe", "sortino", "calmar", "volatility"]:
        assert np.isnan(metrics[key])
    assert reason in analyzer.basis["unavailable_reason"]


def test_holidays_not_missing_and_period_binding_not_fake_provenance():
    curve = equity(["2026-09-24", "2026-09-28", "2026-09-29"], [100, 101, 102])
    source = performance_frame(curve, "DAY")
    assert "snapshot_metadata" not in source.attrs
    assert not curve.attrs
    analyzer = PerformanceAnalyzer(curve, trades(), source=source)
    assert np.isfinite(analyzer.compute()["annual_return"])
    assert not analyzer.basis["missing_sessions"]
    source.attrs["snapshot_metadata"] = {"category": "WEEK"}
    with pytest.raises(ValueError, match="不一致"):
        resolve_category(source)


def result(curve, category="DAY"):
    analyzer = PerformanceAnalyzer(curve, trades(), category=category)
    return BacktestResult(
        analyzer.compute(), curve, trades(), pd.DataFrame(), {"performance_basis": analyzer.basis}
    )


def test_combined_cash_exists_before_first_observation_and_empty_slot():
    a = result(equity(["2026-09-14", "2026-09-15", "2026-09-16"], [100, 110, 100]))
    b = result(equity(["2026-09-15", "2026-09-16"], [200, 190]))
    curve = combine_equity({"a": a, "b": b}, {"a": 100, "b": 200, "empty": 50})
    assert curve.total.tolist() == [350, 360, 340]
    assert curve.drawdown.tolist() == [0, 0, 20]
    assert curve.drawdown_pct.iloc[-1] == pytest.approx(20 / 360)
    metrics, basis = aggregate_performance(
        {"a": a, "b": b}, {"a": 100, "b": 200, "empty": 50}, curve
    )
    assert metrics["total_return"] == pytest.approx(340 / 350 - 1)
    assert metrics["annual_return"] != metrics["total_return"]
    assert basis["sample_count"] == 3


def test_mixed_period_union_not_annualized_as_daily():
    a = result(equity(["2026-09-14", "2026-09-15", "2026-09-16"], [100, 110, 100]))
    b = result(equity(["2026-08-28", "2026-09-04", "2026-09-11"], [200, 190, 210]), "WEEK")
    curve = combine_equity({"a": a, "b": b}, {"a": 100, "b": 200})
    metrics, basis = aggregate_performance({"a": a, "b": b}, {"a": 100, "b": 200}, curve)
    assert np.isnan(metrics["annual_return"])
    assert basis["input_category"] == "MIXED"
    assert "成员周期不同" in basis["unavailable_reason"]


def test_maximum_drawdown_starts_at_peak_not_nearest_higher_value():
    analyzer = PerformanceAnalyzer(
        equity(pd.date_range("2026-09-14", periods=4), [100, 130, 120, 110]), trades()
    )
    assert analyzer.compute()["max_dd_duration"] == 2


def test_holding_time_preserves_fractional_days():
    tx = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-09-14 10:00", "2026-09-14 11:00"]),
            "direction": ["BUY", "SELL"],
            "size": [100, 100],
            "pnl": [0, 1],
            "rejected": [False, False],
        }
    )
    analyzer = PerformanceAnalyzer(
        equity(pd.date_range("2026-09-14", periods=3), [100, 101, 102]), tx
    )
    assert analyzer.compute()["avg_holding_days"] == pytest.approx(1 / 24)


def test_two_observations_keep_total_return_even_without_enough_risk_samples():
    analyzer = PerformanceAnalyzer(
        equity(["2026-09-14", "2026-09-15"], [100, 105]), trades(), category="DAY"
    )
    metrics = analyzer.compute()
    assert metrics["total_return"] == pytest.approx(0.05)
    assert np.isnan(metrics["sharpe"])


@pytest.mark.parametrize("category,periods", [("MIN_30", 252), ("WEEK", 52), ("MONTH", 12)])
def test_web_consumers_share_request_period_and_result_basis(monkeypatch, category, periods):
    from easy_tdx.backtest.multi_strategy_engine import StrategySlot
    from easy_tdx.backtest.portfolio_engine import StockData
    from easy_tdx.backtest.strategies import get_registry, presets
    from easy_tdx.web.backtest_schemas import (
        BacktestRequest,
        MultiStrategyBacktestRequest,
        OptimizeAllBacktestRequest,
        OptimizeBacktestRequest,
        PortfolioBacktestRequest,
    )
    from easy_tdx.web.routers import backtest

    if category == "MIN_30":
        dates = pd.to_datetime(
            [
                f"2026-09-{day} {clock}"
                for day in [14, 15, 16, 17]
                for clock in [
                    "10:00",
                    "10:30",
                    "11:00",
                    "11:30",
                    "13:30",
                    "14:00",
                    "14:30",
                    "15:00",
                ]
            ]
        )
    elif category == "WEEK":
        dates = pd.date_range("2026-07-03", periods=10, freq="W-FRI")
    else:
        dates = pd.date_range("2025-10-31", periods=10, freq="ME")
    values = 20 + np.sin(np.arange(len(dates)))
    frame = pd.DataFrame(
        {
            "datetime": dates,
            "open": values,
            "high": values + 1,
            "low": values - 1,
            "close": values,
            "vol": 1000,
            "amount": 20000,
        }
    )
    params = {"fast": 2, "slow": 5}
    single = backtest._run_backtest(
        frame,
        BacktestRequest(strategy="ma_cross", symbol="SZ:000001", category=category, params=params),
    )
    portfolio = backtest._run_portfolio_backtest(
        [StockData("000001", "SZ", frame)],
        PortfolioBacktestRequest(
            strategy="ma_cross", stocks=["SZ:000001"], category=category, params=params
        ),
    )
    request = MultiStrategyBacktestRequest(
        items=[dict(strategy="ma_cross", symbol="SZ:000001", category=category, params=params)]
    )
    multi = backtest._run_multi_strategy_backtest(
        [StrategySlot("ma", "SZ:000001", get_registry().get("ma_cross").build(params), frame)],
        request,
    )
    optimize = backtest._run_optimize(
        frame,
        OptimizeBacktestRequest(
            strategy="ma_cross",
            symbol="SZ:000001",
            category=category,
            param_grid={"fast": [2], "slow": [5]},
        ),
    )
    monkeypatch.setattr(presets, "STRATEGY_PRESETS", {"ma_cross": {"fast": [2], "slow": [5]}})
    all_result = backtest._run_optimize_all(
        frame, OptimizeAllBacktestRequest(symbol="SZ:000001", category=category), process_budget=1
    )
    for output in [single, portfolio, multi, optimize, all_result]:
        basis = output["data_provenance"]["performance_basis"]
        assert basis["input_category"] == category
        assert basis["annual_periods"] == periods
        assert basis["return_count"] == (3 if category == "MIN_30" else 9)
        assert basis["unavailable_reason"] is None
    assert "performance_category" not in frame.attrs
