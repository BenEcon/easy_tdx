"""GTJA143: hand products + exact rational oracle independent of Decimal state."""

import copy
import math
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor


def independent(close):
    output = []
    segment = []
    for price in close:
        if not math.isfinite(price) or price <= 0:
            segment = []
            output.append(np.nan)
            continue
        segment.append(Fraction(str(float(price))))
        if len(segment) < 2:
            output.append(np.nan)
            continue
        # Rebuild the product, not the production recursive implementation.
        exact = math.prod(
            ((b - a) / a for a, b in zip(segment, segment[1:]) if b > a),
            start=Fraction(1),
        )
        try:
            value = float(exact)
        except OverflowError:
            value = np.inf
        output.append(value if math.isfinite(value) and value > 0 else np.nan)
    return np.array(output)


def frame(close):
    return pd.DataFrame(
        {"datetime": pd.date_range("2025-01-01", periods=len(close), freq="B"), "close": close}
    )


def calculate(close):
    return configure_factor("gtja191_143").compute(frame(close)).to_numpy()


def test_self_hand_seed_constant_and_history_origin():
    close = [10.0, 11.0, 10.0, 12.0, 12.0, 9.0, 18.0]
    np.testing.assert_allclose(calculate(close), [np.nan, 0.1, 0.1, 0.02, 0.02, 0.02, 0.02])
    np.testing.assert_allclose(calculate(close), independent(close), rtol=1e-14)
    assert calculate([10.0, 10.0, 9.0]).tolist()[1:] == [1.0, 1.0]
    assert calculate([11.0, 10.0])[-1] == 1  # Truncation changes the starting seed.
    assert calculate(close)[2] == 0.1
    assert len(calculate([])) == 0
    assert np.isnan(calculate([10.0])).all()


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, 0.0, -1.0])
def test_self_invalid_prices_reset_and_recover(bad):
    close = [10.0, 11.0, bad, 20.0, 22.0, 20.0, 24.0]
    out = calculate(close)
    np.testing.assert_allclose(out, independent(close), rtol=1e-14)
    assert np.isnan(out[2:4]).all()
    assert out[4] == 0.1
    assert out[-1] == 0.02


def test_self_underflow_overflow_preserves_state_and_decimal_ties():
    # 1e-3 ** 110 underflows float64; a subsequent large return recovers.
    close = [v for _ in range(110) for v in (1.0, 1.001)] + [1e-310, 1.0]
    out = calculate(close)
    np.testing.assert_allclose(out, independent(close), rtol=1e-12, atol=0)
    assert np.isnan(out[-3:-1]).all()
    assert 0 < out[-1] < 1e-19
    # Overflow must also preserve state, not reset to 1 or infinity forever.
    close = [1e-310, 1.0, *[v for _ in range(10) for v in (1.0, 1.001)]]
    out = calculate(close)
    np.testing.assert_allclose(out, independent(close), rtol=1e-12, atol=0)
    assert np.isnan(out[1]) and np.isfinite(out[-1])
    close = [1.0, np.nextafter(1.0, 2.0), np.nextafter(1.0, 2.0)]
    np.testing.assert_array_equal(calculate(close)[1:], [2e-16, 2e-16])
    assert not np.any(calculate([v for _ in range(120) for v in (1.0, 1.001)]) == 0)


def test_self_pool_prefix_permutation_missing_dates_and_inputs():
    from tests.unit.test_gtja191_vwap import sample

    data = sample(160)
    data["S0"] = data["S0"].drop(index=45)
    data["S1"].loc[50, "close"] = np.nan
    original = copy.deepcopy(data)
    factor = configure_factor("gtja191_143")
    values = FactorEngine().compute_matrix(data, factor)
    for symbol, f in data.items():
        expected = pd.Series(independent(f.close), index=f.datetime).reindex(values.index)
        np.testing.assert_allclose(values[symbol], expected, rtol=1e-12, atol=0)
        pd.testing.assert_frame_equal(f, original[symbol])
    cutoff = values.index[80]
    prefix = FactorEngine().compute_matrix(
        {s: f[f.datetime <= cutoff] for s, f in data.items()}, factor
    )
    pd.testing.assert_frame_equal(values.loc[:cutoff], prefix)
    reverse = FactorEngine().compute_matrix(dict(reversed(list(data.items()))), factor)
    pd.testing.assert_frame_equal(values, reverse.reindex(columns=values.columns))
    with pytest.raises(ValueError):
        FactorEngine().compute_matrix({"A": frame([1.0, 2.0]).drop(columns="close")}, factor)


@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_self_real_stocks_periods_adjustments(adjust):
    from tests.unit.test_factor_data import FILES, frozen
    from tests.unit.test_gtja191_vwap import long_frozen

    for path in FILES:
        if path.endswith(f"-{adjust}.json"):
            close = frozen(path).close
            np.testing.assert_allclose(calculate(close), independent(close), rtol=1e-12, atol=0)
            assert np.isfinite(calculate(close)).any()
    if adjust == "NONE":
        for path in (
            "0-000001-DAILY-NONE.json",
            "0-300750-DAILY-NONE.json",
            "1-600036-DAILY-NONE.json",
            "0-300750-MIN_30-NONE.json",
        ):
            close = long_frozen(path).close
            np.testing.assert_allclose(calculate(close), independent(close), rtol=1e-12, atol=0)


def test_self_tiny_research_values_are_not_collapsed_to_zero():
    from easy_tdx.factor.statistics import mad_zscore, stable_correlation

    values = pd.Series(
        [
            calculate([v for _ in range(98) for v in (1.0, 1.001)] + [1.0, 1.0 + i / 1000])[-1]
            for i in range(1, 7)
        ]
    )
    assert values.gt(0).all() and values.lt(1e-296).all()
    expected = np.arange(1.0, 7.0)
    for rank in (False, True):
        assert stable_correlation(values, pd.Series(expected), rank=rank) == pytest.approx(1.0)
    np.testing.assert_allclose(
        mad_zscore(values),
        (expected - expected.mean()) / expected.std(ddof=1),
        rtol=1e-12,
    )


def test_self_metadata_and_midway_cancellation(monkeypatch):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import gtja191

    factor = configure_factor("gtja191_143")
    meta = describe_factor(type(factor))
    assert meta["warmup_bars"] == 2
    assert meta["parameters"] == {}
    assert meta["resolved_parameters"] == {}
    assert meta["available"] and meta["evaluation_available"]
    assert meta["implementation_version"] == gtja191.VERSION
    assert "种子1" in meta["warmup_note"]
    assert any("历史起点" in note for note in meta["limitations"])
    assert any("80位" in note for note in meta["limitations"])
    assert not any("每层独立暖机" in note for note in meta["limitations"])
    for params in ({"window": 5}, {"seed": 2}):
        with pytest.raises(ValueError):
            configure_factor(factor.name, params)
    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ComputationStopped("cancelled in recursion")

    monkeypatch.setattr(gtja191, "computation_checkpoint", checkpoint)
    with pytest.raises(ComputationStopped):
        calculate([10.0, 11.0] * 200)
    assert calls == 3


@pytest.mark.asyncio
async def test_self_research_archive_readonly_recompute(monkeypatch):
    from easy_tdx.factor.builtin.gtja191 import GTJAFactor
    from easy_tdx.web.factor_archive import validate_factor_archive
    from easy_tdx.web.routers import research
    from tests.unit.test_factor_archive import record
    from tests.unit.test_gtja191_archive import envelope
    from tests.unit.test_gtja191_vwap import sample

    pool = sample(100)

    async def fetch(*args):
        from easy_tdx.web.bar_snapshot import annotate_snapshot

        f = pool[f"S{int(args[3][-1])}"].copy()
        f.attrs["snapshot_metadata"] = annotate_snapshot(
            f.to_dict("records"),
            "DAY",
            source="SYNTHETIC_QA",
            requested_adjust="QFQ",
            actual_adjust="QFQ",
            bar_time="end",
        )["metadata"]
        return f

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda f: f)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(len(pool))],
        factors=["gtja191_143"],
        count=100,
        adjust="QFQ",
    )
    result = (await research.factor_evaluate(req, None, None)).data
    assert not result["errors"]
    original = envelope(result, "evaluation")
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(GTJAFactor, "compute", lambda *a: pytest.fail("read computes"))
        validate_factor_archive(original)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("no live data"))
    newer = research.recompute_factor_payload(record(original))
    validate_factor_archive(newer)
    assert newer["result"]["reports"] == result["reports"]
    assert newer["result"]["latest"] == result["latest"]
    assert original == before
