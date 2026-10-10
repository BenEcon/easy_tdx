"""Independent numerical counterexamples; no market significance is implied."""

from decimal import Decimal, localcontext

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FACTORY_REGISTRY, Factor
from easy_tdx.factor.research import cross_section_report
from easy_tdx.factor.statistics import (
    NUMERIC_POLICY,
    RELATIVE_TOLERANCE,
    STATISTICS_VERSION,
    coalesced,
    mad_zscore,
    stable_correlation,
)


def decimal_correlation(x, y):
    # Independent high-precision arithmetic on the actual representable inputs.
    with localcontext() as ctx:
        ctx.prec = 100
        a, b = [[Decimal.from_float(float(v)) for v in row] for row in (x, y)]
        a = [v - sum(a) / len(a) for v in a]
        b = [v - sum(b) / len(b) for v in b]
        return float(
            sum(u * v for u, v in zip(a, b))
            / (sum(v * v for v in a) * sum(v * v for v in b)).sqrt()
        )


@pytest.mark.parametrize("scale", [1e-300, 1e-100, 1.0, 1e100, 1e300])
def test_small_and_large_real_dispersion_is_preserved(scale):
    x = pd.Series(np.array([-3, -1, 0, 1, 2, 4], dtype=float) * scale)
    y = pd.Series([2.0, -1.0, 7.0, 3.0, 4.0, 1.0])
    assert stable_correlation(x, y) == pytest.approx(decimal_correlation(x, y), abs=2e-15)
    assert stable_correlation(x, y, rank=True) == pytest.approx(1 / 7)
    assert np.isfinite(mad_zscore(x)).all()
    np.testing.assert_allclose(mad_zscore(x), mad_zscore(x / scale), atol=1e-15)


def test_large_common_offset_does_not_lose_resolvable_low_bits():
    x = pd.Series(1e14 + np.arange(6, dtype=float))
    y = pd.Series([2.0, 1.0, 7.0, 3.0, 4.0, 0.0])
    assert stable_correlation(x, y) == pytest.approx(decimal_correlation(x, y), abs=2e-15)
    np.testing.assert_allclose(mad_zscore(x), mad_zscore(x - 1e14), atol=1e-15)


@pytest.mark.parametrize("rank", [False, True])
def test_proportional_price_return_roundoff_is_not_information(rank):
    x = pd.Series(range(8), dtype=float)
    y = pd.Series([-0.015503861641813277, -0.015503861641813166] * 4)
    assert stable_correlation(x, y, rank=rank, y_floor=1.0) is None
    # No hard absolute floor for factor-factor comparisons, even tiny inputs.
    assert stable_correlation(x * 1e-200, (x + 1) * 1e-200, rank=rank) == pytest.approx(1)


def test_ties_use_average_rank_and_do_not_split_on_roundoff():
    x = pd.Series([1.0, np.nextafter(1.0, 2.0), 2.0, 3.0, 3.0, 4.0])
    y = pd.Series([6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
    expected = decimal_correlation([1.5, 1.5, 3.0, 4.5, 4.5, 6.0], y)
    assert stable_correlation(x, y, rank=True) == pytest.approx(expected)


def test_tie_clusters_are_bounded_not_transitively_chained_and_order_independent():
    step = 0.75 * RELATIVE_TOLERANCE
    x = pd.Series([1.0, 1.0 + step, 1.0 + 2 * step, 1.0 + 3 * step], index=list("abcd"))
    merged = coalesced(x)
    assert merged.nunique() == 2
    assert merged.a == merged.b and merged.c == merged.d
    pd.testing.assert_series_equal(coalesced(x.iloc[::-1]).reindex(x.index), merged)
    # A remote large value must not set a global absolute threshold.
    assert coalesced(pd.Series([1e-100, 2e-100, 3e-100, 1e100])).nunique() == 4


def test_missing_and_inf_align_by_index_without_mutating_inputs():
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, np.inf, np.nan], index=list("abcdefg"))
    y = pd.Series([7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0], index=list("gfedcba"))
    before = x.copy()
    assert stable_correlation(x, y) == pytest.approx(1)
    assert stable_correlation(x.iloc[:4], y) is None
    pd.testing.assert_series_equal(x, before)
    assert coalesced(x).iloc[-2:].isna().all()


@pytest.mark.parametrize(
    "data", [[1.0] * 6, [1.0 + n * np.finfo(float).eps for n in range(6)], [np.nan] * 6]
)
def test_constant_preprocess_does_not_amplify_noise(data):
    assert mad_zscore(pd.Series(data)).isna().all()


def test_mad_is_sample_standardization_and_zero_mad_keeps_minority():
    x = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0, 100.0, np.nan])
    result = mad_zscore(x)
    assert result.iloc[-1:].isna().all()
    assert result.iloc[5] > result.iloc[0]
    assert result.mean() == pytest.approx(0, abs=1e-15)
    assert result.std(ddof=1) == pytest.approx(1)


def test_mad_preserves_tiny_majority_before_scaling_extreme_outlier():
    x = pd.Series([1e-200, 2e-200, 3e-200, 4e-200, 5e-200, 1e200])
    # Independent manual median=3.5, MAD=1.5; cap=3.5+3*1.4826*1.5.
    clipped = np.array([1, 2, 3, 4, 5, 3.5 + 3 * 1.4826 * 1.5])
    expected = (clipped - clipped.mean()) / clipped.std(ddof=1)
    np.testing.assert_allclose(mad_zscore(x), expected, atol=2e-15)


def test_extreme_opposite_values_do_not_overflow_center_or_variance():
    x = pd.Series([-1.7e308, -1.6e308, -1.5e308, 1.5e308, 1.6e308, 1.7e308])
    assert stable_correlation(x, -x) == pytest.approx(-1)
    assert np.isfinite(mad_zscore(x)).all()
    assert mad_zscore(x).std() == pytest.approx(1)


class NumericScore(Factor):
    name = "qa_numerics"
    category = "technical"
    description = "Synthetic numerical acceptance only"
    inputs = ("open",)

    def compute(self, frame):
        return frame["open"]


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setitem(FACTORY_REGISTRY, NumericScore.name, NumericScore)
    t = np.arange(45, dtype=float)
    base = 10 + 0.01 * t + np.sin(t / 5)
    return {
        f"SZ:{n:06d}": pd.DataFrame(
            {
                "datetime": pd.date_range("2025-01-01", periods=len(t), freq="B"),
                "close": base * (1 + n * 0.07),
                "open": float(n),
            }
        )
        for n in range(1, 9)
    }


@pytest.mark.parametrize("preprocess", ["raw", "mad_zscore"])
def test_report_equal_returns_null_ic_but_descriptive_layers_are_retained(pool, preprocess):
    result = cross_section_report(pool, [NumericScore.name], 5, 3, preprocess)
    report = result["reports"][0]
    assert result["statistics_version"] == STATISTICS_VERSION
    assert result["numeric_policy"] == NUMERIC_POLICY
    assert report["observations"] == 0 and report["rank_ic_mean"] is None
    assert report["coverage"] == 1
    assert report["layer_dates"] == 40 and report["spread"] == 0
    assert all(
        row["layer_spread"] == 0 and "收益为常数或近常数" in row["reason"]
        for row in report["daily"][:-5]
    )
    assert all(row["layer_spread"] is None for row in report["daily"][-5:])
    assert all(v is not None for v in report["layer_means"])
    # Complete labels remain causal. Pool ordering cannot produce fictitious rank.
    early = cross_section_report(
        {k: v.iloc[:35] for k, v in pool.items()}, [NumericScore.name], 5, 3, preprocess
    )
    assert early["reports"][0]["daily"][:30] == report["daily"][:30]
    reverse = cross_section_report(
        dict(reversed(list(pool.items()))), [NumericScore.name], 5, 3, preprocess
    )
    assert reverse["reports"] == result["reports"]


@pytest.mark.parametrize("preprocess", ["raw", "mad_zscore"])
def test_report_near_constant_factor_has_no_artificial_layers(pool, preprocess):
    for n, frame in enumerate(pool.values()):
        frame["open"] = 1 + n * np.finfo(float).eps
    report = cross_section_report(pool, [NumericScore.name], 1, 3, preprocess)["reports"][0]
    assert report["coverage"] == 1
    assert report["observations"] == 0 and report["layer_dates"] == 0
    assert report["spread"] is None and report["layer_means"] == [None] * 3
    assert any("近常数" in reason for reason in report["diagnostics"])
