"""Availability, non-nesting periods, missing observations and causal prefixes."""

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.combined_performance import aggregate_performance, combine_equity
from easy_tdx.backtest.types import BacktestResult
from easy_tdx.backtest.valuation import common_samples, observations
from easy_tdx.web.trading_calendar import is_session


def result(category, dates, totals, *, label="end", closed=None, ends=None):
    curve = pd.DataFrame({"datetime": pd.to_datetime(dates), "total": totals})
    if closed is not None:
        curve["is_closed"] = closed
    if ends is not None:
        curve["period_end"] = pd.to_datetime(ends)
    return BacktestResult(
        {},
        curve,
        pd.DataFrame(columns=["datetime", "direction", "pnl", "rejected", "size"]),
        pd.DataFrame(),
        {
            "performance_basis": {"input_category": category, "category_source": "explicit"},
            "bar_time": label,
        },
    )


def daily(start, end):
    dates = [day for day in pd.date_range(start, end) if is_session(day.date())]
    return result("DAY", dates, 100 + np.arange(len(dates), dtype=float))


def evaluate(results):
    allocations = {key: 100 for key in results}
    curve = combine_equity(results, allocations)
    metrics, basis = aggregate_performance(results, allocations, curve)
    return curve, metrics, basis


def test_week_start_labels_do_not_leak_friday_close_into_monday():
    week = result("WEEK", ["2026-09-07", "2026-09-14", "2026-09-21"], [110, 120, 130])
    original = week.equity_curve.copy(deep=True)
    curve, _, _ = evaluate({"day": daily("2026-09-07", "2026-09-24"), "week": week})
    assert curve.datetime.iloc[0] == pd.Timestamp("2026-09-07 15:00")
    assert curve.total.iloc[0] == 200  # weekly allocation is still cash
    assert curve.loc[curve.datetime == "2026-09-11 15:00", "total"].item() == 214
    assert curve.loc[curve.datetime == "2026-09-14 15:00", "total"].item() == 215
    pd.testing.assert_frame_equal(week.equity_curve, original, check_exact=True)


def test_daily_weekly_common_samples_compute_weekly_not_daily_metrics():
    results = {
        "day": daily("2026-09-01", "2026-09-30"),
        "week": result(
            "WEEK", ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-24"], [100, 103, 102, 107]
        ),
    }
    samples, evidence = common_samples(results, {"day": 100, "week": 100})
    curve, metrics, basis = evaluate(results)
    assert samples.datetime.dt.strftime("%Y-%m-%d").tolist() == [
        "2026-09-04",
        "2026-09-11",
        "2026-09-18",
        "2026-09-24",
    ]
    expected = (samples.total.iloc[-1] / samples.total.iloc[0]) ** (52 / 3) - 1
    assert metrics["annual_return"] == pytest.approx(expected)
    assert metrics["total_return"] == pytest.approx(curve.total.iloc[-1] / curve.total.iloc[0] - 1)
    assert basis["sample_category"] == "WEEK"
    assert basis["input_category"] == "MIXED"
    assert basis["unavailable_reason"] is None
    assert all(row["valid"] for row in evidence["valuation_samples"])


def test_nonnesting_week_month_uses_previous_complete_week_not_future_friday():
    weeks = pd.date_range("2026-01-02", "2026-05-08", freq="W-FRI")
    # Exclude all-holiday weeks; raw Friday labels can represent a Thursday close.
    from easy_tdx.backtest.valuation import period_close

    weeks = [day for day in weeks if period_close(day, "WEEK") is not None]
    weekly = result("WEEK", weeks, np.arange(len(weeks)) + 100)
    monthly = result(
        "MONTH", ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"], [100, 110, 105, 112]
    )
    _, metrics, basis = evaluate({"week": weekly, "month": monthly})
    march = next(row for row in basis["valuation_samples"] if row["datetime"].startswith("2026-03"))
    week = next(row for row in march["members"] if row["member"] == "week")
    assert week["valuation_time"] == "2026-03-27T15:00:00"
    assert week["asof_age_seconds"] == 4 * 86400
    assert basis["annual_periods"] == 12
    assert np.isfinite(metrics["annual_return"])


def test_internal_missing_native_close_invalidates_without_compressing_interval():
    day = daily("2026-09-01", "2026-09-24")
    day.equity_curve = day.equity_curve.loc[day.equity_curve.datetime != "2026-09-11"].copy()
    week = result(
        "WEEK", ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-24"], [100, 103, 102, 107]
    )
    _, metrics, basis = evaluate({"day": day, "week": week})
    assert np.isnan(metrics["annual_return"])
    assert basis["sample_count"] == 4
    assert "缺失" in basis["unavailable_reason"]
    failed = [row for row in basis["valuation_samples"] if not row["valid"]]
    assert len(failed) == 1
    member = failed[0]["members"][0]
    assert member["expected_time"] == "2026-09-11T15:00:00"
    assert member["valuation_time"] == "2026-09-10T15:00:00"
    assert member["reason"]


def test_trailing_outside_coverage_is_excluded_and_explained_not_forward_filled():
    week = result("WEEK", ["2026-09-04", "2026-09-11", "2026-09-18"], [100, 105, 103])
    _, metrics, basis = evaluate({"day": daily("2026-09-01", "2026-09-30"), "week": week})
    assert basis["sample_count"] == 3
    assert np.isfinite(metrics["annual_return"])
    assert basis["excluded_targets"][0]["datetime"] == "2026-09-24T15:00:00"
    assert basis["excluded_targets"][0]["members"] == ["week"]


def test_minute_start_and_end_labels_agree_at_daily_close():
    dates = pd.to_datetime(["2026-09-14 14:55", "2026-09-15 14:55", "2026-09-16 14:55"])
    start = result(
        "MIN_5", dates, [100, 105, 103], label="start", ends=dates + pd.Timedelta(minutes=5)
    )
    end = result("MIN_5", dates + pd.Timedelta(minutes=5), [100, 105, 103])
    day = daily("2026-09-14", "2026-09-16")
    a, metrics_a, basis_a = evaluate({"day": day, "minute": start})
    b, metrics_b, basis_b = evaluate({"day": day, "minute": end})
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    pd.testing.assert_series_equal(pd.Series(metrics_a), pd.Series(metrics_b), check_exact=True)
    assert basis_a["sample_count"] == basis_b["sample_count"] == 3


def test_unclosed_observation_never_enters_combined_valuation():
    week = result(
        "WEEK",
        ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-24"],
        [100, 105, 103, 99999],
        closed=[True, True, True, False],
    )
    curve, _, basis = evaluate({"day": daily("2026-09-01", "2026-09-30"), "week": week})
    assert curve.total.max() < 300
    assert basis["sample_count"] == 3


@pytest.mark.parametrize("category", ["WEEK", "MONTH", "SEASON", "YEAR"])
def test_unknown_calendar_never_invents_close(category):
    with pytest.raises(ValueError, match="未覆盖"):
        observations(result(category, ["2027-01-01"], [100]))


@pytest.mark.parametrize(
    "dates",
    [
        ["2026-09-14", "2026-09-14"],
        ["2026-09-15", "2026-09-14"],
        ["2026-09-14", None],
    ],
)
def test_invalid_time_not_sorted_or_guessed(dates):
    with pytest.raises(ValueError, match="缺失、重复或乱序"):
        observations(result("DAY", dates, [100, 102]))


def test_period_end_mismatch_cannot_override_category_or_advance_availability():
    item = result("WEEK", ["2026-09-07"], [100], ends=["2026-09-07 15:00"])
    with pytest.raises(ValueError, match="period_end"):
        observations(item)


def test_aware_and_local_exchange_times_have_same_availability():
    local = result("MIN_5", ["2026-09-14 15:00", "2026-09-15 15:00"], [100, 101])
    utc = result("MIN_5", ["2026-09-14 07:00Z", "2026-09-15 07:00Z"], [100, 101])
    pd.testing.assert_frame_equal(observations(local), observations(utc), check_exact=True)


def test_prefix_valuation_identical_before_future_week_is_available():
    day = daily("2026-09-01", "2026-09-30")
    old = result("WEEK", ["2026-09-04", "2026-09-11", "2026-09-18"], [100, 105, 103])
    new = result(
        "WEEK", ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-21"], [100, 105, 103, 200]
    )
    first, _, basis_first = evaluate({"day": day, "week": old})
    second, _, basis_second = evaluate({"day": day, "week": new})
    cutoff = pd.Timestamp("2026-09-24 15:00")
    pd.testing.assert_frame_equal(first[first.datetime < cutoff], second[second.datetime < cutoff])
    assert basis_first["valuation_samples"] == basis_second["valuation_samples"][:3]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1])
def test_invalid_member_value_is_not_hidden_by_positive_combined_total(value):
    week = result("WEEK", ["2026-09-04", "2026-09-11", "2026-09-18"], [100, value, 103])
    samples, basis = common_samples(
        {"day": daily("2026-09-01", "2026-09-18"), "week": week}, {"day": 100, "week": 100}
    )
    assert np.isnan(samples.total.iloc[1])
    assert basis["valuation_samples"][1]["members"][1]["reason"] == "成员净值非有限或不为正"


def test_cash_only_allocation_is_included_in_common_samples():
    results = {
        "day": daily("2026-09-01", "2026-09-18"),
        "week": result("WEEK", ["2026-09-04", "2026-09-11", "2026-09-18"], [100, 105, 103]),
    }
    original, _ = common_samples(results, {"day": 100, "week": 100})
    cash, _ = common_samples(results, {"day": 100, "week": 100, "cash-only": 50})
    np.testing.assert_array_equal(cash.total, original.total + 50)


@pytest.mark.parametrize("category", ["DAY", "WEEK"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_union_does_not_forward_fill_invalid_observation(category, value):
    dates = ["2026-09-04", "2026-09-11", "2026-09-18"]
    item = result(category, dates, [100, value, 103])
    with pytest.raises(ValueError, match="非有限净值"):
        combine_equity({"bad": item}, {"bad": 100})


def test_full_holiday_week_not_compressed_into_one_week_return():
    results = {
        "day": daily("2026-02-01", "2026-03-13"),
        "week": result(
            "WEEK", ["2026-02-06", "2026-02-13", "2026-02-27", "2026-03-06"], [100, 105, 103, 104]
        ),
    }
    curve, metrics, basis = evaluate(results)
    samples, evidence = common_samples(results, {"day": 100, "week": 100})
    assert np.isfinite(metrics["annual_return"])
    assert basis["unavailable_reason"] is None
    assert basis["sample_count"] == 5
    assert basis["observed_sample_count"] == 4
    assert samples.total.iloc[1] == samples.total.iloc[2]
    assert basis["return_count"] == 4
    assert metrics["annual_return"] == pytest.approx(
        (samples.total.iloc[-1] / samples.total.iloc[0]) ** (52 / 4) - 1
    )
    assert not (curve.datetime == "2026-02-22 15:00").any()
    closure = evidence["valuation_samples"][2]
    assert closure["closed_period"] is True
    assert closure["datetime"] == "2026-02-22T15:00:00"
    assert {member["valuation_time"] for member in closure["members"]} == {"2026-02-13T15:00:00"}


def test_real_web_multi_strategy_delivers_mixed_sampling_and_unchanged_source_labels():
    from easy_tdx.backtest.multi_strategy_engine import StrategySlot
    from easy_tdx.backtest.strategies import get_registry
    from easy_tdx.web.backtest_schemas import MultiStrategyBacktestRequest
    from easy_tdx.web.routers.backtest import _run_multi_strategy_backtest

    params = {"fast": 2, "slow": 5}
    slots, items, originals = [], [], []
    for category, dates in [
        ("DAY", daily("2026-07-01", "2026-09-24").equity_curve.datetime),
        ("WEEK", pd.date_range("2026-07-03", "2026-09-18", freq="W-FRI")),
    ]:
        values = 20 + np.sin(np.arange(len(dates)))
        frame = pd.DataFrame(
            dict(
                datetime=dates,
                open=values,
                high=values + 1,
                low=values - 1,
                close=values,
                vol=1000,
                amount=20000,
            )
        )
        originals.append(frame.copy(deep=True))
        slots.append(
            StrategySlot(category, "SZ:300750", get_registry().get("ma_cross").build(params), frame)
        )
        items.append(
            dict(
                strategy="ma_cross",
                strategy_label=category,
                symbol="SZ:300750",
                category=category,
                params=params,
            )
        )
    output = _run_multi_strategy_backtest(slots, MultiStrategyBacktestRequest(items=items))
    basis = output["data_provenance"]["performance_basis"]
    assert basis["input_category"] == "MIXED"
    assert basis["sample_category"] == "WEEK"
    assert basis["unavailable_reason"] is None
    assert output["total_performance"]["annual_return"] is not None
    assert basis == output["performance_basis"]
    assert len(basis["valuation_samples"]) == 12
    for slot, original in zip(slots, originals, strict=True):
        pd.testing.assert_frame_equal(slot.df, original, check_exact=True)
        assert not slot.df.attrs  # binding must not mutate input or fabricate provenance


def test_common_closure_does_not_inflate_observation_count():
    results = {
        "day": daily("2026-02-13", "2026-02-27"),
        "week": result("WEEK", ["2026-02-13", "2026-02-27"], [100, 105]),
    }
    _, metrics, basis = evaluate(results)
    assert basis["sample_count"] == 3
    assert basis["observed_sample_count"] == 2
    assert np.isnan(metrics["annual_return"])
    assert "不足" in basis["unavailable_reason"]


def test_common_sampling_checks_cancellation():
    from unittest.mock import patch

    from easy_tdx import computation

    item = result("WEEK", ["2026-09-04", "2026-09-11", "2026-09-18"], [100, 105, 103])
    with patch.object(computation, "computation_checkpoint", side_effect=RuntimeError("cancelled")):
        # valuation imports the guard directly; patch its binding as well.
        with patch(
            "easy_tdx.backtest.valuation.computation_checkpoint",
            side_effect=RuntimeError("cancelled"),
        ):
            with pytest.raises(RuntimeError, match="cancelled"):
                common_samples({"week": item}, {"week": 100})
