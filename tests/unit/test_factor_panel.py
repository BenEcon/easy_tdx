"""Whole-pool semantics checked against hand ranks and scalar reference loops.

Synthetic testing factors are deliberately not published as Alpha101/GTJA191.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.computation import ComputationControl, ComputationStopped, computation_scope
from easy_tdx.factor import FACTORY_REGISTRY, FactorEngine, PanelFactor
from easy_tdx.factor.catalog import availability_reason, describe_factor
from easy_tdx.factor.panel import FactorPanel, cross_section_rank, delay, rolling_mean
from easy_tdx.factor.research import cross_section_report


class RankClose(PanelFactor):
    name = "test_pool_close_rank"
    category = "technical"
    description = "测试截面排名（非投资因子）"
    inputs = ("close",)

    def compute_panel(self, panel):
        return cross_section_rank(panel.fields["close"])


def pool():
    dates = pd.date_range("2025-01-01", periods=4)
    return {
        "A": pd.DataFrame({"datetime": dates, "close": [1.0, 9.0, 3.0, 7.0]}),
        "B": pd.DataFrame({"datetime": dates, "close": [2.0, 8.0, 3.0, 8.0]}),
        "C": pd.DataFrame({"datetime": dates, "close": [3.0, 7.0, 6.0, 9.0]}),
    }


def test_real_cross_section_ranks_and_ties_not_time_series():
    result = FactorEngine().compute_matrix(pool(), RankClose())
    np.testing.assert_allclose(
        result, [[1 / 3, 2 / 3, 1], [1, 2 / 3, 1 / 3], [0.5, 0.5, 1], [1 / 3, 2 / 3, 1]]
    )
    # A future row cannot change earlier cross-sections.
    short = {code: frame.iloc[:3].copy() for code, frame in pool().items()}
    pd.testing.assert_frame_equal(
        result.iloc[:3], FactorEngine().compute_matrix(short, RankClose())
    )


def test_symbol_permutation_changes_no_values():
    original = pool()
    swapped = {s: original[s] for s in ["C", "A", "B"]}
    a = FactorEngine().compute_matrix(original, RankClose())
    b = FactorEngine().compute_matrix(swapped, RankClose())
    pd.testing.assert_frame_equal(a, b[a.columns])


def test_duplicate_factor_names_do_not_overwrite_result():
    with pytest.raises(ValueError, match="重复因子"):
        FactorEngine().compute_cross_section(pool(), [RankClose(), RankClose()])


def test_missing_observation_is_not_an_imputed_member_or_stale_latest():
    data = pool()
    data["A"] = data["A"].iloc[[0, 2]]
    values = FactorEngine().compute_matrix(data, RankClose())
    assert np.isnan(values.iloc[1, 0]) and np.isnan(values.iloc[3, 0])
    assert values.iloc[1].tolist()[1:] == [1.0, 0.5]
    latest = FactorEngine().compute_cross_section(data, [RankClose()], date=None)
    assert len(latest) == 3
    assert latest.datetime.nunique() == 1
    assert latest.iloc[0][RankClose.name] != latest.iloc[0][RankClose.name]
    assert latest.date.tolist() == [20250104] * 3


def test_nullable_numeric_missing_is_nan_not_fatal_or_zero():
    data = pool()
    data["A"]["close"] = pd.Series([1, pd.NA, 3, 7], dtype="Float64")
    result = FactorEngine().compute_matrix(data, RankClose())
    assert np.isnan(result.iloc[1, 0])
    assert result.iloc[1].tolist()[1:] == [1, 0.5]


@pytest.mark.parametrize(
    "column, expected", [([4, 4, 4], [2 / 3] * 3), ([0, np.nan, np.inf], [np.nan] * 3)]
)
def test_rank_constant_missing_singleton(column, expected):
    actual = cross_section_rank(pd.DataFrame([column])).iloc[0].to_numpy()
    np.testing.assert_allclose(actual, expected, equal_nan=True)


@pytest.mark.parametrize("count", [0, 1, True, 2.5])
def test_invalid_rank_threshold(count):
    with pytest.raises(ValueError, match="至少"):
        cross_section_rank(pd.DataFrame([[1, 2]]), min_count=count)


def test_minutes_preserve_timestamp_and_same_day_cross_sections():
    data = pool()
    for frame in data.values():
        frame["datetime"] = pd.date_range("2025-01-01 09:30", periods=4, freq="30min")
    result = FactorEngine().compute_cross_section(data, [RankClose()], date=20250101)
    assert len(result) == 12 and result.datetime.nunique() == 4
    assert result.groupby("datetime")[RankClose.name].count().tolist() == [3] * 4


def test_timezone_alignment_is_exact_local_instant():
    data = pool()
    data["B"]["datetime"] = data["B"].datetime.dt.tz_localize("Asia/Shanghai").dt.tz_convert("UTC")
    actual = FactorEngine().compute_matrix(data, RankClose())
    pd.testing.assert_frame_equal(actual, FactorEngine().compute_matrix(pool(), RankClose()))


def test_integer_dates_not_epoch_nanoseconds():
    data = pool()
    data["A"]["datetime"] = [20250101, 20250102, 20250103, 20250104]
    actual = FactorEngine().compute_matrix(data, RankClose())
    pd.testing.assert_frame_equal(actual, FactorEngine().compute_matrix(pool(), RankClose()))


@pytest.mark.parametrize(
    "bad",
    [
        "duplicate",
        "reverse",
        "missing_date",
        "empty",
        "field",
        "units",
        "labels",
        "duplicate_field",
    ],
)
def test_fail_closed_inputs(bad):
    data = pool()
    if bad == "duplicate":
        data["A"].loc[1, "datetime"] = data["A"].loc[0, "datetime"]
    elif bad == "reverse":
        data["A"] = data["A"].iloc[::-1]
    elif bad == "missing_date":
        data["A"].loc[0, "datetime"] = pd.NaT
    elif bad == "empty":
        data["A"] = data["A"].iloc[:0]
    elif bad == "field":
        data["A"] = data["A"].drop(columns="close")
    elif bad == "units":
        data["A"].attrs["factor_input_errors"] = {"close": "复权未知"}
    elif bad == "labels":
        data[""] = data.pop("A")
    else:
        data["A"] = pd.concat([data["A"], data["A"][["close"]]], axis=1)
    with pytest.raises(ValueError):
        FactorEngine().compute_matrix(data, RankClose())


@pytest.mark.parametrize("bad", ["dates", "symbols", "drop", "extra", "array"])
def test_fail_closed_output_axes(bad):
    class Broken(RankClose):
        def compute_panel(self, panel):
            values = super().compute_panel(panel)
            if bad == "dates":
                return values.iloc[::-1]
            if bad == "symbols":
                return values[values.columns[::-1]]
            if bad == "drop":
                return values.iloc[1:]
            if bad == "extra":
                return values.assign(FAKE=1)
            return values.to_numpy()

    with pytest.raises(ValueError, match="轴不一致"):
        FactorEngine().compute_matrix(pool(), Broken())


def test_panel_cannot_mutate_original_or_hide_axis_change():
    data = pool()
    original = data["A"].copy(deep=True)

    class Mutating(RankClose):
        def compute_panel(self, panel):
            panel.fields["close"].iloc[:] = 0
            panel.observed.drop(index=panel.observed.index[0], inplace=True)
            return panel.fields["close"].iloc[1:]

    with pytest.raises(ValueError, match="轴不一致"):
        FactorEngine().compute_matrix(data, Mutating())
    pd.testing.assert_frame_equal(data["A"], original)


def test_absent_observations_cannot_acquire_synthetic_signals():
    data = pool()
    data["A"] = data["A"].iloc[:2]

    class Filled(RankClose):
        def compute_panel(self, panel):
            return pd.DataFrame(99.0, index=panel.observed.index, columns=panel.observed.columns)

    result = FactorEngine().compute_matrix(data, Filled())
    assert result.iloc[2:, 0].isna().all()
    assert result.iloc[:2, 0].eq(99).all()


def test_single_rejected_catalog_matches_execution():
    with pytest.raises(ValueError, match="股票池"):
        FactorEngine().compute_single(pool()["A"], [RankClose()])
    definition = describe_factor(RankClose)
    assert definition["scope"] == "cross_section_panel"
    assert "股票池" in availability_reason(definition, "QFQ")
    assert not availability_reason(definition, "QFQ", evaluation=True)
    assert "compute_panel" in definition["source"]
    assert "explicit_universe" in definition["data_requirements"]
    with pytest.raises(ValueError, match="至少需要 2"):
        FactorEngine().compute_matrix({"A": pool()["A"]}, RankClose())


@pytest.mark.parametrize("field", ["actual_adjust", "category"])
@pytest.mark.parametrize("other", [None, "inconsistent"])
def test_panel_refuses_mixed_or_partly_missing_data_contract(field, other):
    data = pool()
    for frame in data.values():
        frame.attrs["snapshot_metadata"] = {field: "QFQ" if field == "actual_adjust" else "DAY"}
    data["B"].attrs["snapshot_metadata"][field] = other
    with pytest.raises(ValueError, match="不能混用"):
        FactorEngine().compute_matrix(data, RankClose())


def test_rolling_panel_append_future_invariance():
    class RollingRank(RankClose):
        def compute_panel(self, panel):
            return cross_section_rank(rolling_mean(delay(panel.fields["close"]), 2))

    full = FactorEngine().compute_matrix(pool(), RollingRank())
    short = {symbol: frame.iloc[:3] for symbol, frame in pool().items()}
    prefix = FactorEngine().compute_matrix(short, RollingRank())
    pd.testing.assert_frame_equal(full.iloc[:3], prefix)


def test_resource_limit_does_not_truncate(monkeypatch):
    monkeypatch.setattr("easy_tdx.factor.panel.MAX_PANEL_CELLS", 5)
    with pytest.raises(ValueError, match="未截断"):
        FactorEngine().compute_matrix(pool(), RankClose())


def test_cancellation_is_not_a_partial_success():
    control = ComputationControl()

    class Cancel(RankClose):
        def compute_panel(self, panel):
            control.request()
            return panel.fields["close"]

    with pytest.raises(ComputationStopped), computation_scope(control):
        FactorEngine().compute_matrix(pool(), Cancel())


def test_union_calendar_rolling_breaks_on_missing_and_recovers():
    data = pool()
    data["A"] = data["A"].iloc[[0, 2, 3]]
    values = FactorPanel.build(data, ("close",)).fields["close"]
    mean = rolling_mean(values, 2)
    np.testing.assert_allclose(mean.A, [np.nan, np.nan, np.nan, 5], equal_nan=True)
    np.testing.assert_allclose(delay(values).A, [np.nan, 1, np.nan, 3], equal_nan=True)


@pytest.mark.parametrize("bad", [-1, True, 1.5])
def test_negative_future_lag_not_allowed(bad):
    with pytest.raises(ValueError):
        delay(pd.DataFrame([[1]]), bad)


@pytest.mark.parametrize("bad", [-1, 0, True, 1.5])
def test_invalid_rolling_window(bad):
    with pytest.raises(ValueError):
        rolling_mean(pd.DataFrame([[1]]), bad)


def test_whole_pool_runs_once_and_enters_existing_report(monkeypatch):
    calls = []

    class Recorded(RankClose):
        def compute_panel(self, panel):
            calls.append(tuple(panel.observed.columns))
            return super().compute_panel(panel)

    monkeypatch.setitem(FACTORY_REGISTRY, Recorded.name, Recorded)
    data = {
        f"SZ:{i:06d}": pd.DataFrame(
            {
                "datetime": pd.date_range("2025-01-01", periods=40),
                "close": 10 * i * (1 + i / 1000) ** np.arange(40),
            }
        )
        for i in range(1, 7)
    }
    result = cross_section_report(data, [Recorded.name], 1, 3, horizons=[1, 5])
    assert len(calls) == 1 and len(calls[0]) == 6
    assert not result["errors"]
    report = result["reports"][0]
    assert report["coverage"] == 1
    assert report["rank_ic_mean"] == pytest.approx(1)
    # Independent scalar ranks: increasing values receive 1/6,...,6/6;
    # adjacent pairs in three layers have mean daily returns .0015/.0035/.0055.
    assert report["layer_means"] == pytest.approx([0.0015, 0.0035, 0.0055])


@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_real_three_stock_frozen_prices_scalar_ranking_oracle(adjust):
    from tests.unit.test_factor_data import frozen

    data = {
        symbol: frozen(f"{filename}-DAILY-{adjust}.json")
        for symbol, filename in [
            ("SZ:000001", "0-000001"),
            ("SZ:300750", "0-300750"),
            ("SH:600036", "1-600036"),
        ]
    }
    actual = FactorEngine().compute_matrix(data, RankClose())
    lookup = {symbol: dict(zip(frame.datetime, frame.close)) for symbol, frame in data.items()}
    for timestamp, row in actual.iterrows():
        available = {
            symbol: prices[timestamp] for symbol, prices in lookup.items() if timestamp in prices
        }
        for symbol in data:
            if symbol not in available or len(available) < 2:
                assert np.isnan(row[symbol])
                continue
            value = available[symbol]
            less = sum(other < value for other in available.values())
            ties = sum(other == value for other in available.values())
            expected = (less + (ties + 1) / 2) / len(available)
            assert row[symbol] == pytest.approx(expected)


@pytest.mark.asyncio
async def test_panel_archive_reopens_without_execution_and_explicit_recompute(monkeypatch):
    import copy

    from easy_tdx.web.factor_archive import validate_factor_archive
    from easy_tdx.web.routers import research
    from tests.unit.test_factor_archive import record
    from tests.unit.test_factor_data import frozen

    monkeypatch.setitem(FACTORY_REGISTRY, RankClose.name, RankClose)

    async def fetch(*args):
        # Synthetic six-stock pool from a real frozen tape, not six real stocks.
        frame = frozen("0-000001-DAILY-NONE.json").copy()
        frame[["open", "high", "low", "close"]] *= 1 + int(args[3][-1]) / 100
        return frame

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 7)],
        factors=[RankClose.name],
        count=160,
        adjust="NONE",
    )
    result = (await research.factor_evaluate(req, None, None)).data
    assert not result["errors"]
    source = {
        "format": "factor-research-v1",
        "mode": "evaluation",
        "title": "整池合成验收",
        "savedAt": "2026-10-10T10:00:00Z",
        "result": result,
    }
    before = copy.deepcopy(source)
    with monkeypatch.context() as guard:
        guard.setattr(RankClose, "compute_panel", lambda *a: pytest.fail("read must not execute"))
        validate_factor_archive(source)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("no live prices"))
    newer = research.recompute_factor_payload(record(source))
    validate_factor_archive(newer)
    assert newer["result"]["reports"] == result["reports"]
    assert newer["result"]["latest"] == result["latest"]
    assert len(newer["result"]["input_snapshots"]) == 6
    assert source == before
