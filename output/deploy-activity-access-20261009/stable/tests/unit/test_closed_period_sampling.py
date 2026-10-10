"""Verified exchange closures are valuations, never invented OHLC or trades."""

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.performance import PerformanceAnalyzer
from easy_tdx.backtest.performance_sampling import sample_equity
from easy_tdx.backtest.sampling_calendar import expand_closed_periods


def sample(dates, values, category="WEEK"):
    return sample_equity(
        pd.DataFrame({"datetime": pd.to_datetime(dates), "total": values}),
        category=category,
        category_source="explicit",
    )


@pytest.mark.parametrize(
    "year,dates,closed",
    [
        (2024, ["02-02", "02-08", "02-23", "03-01"], "2024-02-18"),
        (2025, ["09-26", "09-30", "10-10", "10-17"], None),
        (2026, ["02-06", "02-13", "02-27", "03-06"], "2026-02-22"),
    ],
)
def test_exact_calendar_closure_is_distinct_from_short_trading_week(year, dates, closed):
    dates = [f"{year}-{day}" for day in dates]
    values, basis = sample(dates, [100, 103, 101, 106])
    assert basis["unavailable_reason"] is None
    assert basis["observed_sample_count"] == 4
    if closed:
        np.testing.assert_array_equal(values, [100, 103, 103, 101, 106])
        assert basis["closed_period_samples"][0]["datetime"] == f"{closed}T15:00:00"
        assert basis["closed_period_samples"][0]["source_time"].startswith(dates[1])
    else:
        np.testing.assert_array_equal(values, [100, 103, 101, 106])
        assert not basis["closed_period_samples"]


def test_weekly_annualization_keeps_holiday_week_as_a_period_not_a_quote():
    dates = pd.to_datetime(["2026-02-06", "2026-02-13", "2026-02-27", "2026-03-06"])
    values = np.array([100, 103, 101, 106], dtype=float)
    peak = np.maximum.accumulate(values)
    frame = pd.DataFrame(
        {
            "datetime": dates,
            "total": values,
            "drawdown": peak - values,
            "drawdown_pct": (peak - values) / peak,
        }
    )
    before = frame.copy(deep=True)
    analyzer = PerformanceAnalyzer(
        frame, pd.DataFrame(columns=["direction", "pnl", "rejected"]), category="WEEK"
    )
    metrics = analyzer.compute()
    returns = np.diff([100, 103, 103, 101, 106]) / np.array([100, 103, 103, 101])
    assert metrics["annual_return"] == pytest.approx(1.06 ** (52 / 4) - 1)
    assert metrics["volatility"] == pytest.approx(returns.std() * np.sqrt(52))
    assert metrics["total_return"] == pytest.approx(0.06)
    assert metrics["max_drawdown"] == pytest.approx(2 / 103)
    pd.testing.assert_frame_equal(frame, before, check_exact=True)


@pytest.mark.parametrize(
    "dates,category,reason",
    [
        (["2026-02-06", "2026-02-27", "2026-03-06"], "WEEK", "有交易日"),
        (["2026-01-30", "2026-03-31", "2026-04-30"], "MONTH", "有交易日"),
        (["2027-02-05", "2027-02-19", "2027-02-26"], "WEEK", "未覆盖"),
        (["2026-02-06", "2026-02-06", "2026-02-27"], "WEEK", "重复"),
        (["2026-02-13", "2026-02-06", "2026-02-27"], "WEEK", "乱序"),
    ],
)
def test_non_closure_gaps_unknown_years_and_bad_order_stay_unavailable(dates, category, reason):
    values, basis = sample(dates, [100, 101, 102], category)
    assert reason in basis["unavailable_reason"]
    np.testing.assert_array_equal(values, [100, 101, 102])
    assert not basis["closed_period_samples"]


def test_no_tail_invention_or_future_value_used_for_closure():
    dates = pd.to_datetime(["2026-02-06", "2026-02-13", "2026-02-27", "2026-03-06"])
    before, basis_before = sample(dates[:2], [100, 103])
    full, basis_full = sample(dates, [100, 103, 999, 800])
    np.testing.assert_array_equal(before, full[:2])
    assert not basis_before["closed_period_samples"]
    assert full[2] == 103  # not the subsequent 999
    assert len(basis_full["closed_period_samples"]) == 1


def test_closure_does_not_hide_a_nan_source_value():
    values, basis = sample(["2026-02-06", "2026-02-13", "2026-02-27"], [100, float("nan"), 110])
    assert np.isnan(values[1]) and np.isnan(values[2])
    assert "非有限" in basis["unavailable_reason"]
    assert basis["closed_period_samples"][0]["valuation"] is None


def test_carried_week_does_not_manufacture_enough_independent_observations():
    values, basis = sample(["2026-02-13", "2026-02-27"], [100, 103])
    np.testing.assert_array_equal(values, [100, 100, 103])
    assert basis["sample_count"] == 3
    assert basis["observed_sample_count"] == 2
    assert "不足" in basis["unavailable_reason"]


def test_timezone_is_classified_by_exchange_local_week():
    dates = pd.to_datetime(["2026-02-06 07:00Z", "2026-02-13 07:00Z", "2026-02-27 07:00Z"])
    values, basis = sample(dates, [100, 103, 101])
    np.testing.assert_array_equal(values, [100, 103, 103, 101])
    assert basis["sample_end"] == "2026-02-27T15:00:00"


def test_closure_scan_observes_cancellation(monkeypatch):
    def cancel():
        raise RuntimeError("cancelled")

    monkeypatch.setattr("easy_tdx.backtest.sampling_calendar.computation_checkpoint", cancel)
    with pytest.raises(RuntimeError, match="cancelled"):
        expand_closed_periods(
            pd.to_datetime(["2026-02-13", "2026-02-27"]), np.array([100.0, 110.0]), "W-SUN"
        )
