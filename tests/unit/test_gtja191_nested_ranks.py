"""Independent complete-window oracle for nested rank/correlation formulas."""

import copy
import math
import statistics
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine
from easy_tdx.factor.configuration import configure_factor
from tests.unit.test_gtja191_panel_compound import lag, pairs, roll, xs
from tests.unit.test_gtja191_vwap import long_frozen, sample

DEFAULTS = {
    64: dict(corr=4, price_decay=4, volume_mean=60, rank_corr=4, peak=13, corr_decay=14),
    119: dict(
        volume_mean=5,
        volume_sum=26,
        corr=5,
        price_decay=7,
        rank_volume_mean=15,
        rank_corr=21,
        trough=9,
        rank=7,
        rank_decay=8,
    ),
    121: dict(price_trough=12, price_rank=20, volume_mean=60, volume_rank=2, corr=18, corr_rank=3),
    138: dict(
        lag=3,
        price_decay=20,
        price_rank=8,
        volume_mean=60,
        volume_rank=17,
        corr=5,
        corr_rank=19,
        rank_decay=16,
        outer_rank=7,
    ),
    140: dict(
        price_decay=8,
        price_rank=8,
        volume_mean=60,
        volume_rank=20,
        corr=8,
        corr_decay=7,
        corr_rank=3,
    ),
    157: dict(lag=5, inner_min=2, sum=1, product=1, outer_min=5, return_lag=6, return_rank=5),
    159: dict(short=6, middle=12, long=24),
}
INPUTS = {
    64: ("close", "volume", "vwap"),
    119: ("open", "volume", "vwap"),
    121: ("volume", "vwap"),
    138: ("low", "volume", "vwap"),
    140: ("open", "close", "high", "low", "volume"),
    157: ("close",),
    159: ("close", "high", "low"),
}
WARMUP = {64: 88, 119: 56, 121: 80, 138: 119, 140: 94, 157: 12, 159: 25}


def custom(n, size=3):
    return {k: size + {"middle": 1, "long": 2}.get(k, 0) for k in DEFAULTS[n]}


def active_sample(size):
    """Explicit stress data, not market data: changing ranks through deep windows."""
    data = sample(size)
    for i, f in enumerate(data.values()):
        rng = np.random.default_rng(1200 + i)
        f["close"] = rng.uniform(20, 40, size)
        f["open"] = f.close + rng.uniform(-1, 1, size)
        f["high"] = np.maximum(f.close, f.open) + rng.uniform(0.1, 2, size)
        f["low"] = np.minimum(f.close, f.open) - rng.uniform(0.1, 2, size)
        f["vwap"] = (f.high + f.low) / 2
        f["volume"] = 1.3 ** np.arange(size) * rng.uniform(100, 2000, size)
    return data


def warmup(n, p):
    if n == 64:
        return max(
            p["corr"] + p["price_decay"] - 1,
            p["volume_mean"] + p["rank_corr"] + p["peak"] + p["corr_decay"] - 3,
        )
    if n == 119:
        return max(
            p["volume_mean"] + p["volume_sum"] + p["corr"] + p["price_decay"] - 3,
            p["rank_volume_mean"] + p["rank_corr"] + p["trough"] + p["rank"] + p["rank_decay"] - 4,
        )
    if n == 121:
        return max(
            p["price_trough"],
            p["price_rank"] + p["corr"] + p["corr_rank"] - 2,
            p["volume_mean"] + p["volume_rank"] + p["corr"] + p["corr_rank"] - 3,
        )
    if n == 138:
        return max(
            p["lag"] + p["price_decay"],
            p["price_rank"] + p["corr"] + p["corr_rank"] + p["rank_decay"] + p["outer_rank"] - 4,
            p["volume_mean"]
            + p["volume_rank"]
            + p["corr"]
            + p["corr_rank"]
            + p["rank_decay"]
            + p["outer_rank"]
            - 5,
        )
    if n == 140:
        return max(
            p["price_decay"],
            p["price_rank"] + p["corr"] + p["corr_decay"] + p["corr_rank"] - 3,
            p["volume_mean"] + p["volume_rank"] + p["corr"] + p["corr_decay"] + p["corr_rank"] - 4,
        )
    if n == 157:
        return max(
            p["lag"] + p["inner_min"] + p["sum"] + p["product"] + p["outer_min"] - 3,
            p["return_lag"] + p["return_rank"] + 1,
        )
    if n == 159:
        return p["long"] + 1
    raise AssertionError(n)


def independent(data, n, p):
    dates = sorted({d for f in data.values() for d in f.datetime})
    if n == 159 and len(data) > 1:
        return np.column_stack(
            [
                pd.Series(independent({s: f}, n, p).ravel(), index=f.datetime).reindex(dates)
                for s, f in data.items()
            ]
        )
    shape = len(dates), len(data)
    fields = {k: np.full(shape, np.nan) for k in INPUTS[n]}
    for j, f in enumerate(data.values()):
        for row in f.to_dict("records"):
            for k in fields:
                fields[k][dates.index(row["datetime"]), j] = row[k]
    valid = np.ones(shape, dtype=bool)
    for k, a in fields.items():
        valid &= np.isfinite(a) & (a >= 0 if k == "volume" else a > 0)
    for top, bottom in [
        ("high", "low"),
        ("high", "open"),
        ("high", "close"),
        ("open", "low"),
        ("close", "low"),
    ]:
        if top in fields and bottom in fields:
            valid &= fields[top] >= fields[bottom]
    blank = np.full(shape, np.nan)
    c, o, h, lo, v, w = [
        np.where(valid, fields.get(k, blank), np.nan)
        for k in ("close", "open", "high", "low", "volume", "vwap")
    ]

    def mask(a, length):
        return np.where(roll(valid.astype(float), length, sum) == length, a, np.nan)

    def tr(a, length):
        return roll(
            a,
            length,
            lambda x: (sum(y < x[-1] for y in x) + (sum(y == x[-1] for y in x) + 1) / 2) / length,
        )

    def mean(a, length):
        return roll(a, length, statistics.mean)

    def total(a, length):
        return roll(a, length, math.fsum)

    def decay(a, length, bound=None):
        def fn(x):
            if bound:
                return float(
                    sum((i + 1) * Fraction(y).limit_denominator(bound) for i, y in enumerate(x))
                    / (length * (length + 1) // 2)
                )
            return math.fsum((i + 1) * y for i, y in enumerate(x)) / (length * (length + 1) / 2)

        return roll(a, length, fn)

    def ts_corr(a):
        return pairs(
            tr(a, p["price_rank"]),
            tr(mean(v, p["volume_mean"]), p["volume_rank"]),
            p["corr"],
            rank_bounds=(2 * p["price_rank"], 2 * p["volume_rank"]),
        )

    with np.errstate(all="ignore"):
        if n == 64:
            a = pairs(xs(w), xs(v), p["corr"], rank_bounds=(2 * len(data),) * 2)
            b = pairs(
                xs(c),
                xs(mean(v, p["volume_mean"])),
                p["rank_corr"],
                rank_bounds=(2 * len(data),) * 2,
            )
            out = -np.maximum(
                xs(decay(a, p["price_decay"])), xs(decay(roll(b, p["peak"], max), p["corr_decay"]))
            )
        elif n == 119:
            a = pairs(w, total(mean(v, p["volume_mean"]), p["volume_sum"]), p["corr"])
            b = pairs(
                xs(o),
                xs(mean(v, p["rank_volume_mean"])),
                p["rank_corr"],
                rank_bounds=(2 * len(data),) * 2,
            )
            out = xs(decay(a, p["price_decay"])) - xs(
                decay(tr(roll(b, p["trough"], min), p["rank"]), p["rank_decay"], 2 * p["rank"])
            )
        elif n == 121:
            a = xs(w - roll(w, p["price_trough"], min))
            b = tr(ts_corr(w), p["corr_rank"])
            out = np.where(np.isfinite(a) & np.isfinite(b), -(a**b), np.nan)
        elif n == 138:
            mix = 0.7 * lo + 0.3 * w
            a = xs(decay(mask(mix - lag(mix, p["lag"]), p["lag"] + 1), p["price_decay"]))
            b = tr(
                decay(tr(ts_corr(lo), p["corr_rank"]), p["rank_decay"], 2 * p["corr_rank"]),
                p["outer_rank"],
            )
            out = b - a
        elif n == 140:
            ranks = [xs(x) for x in (o, lo, h, c)]
            contrast = np.full(shape, np.nan)
            for i in range(shape[0]):
                for j in range(shape[1]):
                    vals = [x[i, j] for x in ranks]
                    if all(map(math.isfinite, vals)):
                        contrast[i, j] = float(
                            sum(
                                sign * Fraction(float(x)).limit_denominator(2 * len(data))
                                for sign, x in zip((1, 1, -1, -1), vals)
                            )
                        )
            a = xs(decay(contrast, p["price_decay"], 2 * len(data)))
            b = tr(decay(ts_corr(c), p["corr_decay"]), p["corr_rank"])
            out = np.minimum(a, b)
        elif n == 157:
            a = xs(xs(-xs(mask(c - lag(c, p["lag"]), p["lag"] + 1))))
            summed = roll(
                roll(a, p["inner_min"], min),
                p["sum"],
                lambda values: float(
                    sum(Fraction(float(x)).limit_denominator(2 * len(data)) for x in values)
                ),
            )
            b = xs(xs(np.log(summed)))
            out = roll(roll(b, p["product"], math.prod), p["outer_min"], min) + tr(
                lag(-(c / lag(c) - 1), p["return_lag"]), p["return_rank"]
            )
        elif n == 159:
            bottom = np.minimum(lo, lag(c))
            span = np.maximum(h, lag(c)) - bottom
            ratios = [
                (c - total(bottom, p[k])) / total(span, p[k]) for k in ("short", "middle", "long")
            ]
            short, mid, long = p["short"], p["middle"], p["long"]
            out = (
                (ratios[0] * mid * long + ratios[1] * short * long + ratios[2] * short * long)
                * 100
                / (short * mid + short * long + mid * long)
            )
        else:
            raise AssertionError(n)
    return np.where(np.isfinite(out), mask(out, warmup(n, p)), np.nan)


def calculate(data, n, p=None):
    return FactorEngine().compute_matrix(data, configure_factor(f"gtja191_{n:03d}", p or {}))


@pytest.mark.parametrize("n", sorted(DEFAULTS))
@pytest.mark.parametrize("size", [None, 3, 7])
def test_nested_independent_defaults_custom_causal_order(n, size):
    p = DEFAULTS[n] if size is None else custom(n, size)
    seen_finite = False
    # Smooth data exercises time ranks; fast rank-changing data exercises
    # cross-sectional correlations. A constant intermediate rank remains NaN.
    for data in (sample(300), active_sample(300)):
        out = calculate(data, n, p)
        np.testing.assert_allclose(out, independent(data, n, p), equal_nan=True, atol=2e-10)
        seen_finite |= out.notna().any().any()
        assert out.iloc[: warmup(n, p) - 1].isna().all().all()
        pd.testing.assert_frame_equal(
            out.iloc[:280], calculate({s: f.iloc[:280] for s, f in data.items()}, n, p)
        )
        pd.testing.assert_frame_equal(
            out, calculate(dict(reversed(list(data.items()))), n, p)[out.columns]
        )
    assert seen_finite


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_nested_invalid_missing_constant_zero_recovery(n):
    p, data = custom(n), active_sample(180)
    for k in INPUTS[n]:
        changed = copy.deepcopy(data)
        for s, pos, bad in [("S0", 20, np.nan), ("S1", 24, np.inf), ("S2", 28, -1.0)]:
            changed[s].loc[pos, k] = bad
        changed["S3"] = changed["S3"].drop(index=33)
        out = calculate(changed, n, p)
        np.testing.assert_allclose(out, independent(changed, n, p), equal_nan=True, atol=2e-10)
        assert out.iloc[80:].notna().any().any()
    for f in data.values():
        for k in ("open", "high", "low", "close", "vwap"):
            f[k] = 10.0
        f["volume"] = 0.0
    out = calculate(data, n, p)
    np.testing.assert_allclose(out, independent(data, n, p), equal_nan=True, atol=2e-10)
    if n != 157:
        assert out.isna().all().all()


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_nested_real_ten_stock_default_values(n):
    stocks = [
        (0, "000001"),
        (0, "300750"),
        (1, "600036"),
        (0, "000002"),
        (0, "000100"),
        (0, "000725"),
        (1, "600050"),
        (1, "600000"),
        (1, "600015"),
        (1, "601998"),
    ]
    data = {s: long_frozen(f"{m}-{s}-DAILY-NONE.json") for m, s in stocks}
    out = calculate(data, n)
    np.testing.assert_allclose(out, independent(data, n, DEFAULTS[n]), equal_nan=True, atol=2e-10)
    if n == 64:
        # This real pool has insufficient continuously varying cross-sectional
        # ranks for both correlation paths. Missing is correct, not a zero.
        assert out.isna().all().all()
    else:
        assert out.notna().any().any()


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_nested_metadata_inputs_adjustment_cancel(n, monkeypatch):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import gtja191
    from easy_tdx.factor.catalog import describe_factor

    factor = configure_factor(f"gtja191_{n:03d}")
    assert factor.spec.inputs == INPUTS[n]
    assert factor.spec.resolved_parameters == DEFAULTS[n]
    assert factor.spec.warmup == WARMUP[n] == warmup(n, DEFAULTS[n])
    assert factor.spec.panel == (n != 159)
    assert describe_factor(type(factor))["implementation_version"] == gtja191.VERSION
    data = sample(40)
    if n != 159:
        with pytest.raises(ValueError, match="股票池"):
            factor.compute(data["S0"])
    for k in INPUTS[n]:
        with pytest.raises(ValueError):
            calculate({s: f.drop(columns=k) for s, f in data.items()}, n)
    for k in DEFAULTS[n]:
        with pytest.raises(ValueError):
            configure_factor(f"gtja191_{n:03d}", {k: 0})
    if "vwap" in INPUTS[n]:
        for f in data.values():
            f.attrs["snapshot_metadata"]["actual_adjust"] = "QFQ"
        with pytest.raises(ValueError):
            calculate(data, n)

    def stop():
        raise ComputationStopped("cancelled")

    monkeypatch.setattr(gtja191, "computation_checkpoint", stop)
    with pytest.raises(ComputationStopped):
        calculate(sample(40), n, custom(n))


def test_nested_rank_contrast_exact_zero_and_time_rank_weights():
    from easy_tdx.factor.builtin.gtja191 import (
        _linear_rank_mean,
        _rank_price_contrast,
        _rank_window_sum,
    )

    # One-stock shape deliberately smaller than the time-rank denominator.
    out = _linear_rank_mean(pd.DataFrame({"a": [1 / 14, 3 / 14, 2 / 14]}), 3, denominator_bound=14)
    assert out.a.iloc[-1] == float(Fraction(13, 84))
    a = pd.DataFrame([[1 / 3, 2 / 3, 1.0]])
    b = pd.DataFrame([[2 / 3, 1 / 3, 1.0]])
    z = _rank_price_contrast(a, b, b, a)
    assert (z == 0).all().all()
    ranks = pd.DataFrame(
        {
            "a": [0.2, 0.4, 0.6],
            "b": [0.4, 0.4, 0.4],
            "c": [1.0, 1.0, 1.0],
            "d": [0.2, 0.2, 0.2],
            "e": [0.8, 0.8, 0.8],
        }
    )
    assert _rank_window_sum(ranks, 3).iloc[-1, 0] == _rank_window_sum(ranks, 3).iloc[-1, 1] == 1.2


def test_nested_159_literal_weights_and_parameter_order():
    f = pd.DataFrame(
        dict(
            datetime=pd.date_range("2025-01-01", periods=5),
            close=[10.0] * 5,
            high=[12.0] * 5,
            low=[8.0] * 5,
        )
    )
    p = dict(short=1, middle=2, long=3)
    # Q1=.5, Q2=-.75, Q3=-7/6; last coefficient is 1*3, NOT 1*2.
    assert calculate({"A": f}, 159, p).iloc[-1, 0] == pytest.approx(-25.0)
    for bad in [dict(short=2, middle=2, long=3), dict(short=1, middle=3, long=3)]:
        with pytest.raises(ValueError):
            configure_factor("gtja191_159", bad)


def test_nested_159_real_minute_single_series():
    f = long_frozen("0-300750-MIN_30-NONE.json")
    out = calculate({"300750": f}, 159)
    np.testing.assert_allclose(out, independent({"300750": f}, 159, DEFAULTS[159]), equal_nan=True)
    assert out.notna().any().any()


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [(64, 119, 121, 138), (140, 157, 159)])
async def test_nested_research_archive_readonly_recompute(monkeypatch, group):
    from easy_tdx.factor.builtin.gtja191 import GTJAFactor, GTJAPanelFactor
    from easy_tdx.web.factor_archive import validate_factor_archive
    from easy_tdx.web.routers import research
    from tests.unit.test_factor_archive import record
    from tests.unit.test_factor_data import frozen
    from tests.unit.test_gtja191_archive import envelope

    async def fetch(*args):
        f = frozen("0-000001-DAILY-NONE.json").copy()
        rng = np.random.default_rng(1300 + int(args[3][-1]))
        # Explicit synthetic, independently qualifying price/volume units.
        scale = rng.uniform(0.8, 1.2, len(f))
        volume_scale = 1.3 ** np.arange(len(f)) * rng.uniform(0.1, 2, len(f))
        f[["open", "high", "low", "close"]] = f[["open", "high", "low", "close"]].mul(scale, axis=0)
        f["vol"] *= volume_scale
        f["amount"] *= scale * volume_scale
        return f

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda f: f)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 7)],
        factors=[f"gtja191_{n:03d}" for n in group],
        count=160,
        adjust="NONE",
        factor_parameters={f"gtja191_{n:03d}": custom(n) for n in group},
    )
    result = (await research.factor_evaluate(req, None, None)).data
    assert not result["errors"]
    original = envelope(result, "evaluation")
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(GTJAPanelFactor, "compute_panel", lambda *a: pytest.fail("read computes"))
        guard.setattr(GTJAFactor, "compute", lambda *a: pytest.fail("read computes"))
        validate_factor_archive(original)
    with monkeypatch.context() as guard:
        guard.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("recompute fetches"))
        newer = research.recompute_factor_payload(record(original))
    validate_factor_archive(newer)
    assert newer["result"]["reports"] == result["reports"]
    assert newer["result"]["latest"] == result["latest"]
    assert original == before
