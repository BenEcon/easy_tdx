"""Independent matrix/list oracle: exact-date pools, never per-stock rank substitutes."""

import copy
import math
import statistics
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine
from easy_tdx.factor.builtin.gtja191 import SPECS, GTJAFactor, GTJAPanelFactor
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor
from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import frozen
from tests.unit.test_gtja191_archive import envelope

DEFAULTS = {
    1: dict(lag=1, corr=6),
    10: dict(volatility=20, peak=5),
    32: dict(corr=3, sum=3),
    37: dict(sum=5, lag=10),
    42: dict(volatility=10, corr=10),
    48: dict(direction=3, short=5, long=20),
    62: dict(corr=5),
    83: dict(covariance=5),
    91: dict(peak=5, volume_mean=40, corr=5),
    99: dict(covariance=5),
    104: dict(corr=5, lag=5, volatility=20),
    105: dict(corr=10),
    107: dict(lag=1),
    113: dict(lag=5, mean=20, corr=2, short=5, long=20),
    115: dict(corr=10, volume_mean=30, price_rank=4, volume_rank=10, rank_corr=7),
    136: dict(lag=3, corr=10),
    142: dict(price_rank=10, lag=1, volume_mean=20, volume_rank=5),
    148: dict(volume_mean=60, sum=9, corr=6, trough=14),
    176: dict(range=12, corr=6),
    184: dict(lag=1, corr=200),
}
INPUTS = {
    1: ("open", "close", "volume"),
    10: ("close",),
    32: ("high", "volume"),
    37: ("open", "close"),
    42: ("high", "volume"),
    48: ("close", "volume"),
    62: ("high", "volume"),
    83: ("high", "volume"),
    91: ("close", "low", "volume"),
    99: ("close", "volume"),
    104: ("high", "close", "volume"),
    105: ("open", "volume"),
    107: ("open", "high", "close", "low"),
    113: ("close", "volume"),
    115: ("high", "low", "close", "volume"),
    136: ("open", "close", "volume"),
    142: ("close", "volume"),
    148: ("open", "volume"),
    176: ("close", "high", "low", "volume"),
    184: ("open", "close"),
}
WARMUP = {
    1: 7,
    10: 25,
    32: 5,
    37: 16,
    42: 10,
    48: 20,
    62: 5,
    83: 5,
    91: 44,
    99: 5,
    104: 20,
    105: 10,
    107: 2,
    113: 25,
    115: 39,
    136: 10,
    142: 24,
    148: 73,
    176: 17,
    184: 201,
}


def custom(n, size=3):
    return {k: size + 2 if k == "long" else size for k in DEFAULTS[n]}


def warmup(n, p):
    if n == 1:
        return p["lag"] + p["corr"]
    if n == 10:
        return p["volatility"] + p["peak"]
    if n == 32:
        return p["corr"] + p["sum"] - 1
    if n == 37:
        return p["sum"] + p["lag"] + 1
    if n == 42:
        return max(p["volatility"], p["corr"])
    if n == 48:
        return max(p["direction"] + 1, p["long"])
    if n in (62, 105):
        return p["corr"]
    if n in (83, 99):
        return p["covariance"]
    if n == 91:
        return max(p["peak"], p["volume_mean"] + p["corr"] - 1)
    if n == 104:
        return max(p["corr"] + p["lag"], p["volatility"])
    if n == 107:
        return p["lag"] + 1
    if n == 113:
        return max(p["lag"] + p["mean"], p["long"] + p["corr"] - 1)
    if n == 115:
        return max(
            p["corr"] + p["volume_mean"] - 1,
            p["price_rank"] + p["rank_corr"] - 1,
            p["volume_rank"] + p["rank_corr"] - 1,
        )
    if n == 136:
        return max(p["lag"] + 2, p["corr"])
    if n == 142:
        return max(p["price_rank"], 2 * p["lag"] + 1, p["volume_mean"] + p["volume_rank"] - 1)
    if n == 148:
        return max(p["volume_mean"] + p["sum"] + p["corr"] - 2, p["trough"])
    if n == 176:
        return p["range"] + p["corr"] - 1
    if n == 184:
        return p["lag"] + p["corr"]
    raise AssertionError(n)


def pool(size=240):
    data = {}
    t = np.arange(size)
    for s in range(5):
        rng = np.random.default_rng(101 + s)
        close = 30 + 3 * np.sin(t / (5 + s) + s) + np.cumsum(rng.normal(0, 0.2, size))
        op = close + rng.uniform(-1, 1, size)
        data[f"S{s}"] = pd.DataFrame(
            dict(
                datetime=pd.date_range("2024-01-01", periods=size),
                open=op,
                close=close,
                high=np.maximum(op, close) + rng.uniform(0.1, 1, size),
                low=np.minimum(op, close) - rng.uniform(0.1, 1, size),
                volume=1000 + 200 * np.sin(t / (2 + s)) + rng.uniform(0, 100, size),
            )
        )
    return data


def lag(x, w=1):
    out = np.full_like(x, np.nan)
    if w < len(x):
        out[w:] = x[:-w]
    return out


def roll(x, w, fn):
    out = np.full_like(x, np.nan)
    for j in range(x.shape[1]):
        for i in range(w - 1, len(x)):
            a = x[i - w + 1 : i + 1, j].tolist()
            if all(map(math.isfinite, a)):
                out[i, j] = fn(a)
    return out


def xs(x):
    out = np.full_like(x, np.nan)
    for i, row in enumerate(x):
        vals = [v for v in row if math.isfinite(v)]
        if len(vals) < 2:
            continue
        for j, v in enumerate(row):
            if math.isfinite(v):
                out[i, j] = (sum(a < v for a in vals) + (sum(a == v for a in vals) + 1) / 2) / len(
                    vals
                )
    return out


def pairs(x, y, w, cov=False, rank_bounds=None):
    out = np.full_like(x, np.nan)
    for j in range(x.shape[1]):
        for i in range(w - 1, len(x)):
            a, b = x[i - w + 1 : i + 1, j].tolist(), y[i - w + 1 : i + 1, j].tolist()
            if not all(map(math.isfinite, a + b)):
                continue
            if rank_bounds or not cov:
                # An independent exact centered-moment oracle. Raw binary
                # inputs are retained exactly; only known rank fractions are
                # reconstructed. statistics.correlation can turn an affine
                # translation into a false last-bit cross-sectional ordering.
                a = [
                    Fraction(v).limit_denominator(rank_bounds[0]) if rank_bounds else Fraction(v)
                    for v in a
                ]
                b = [
                    Fraction(v).limit_denominator(rank_bounds[1]) if rank_bounds else Fraction(v)
                    for v in b
                ]
                aa = [v - sum(a) / w for v in a]
                bb = [v - sum(b) / w for v in b]
                cross = sum(u * v for u, v in zip(aa, bb))
                squares = sum(u * u for u in aa) * sum(v * v for v in bb)
                if cov:
                    out[i, j] = float(cross / (w - 1))
                elif squares:
                    out[i, j] = (1 if cross > 0 else -1 if cross < 0 else 0) * math.sqrt(
                        float(cross**2 / squares)
                    )
            elif cov:
                out[i, j] = statistics.covariance(a, b)
    return out


def independent(data, n, p):
    dates = sorted({d for f in data.values() for d in f.datetime})
    shape = len(dates), len(data)
    fields = {k: np.full(shape, np.nan) for k in INPUTS[n]}
    for j, frame in enumerate(data.values()):
        for row in frame.to_dict("records"):
            i = dates.index(row["datetime"])
            for key in fields:
                fields[key][i, j] = row[key]
    valid = np.ones(shape, dtype=bool)
    for k, x in fields.items():
        valid &= np.isfinite(x) & (x >= 0 if k == "volume" else x > 0)
    for a, b in [
        ("high", "low"),
        ("high", "open"),
        ("high", "close"),
        ("open", "low"),
        ("close", "low"),
    ]:
        if a in fields and b in fields:
            valid &= fields[a] >= fields[b]
    fields = {k: np.where(valid, x, np.nan) for k, x in fields.items()}
    c, o, h, lo, v = (
        fields.get(k, np.full(shape, np.nan)) for k in ["close", "open", "high", "low", "volume"]
    )

    def mask(x, w):
        return np.where(roll(valid.astype(float), w, sum) == w, x, np.nan)

    def avg(x, w):
        return roll(x, w, statistics.mean)

    def total(x, w):
        return roll(x, w, math.fsum)

    def tr(x, w):
        return roll(
            x, w, lambda a: (sum(v < a[-1] for v in a) + (sum(v == a[-1] for v in a) + 1) / 2) / w
        )

    def rank_pairs(x, y, w, cov=False, bounds=None):
        return pairs(x, y, w, cov, rank_bounds=bounds or (2 * shape[1], 2 * shape[1]))

    with np.errstate(all="ignore"):
        ret = c / lag(c) - 1
        if n == 1:
            lv = np.log(np.where(v > 0, v, np.nan))
            dv = lv - lag(lv, p["lag"])
            dv = np.where(
                roll((v > 0).astype(float), p["lag"] + 1, sum) == p["lag"] + 1, dv, np.nan
            )
            out = -rank_pairs(xs(dv), xs((c - o) / o), p["corr"])
        elif n == 10:
            sd = roll(ret, p["volatility"], statistics.stdev)
            value = np.where(np.isfinite(sd), np.where(ret < 0, sd, c), np.nan)
            out = xs(roll(value**2, p["peak"], max))
        elif n == 32:
            out = -total(xs(rank_pairs(xs(h), xs(v), p["corr"])), p["sum"])
        elif n == 37:
            a = total(o, p["sum"]) * total(ret, p["sum"])
            out = -xs(mask(a - lag(a, p["lag"]), warmup(n, p)))
        elif n == 42:
            out = -xs(roll(h, p["volatility"], statistics.stdev)) * pairs(h, v, p["corr"])
        elif n == 48:
            out = (
                -xs(total(np.sign(c - lag(c)), p["direction"]))
                * total(v, p["short"])
                / total(v, p["long"])
            )
        elif n == 62:
            out = -pairs(h, xs(v), p["corr"])
        elif n in (83, 99):
            out = -xs(rank_pairs(xs(h if n == 83 else c), xs(v), p["covariance"], True))
        elif n == 91:
            out = -xs(c - roll(c, p["peak"], max)) * xs(
                pairs(avg(v, p["volume_mean"]), lo, p["corr"])
            )
        elif n == 104:
            a = pairs(h, v, p["corr"])
            out = -(a - lag(a, p["lag"])) * xs(roll(c, p["volatility"], statistics.stdev))
        elif n == 105:
            out = -rank_pairs(xs(o), xs(v), p["corr"])
        elif n == 107:
            out = (
                -xs(mask(o - lag(h, p["lag"]), warmup(n, p)))
                * xs(mask(o - lag(c, p["lag"]), warmup(n, p)))
                * xs(mask(o - lag(lo, p["lag"]), warmup(n, p)))
            )
        elif n == 113:
            out = (
                -xs(mask(avg(lag(c, p["lag"]), p["mean"]), p["lag"] + p["mean"]))
                * pairs(c, v, p["corr"])
                * xs(pairs(total(c, p["short"]), total(c, p["long"]), p["corr"]))
            )
        elif n == 115:
            out = xs(pairs(0.9 * h + 0.1 * c, avg(v, p["volume_mean"]), p["corr"])) ** xs(
                rank_pairs(
                    tr((h + lo) / 2, p["price_rank"]),
                    tr(v, p["volume_rank"]),
                    p["rank_corr"],
                    bounds=(2 * p["price_rank"], 2 * p["volume_rank"]),
                )
            )
        elif n == 136:
            out = -xs(mask(ret - lag(ret, p["lag"]), p["lag"] + 2)) * pairs(o, v, p["corr"])
        elif n == 142:
            d = c - lag(c, p["lag"])
            out = (
                -xs(tr(c, p["price_rank"]))
                * xs(mask(d - lag(d, p["lag"]), 2 * p["lag"] + 1))
                * xs(tr(v / avg(v, p["volume_mean"]), p["volume_rank"]))
            )
        elif n == 148:
            a = xs(pairs(o, total(avg(v, p["volume_mean"]), p["sum"]), p["corr"]))
            b = xs(o - roll(o, p["trough"], min))
            out = np.where(np.isfinite(a) & np.isfinite(b), -(a < b).astype(float), np.nan)
        elif n == 176:
            bot, top = roll(lo, p["range"], min), roll(h, p["range"], max)
            out = rank_pairs(xs((c - bot) / (top - bot)), xs(v), p["corr"])
        elif n == 184:
            out = xs(mask(pairs(lag(o - c, p["lag"]), c, p["corr"]), warmup(n, p))) + xs(o - c)
        else:
            raise AssertionError(n)
    return np.where(np.isfinite(out), mask(out, warmup(n, p)), np.nan)


def calculate(data, n, p=None):
    return FactorEngine().compute_matrix(data, configure_factor(f"gtja191_{n:03d}", p or {}))


@pytest.mark.parametrize("n", sorted(DEFAULTS))
@pytest.mark.parametrize("size", [None, 3, 7])
def test_panel_independent_defaults_custom_future_and_permutation(n, size):
    p = DEFAULTS[n] if size is None else custom(n, size)
    data = pool()
    out = calculate(data, n, p)
    np.testing.assert_allclose(out, independent(data, n, p), atol=2e-10, rtol=2e-8, equal_nan=True)
    assert out.iloc[: warmup(n, p) - 1].isna().all().all()
    assert out.notna().any().any()
    assert configure_factor(f"gtja191_{n:03d}", p).spec.warmup == warmup(n, p)
    prefix = {s: f.iloc[:215].copy() for s, f in data.items()}
    pd.testing.assert_frame_equal(out.iloc[:215], calculate(prefix, n, p))
    reverse = dict(reversed(list(data.items())))
    pd.testing.assert_frame_equal(out, calculate(reverse, n, p)[out.columns])


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_panel_all_inputs_invalid_missing_date_constant_and_zero(n):
    p = custom(n)
    data = pool(60)
    for key in INPUTS[n]:
        changed = copy.deepcopy(data)
        changed["S0"].loc[18, key] = np.nan
        changed["S1"].loc[22, key] = np.inf
        changed["S2"].loc[26, key] = -1
        changed["S3"] = changed["S3"].drop(index=30)
        out = calculate(changed, n, p)
        np.testing.assert_allclose(
            out, independent(changed, n, p), atol=2e-10, rtol=2e-8, equal_nan=True
        )
        assert out["S0"].iloc[18 : 18 + warmup(n, p)].isna().all()
        assert pd.isna(out.iloc[30, 3])
    for f in data.values():
        f[["open", "high", "low", "close"]] = 10.0
        f["volume"] = 0.0
    np.testing.assert_allclose(
        calculate(data, n, p), independent(data, n, p), atol=2e-10, equal_nan=True
    )
    with pytest.raises(ValueError, match="至少需要 2"):
        calculate({"S0": data["S0"]}, n, p)
    assert calculate({s: f.iloc[:1] for s, f in data.items()}, n, p).isna().all().all()


@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_panel_frozen_three_stock_all_adjustments(n, adjust):
    data = {
        code: qualify_factor_fields(
            frozen(f"{market}-{code}-DAILY-{adjust}.json"),
            frozen(f"{market}-{code}-DAILY-NONE.json"),
        )
        for market, code in [(0, "000001"), (0, "300750"), (1, "600036")]
    }
    for p in (DEFAULTS[n], custom(n)):
        np.testing.assert_allclose(
            calculate(data, n, p), independent(data, n, p), atol=2e-10, rtol=2e-8, equal_nan=True
        )


def test_panel_named_parameters_catalog_and_no_single_stock_substitute():
    from tests.unit.test_gtja191_linear_decay import DEFAULTS as DECAY_DEFAULTS
    from tests.unit.test_gtja191_vwap import DEFAULTS as VWAP_DEFAULTS
    from tests.unit.test_gtja191_vwap import SERIES

    assert {n for n, s in SPECS.items() if s.panel and s.windows} == set(DEFAULTS) | set(
        DECAY_DEFAULTS
    ) | (set(VWAP_DEFAULTS) - SERIES - {120})
    for n, p in DEFAULTS.items():
        factor = configure_factor(f"gtja191_{n:03d}")
        assert factor.spec.resolved_parameters == p and factor.spec.warmup == WARMUP[n]
        assert factor.spec.inputs == INPUTS[n]
        with pytest.raises(ValueError, match="股票池"):
            factor.compute(pool(5)["S0"])
        before = describe_factor(type(factor))
        for k, w in p.items():
            changed = configure_factor(factor.name, {k: w + 1 if k != "short" else w - 1})
            assert (
                describe_factor(type(changed), changed.spec.resolved_parameters)["formula_sha256"]
                != before["formula_sha256"]
            )
        for bad in (True, 0, 601, 1.5):
            with pytest.raises(ValueError):
                configure_factor(factor.name, {next(iter(p)): bad})
        assert configure_factor(factor.name).spec.resolved_parameters == p


def test_panel_rank_moments_preserve_exact_permutation_ties_without_epsilon():
    from easy_tdx.factor.builtin.gtja191 import _panel_correlation, _panel_rank_moment
    from easy_tdx.factor.panel import cross_section_rank

    # Each column is a permutation of 1/3,2/3,1. Paired cyclic permutation
    # has covariance -1/18, variance 1/9 on both sides, correlation exactly -1/2.
    a = pd.DataFrame([[1 / 3, 2 / 3, 1], [2 / 3, 1, 1 / 3], [1, 1 / 3, 2 / 3]])
    b = a.iloc[[1, 2, 0]].reset_index(drop=True)
    actual = _panel_rank_moment(a, b, 3)
    np.testing.assert_array_equal(actual.iloc[-1], [-0.5] * 3)
    np.testing.assert_array_equal(cross_section_rank(actual).iloc[-1], [2 / 3] * 3)
    np.testing.assert_array_equal(
        _panel_rank_moment(a, b, 3, covariance=True).iloc[-1], [-1 / 18] * 3
    )
    # Raw two-point correlations are also exactly +/-1, including large offsets.
    raw = pd.DataFrame([[1e12, 1e12], [1e12 + 1, 1e12 + 3]])
    np.testing.assert_array_equal(_panel_correlation(raw, raw, 2).iloc[-1], [1, 1])


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_panel_subset_membership_is_explicit_and_all_ranks_recomputed(n):
    data = pool(85)
    subset = {s: data[s] for s in ["S0", "S2", "S4"]}
    np.testing.assert_allclose(
        calculate(subset, n, custom(n)),
        independent(subset, n, custom(n)),
        atol=2e-10,
        rtol=2e-8,
        equal_nan=True,
    )


def test_panel_148_affine_translation_is_an_exact_rank_tie():
    t = np.arange(120)
    # Binary-exact input prices differing only by a constant; correlations and
    # O - TSMIN(O) must tie, so rank(corr) < rank(distance) is always false.
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=120),
            "open": 20 + (t % 17) / 8,
            "volume": 1000 + t * t,
        }
    )
    other = frame.copy()
    other["open"] += 16
    data = {"A": frame, "B": other}
    actual = calculate(data, 148, DEFAULTS[148])
    expected = independent(data, 148, DEFAULTS[148])
    np.testing.assert_array_equal(actual, expected)
    assert actual.iloc[72:].notna().all().all()
    assert actual.iloc[72:].eq(0).all().all()


def test_panel_boolean_missing_is_not_false_and_skipped_gap_not_ranked():
    data = pool(95)
    for s in ["S1", "S2", "S3", "S4"]:
        data[s].loc[30:40, "volume"] = np.nan
    out = calculate(data, 148, custom(148))
    assert out.iloc[:30].notna().any().any()
    assert out.iloc[35:41].isna().all().all()
    # 037 compares separated windows. Missing middle must not sneak through
    # simply because both endpoints happen to have complete sums.
    data = pool(55)
    data["S0"].loc[12, "open"] = np.nan
    out = calculate(data, 37, dict(sum=3, lag=15))
    assert pd.isna(out["S0"].iloc[22])
    np.testing.assert_allclose(
        out, independent(data, 37, dict(sum=3, lag=15)), atol=2e-10, rtol=2e-8, equal_nan=True
    )


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_panel_cancellation_is_not_partial_success(monkeypatch, n):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import gtja191

    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise ComputationStopped("cancelled")

    monkeypatch.setattr(gtja191, "computation_checkpoint", checkpoint)
    with pytest.raises(ComputationStopped):
        calculate(pool(80), n, custom(n))


@pytest.mark.asyncio
@pytest.mark.parametrize("n", sorted(DEFAULTS))
async def test_panel_research_archive_readonly_recompute_all(n, monkeypatch):
    async def fetch(*args):
        data = pool(120)[f"S{int(args[3][-1]) - 1}"].copy()
        data["vol"] = data.pop("volume")
        data["amount"] = data["vol"] * data["close"]
        data.attrs["snapshot_metadata"] = dict(source="MAC", actual_adjust="NONE", category="DAY")
        return data

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)
    name = f"gtja191_{n:03d}"
    request = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 6)],
        factors=[name, "gtja191_014"],
        factor_parameters={name: custom(n)},
        count=120,
        adjust="NONE",
    )
    result = (await research.factor_evaluate(request, None, None)).data
    assert not result["errors"]
    original = envelope(result, "evaluation")
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(
            GTJAPanelFactor, "compute_panel", lambda *a: pytest.fail("read must not compute")
        )
        guard.setattr(GTJAFactor, "compute", lambda *a: pytest.fail("read must not compute"))
        validate_factor_archive(original)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("no live fetch"))
    newer = research.recompute_factor_payload(record(original))
    validate_factor_archive(newer)
    assert newer["result"]["latest"] == result["latest"]
    assert newer["result"]["reports"] == result["reports"]
    assert original == before
