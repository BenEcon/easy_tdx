"""Independent literal-report definitions; do not silently replace ambiguous formulas."""

import copy
import math
import statistics
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor
from tests.unit.test_gtja191_panel_compound import pairs, xs
from tests.unit.test_gtja191_smoothing import rolling, weighted
from tests.unit.test_gtja191_vwap import long_frozen, sample

DEFAULTS = {
    28: dict(range=9, smooth=3),
    54: dict(body_std=10, corr=10),
    190: dict(lag=19, root=20, window=20),
}
INPUTS = {28: ("close", "high", "low"), 54: ("open", "close"), 190: ("close",)}


def custom(n, size=3):
    return {k: size for k in DEFAULTS[n]}


def warmup(n, p):
    return (
        p["range"] + 2 * p["smooth"] - 2
        if n == 28
        else max(p.values())
        if n == 54
        else p["lag"] + p["window"]
    )


def independent(data, n, p):
    index = sorted(set().union(*(set(f.datetime) for f in data.values())))
    output = {}
    for s, f in data.items():
        # Panel formula uses exact union dates; TS formula uses observed bars.
        if n == 54:
            f = f.set_index("datetime").reindex(index).rename_axis("datetime").reset_index()
        vals = {k: f[k].to_numpy(float).copy() for k in INPUTS[n]}
        valid = np.logical_and.reduce([np.isfinite(a) & (a > 0) for a in vals.values()])
        if n == 28:
            valid &= (vals["low"] <= vals["close"]) & (vals["close"] <= vals["high"])
        for a in vals.values():
            a[~valid] = np.nan
        c = vals["close"]
        result = np.full(len(f), np.nan)
        with np.errstate(all="ignore"):
            if n == 28:
                lows = np.array(rolling(vals["low"], p["range"], min))
                highs = np.array(rolling(vals["high"], p["range"], max))
                high_lows = np.array(rolling(vals["low"], p["range"], max))
                u = 100 * (c - lows) / (highs - lows)
                v = 100 * (c - lows) / (highs - high_lows)
                u[~np.isfinite(u)] = np.nan
                v[~np.isfinite(v)] = np.nan
                result = 3 * np.array(weighted(u, p["smooth"], 1)) - 2 * np.array(
                    weighted(weighted(v, p["smooth"], 1), p["smooth"], 1)
                )
            elif n == 54:
                o = vals["open"]
                corr = pairs(c[:, None], o[:, None], p["corr"])
                result = (
                    np.array(rolling(abs(c - o), p["body_std"], statistics.stdev))
                    + (c - o)
                    + corr[:, 0]
                )
            else:
                for t in range(warmup(n, p) - 1, len(f)):
                    if not valid[t - warmup(n, p) + 1 : t + 1].all():
                        continue
                    above, below = [], []
                    for j in range(t - p["window"] + 1, t + 1):
                        current, previous, old = (
                            Fraction(str(c[k])) for k in (j, j - 1, j - p["lag"])
                        )
                        ret = float(current / previous) - 1
                        threshold = math.expm1(math.log(float(current / old)) / p["root"])
                        comparison = (current / previous) ** p["root"] - current / old
                        if comparison > 0:
                            above.append((ret - threshold) ** 2)
                        elif comparison < 0:
                            below.append((ret - threshold - 2) ** 2)
                    if len(above) > 1 and below and math.fsum(above) > 0 and math.fsum(below) > 0:
                        result[t] = math.log(
                            (len(above) - 1) * math.fsum(below) / (len(below) * math.fsum(above))
                        )
        for t in range(len(result)):
            if t + 1 < warmup(n, p) or not valid[t - warmup(n, p) + 1 : t + 1].all():
                result[t] = np.nan
        result[~np.isfinite(result)] = np.nan
        output[s] = pd.Series(result, index=f.datetime).reindex(index)
    out = pd.DataFrame(output)
    if n == 54:
        out.iloc[:, :] = -xs(out.to_numpy())
    return out


def calculate(data, n, p=None):
    return FactorEngine().compute_matrix(data, configure_factor(f"gtja191_{n:03d}", p or {}))


@pytest.mark.parametrize("n", sorted(DEFAULTS))
@pytest.mark.parametrize("size", [None, 3, 7])
def test_literal_defaults_custom_prefix_permutation(n, size):
    p = DEFAULTS[n] if size is None else custom(n, size)
    data = sample(200)
    out = calculate(data, n, p)
    np.testing.assert_allclose(out, independent(data, n, p), equal_nan=True, atol=2e-9)
    assert out.notna().any().any()
    assert out.iloc[: warmup(n, p) - 1].isna().all().all()
    pd.testing.assert_frame_equal(
        out.iloc[:170], calculate({s: f.iloc[:170] for s, f in data.items()}, n, p)
    )
    pd.testing.assert_frame_equal(
        out, calculate(dict(reversed(list(data.items()))), n, p)[out.columns]
    )


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_literal_invalid_missing_constant_and_recovery(n):
    data, p = sample(150), custom(n)
    for field in INPUTS[n]:
        for bad in (np.nan, np.inf, -1.0, 0.0):
            changed = copy.deepcopy(data)
            changed["S0"].loc[35, field] = bad
            changed["S1"] = changed["S1"].drop(index=40)
            out = calculate(changed, n, p)
            np.testing.assert_allclose(out, independent(changed, n, p), equal_nan=True, atol=2e-9)
            assert out.iloc[80:].notna().any().any()
    for f in data.values():
        for k in INPUTS[n]:
            f[k] = 10.0
    assert calculate(data, n, p).isna().all().all()


@pytest.mark.parametrize("n", sorted(DEFAULTS))
@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_literal_real_stocks_periods_adjustments(n, adjust):
    from easy_tdx.factor.data import qualify_factor_fields
    from tests.unit.test_factor_data import FILES, frozen

    for period in ("DAILY", "MIN_30"):
        paths = [f for f in FILES if f.endswith(f"-{period}-{adjust}.json")]
        if not paths:
            continue
        data = {
            f: qualify_factor_fields(frozen(f), frozen(f.replace(adjust, "NONE"))) for f in paths
        }
        if n == 54 and len(data) < 2:
            # Only one real minute tape exists: assert rejection, never duplicate
            # the same security and call it a real multi-stock validation.
            with pytest.raises(ValueError, match="至少需要 2"):
                calculate(data, n)
            continue
        for p in (DEFAULTS[n], custom(n)):
            out = calculate(data, n, p)
            np.testing.assert_allclose(out, independent(data, n, p), equal_nan=True, atol=2e-9)
            assert out.notna().any().any()


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_literal_metadata_parameters_and_single_scope(n, monkeypatch):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import gtja191

    factor = configure_factor(f"gtja191_{n:03d}")
    meta = describe_factor(type(factor))
    assert factor.spec.inputs == INPUTS[n]
    assert meta["warmup_bars"] == warmup(n, DEFAULTS[n])
    assert meta["supported_adjustments"] == ["NONE", "QFQ", "HFQ"]
    assert meta["implementation_version"] == gtja191.VERSION
    assert meta["limitations"]
    if n == 190:
        assert meta["parameters"]["root"]["unit"] == "dimensionless"
        assert meta["parameters"]["lag"]["unit"] == "bars"
        changed = configure_factor(factor.name, {"root": 600})
        assert changed.spec.warmup == factor.spec.warmup
    for key in DEFAULTS[n]:
        for bad in (True, 0, -1, 1.2, "3", 601):
            with pytest.raises(ValueError):
                configure_factor(factor.name, {key: bad})
    if n == 54:
        with pytest.raises(ValueError, match="股票池"):
            factor.compute(sample(20)["S0"])
    with pytest.raises(ValueError, match="无行情"):
        calculate(sample(0), n)
    for size in (1, 3):
        assert calculate(sample(size), n).isna().all().all()
    for field in INPUTS[n]:
        with pytest.raises(ValueError):
            calculate({s: f.drop(columns=field) for s, f in sample(30).items()}, n)
    if n != 54:
        with pytest.raises(ValueError, match="600"):
            configure_factor(factor.name, {k: 600 for k in DEFAULTS[n]})

    def stop():
        raise ComputationStopped("cancelled")

    monkeypatch.setattr(gtja191, "computation_checkpoint", stop)
    with pytest.raises(ComputationStopped):
        calculate(sample(40), n, custom(n))


def test_literal_hand_distinct_denominators_and_correlation_ties():
    # Smooth=1 leaves 3U-2V; two lows differ, so this is not KDJ J.
    f = pd.DataFrame(
        dict(
            datetime=pd.date_range("2020-01-01", periods=2),
            close=[3.0, 5.0],
            low=[1.0, 4.0],
            high=[6.0, 7.0],
            open=[3.0, 5.0],
        )
    )
    value = calculate({"A": f}, 28, dict(range=2, smooth=1)).iloc[-1, 0]
    assert value == pytest.approx(3 * 100 * 4 / 6 - 2 * 100 * 4 / 3)
    pool = {
        str(i): pd.DataFrame(
            dict(
                datetime=pd.date_range("2020-01-01", periods=5),
                open=np.arange(1.0, 6.0) + i * 10,
                close=np.arange(1.0, 6.0) + i * 10 + 1,
            )
        )
        for i in range(3)
    }
    assert calculate(pool, 54, dict(body_std=3, corr=3)).iloc[-1].tolist() == [-2 / 3] * 3


def test_literal_190_asymmetric_hand_counts_and_exact_ties():
    c = [10.0, 11.0, 10.0, 12.0, 10.0, 13.0, 10.0, 14.0]
    f = pd.DataFrame(dict(datetime=pd.date_range("2020-01-01", periods=len(c)), close=c))
    p = dict(lag=1, root=2, window=4)
    actual = calculate({"A": f}, 190, p)
    np.testing.assert_allclose(actual, independent({"A": f}, 190, p), equal_nan=True)
    # root=lag=1 means every return equals the boundary exactly, including 0.1.
    assert calculate({"A": f}, 190, dict(lag=1, root=1, window=4)).isna().all().all()
    up = (1.3 - math.sqrt(1.3)) ** 2 + (1.4 - math.sqrt(1.4)) ** 2
    down = (5 / 6 - math.sqrt(5 / 6) - 2) ** 2 + (10 / 13 - math.sqrt(10 / 13) - 2) ** 2
    assert actual.iloc[-1, 0] == pytest.approx(math.log(down / (2 * up)))


@pytest.mark.asyncio
async def test_literal_research_archive_readonly_recompute(monkeypatch):
    from easy_tdx.factor.builtin.gtja191 import GTJAFactor, GTJAPanelFactor
    from easy_tdx.web.factor_archive import validate_factor_archive
    from easy_tdx.web.routers import research
    from tests.unit.test_factor_archive import record
    from tests.unit.test_gtja191_archive import envelope

    async def fetch(*args):
        f = long_frozen("0-000001-DAILY-NONE.json").copy()
        # Source uses canonical volume; original MAC volume retained in frozen file.
        return f

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda f: f)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 7)],
        factors=[f"gtja191_{n:03d}" for n in DEFAULTS],
        count=320,
        adjust="NONE",
    )
    result = (await research.factor_evaluate(req, None, None)).data
    assert not result["errors"]
    original = envelope(result, "evaluation")
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(GTJAFactor, "compute", lambda *a: pytest.fail("read computes"))
        guard.setattr(GTJAPanelFactor, "compute_panel", lambda *a: pytest.fail("read computes"))
        validate_factor_archive(original)
    with monkeypatch.context() as guard:
        guard.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("recompute fetches"))
        newer = research.recompute_factor_payload(record(original))
    assert newer["result"]["reports"] == result["reports"]
    assert newer["result"]["latest"] == result["latest"]
    assert original == before
