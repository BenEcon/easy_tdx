"""Independent list-window oracle for GTJA's nested correlations and ranks.

No production kernel or declared warmup is used to generate expected values.
"""

import copy
import math
import statistics

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine
from easy_tdx.factor.configuration import configure_factor
from tests.unit.test_gtja191_panel_compound import lag, pairs, roll, xs
from tests.unit.test_gtja191_vwap import long_frozen, sample

DEFAULTS = {
    25: dict(lag=7, volume_mean=20, volume_decay=9, return_sum=250),
    33: dict(trough=5, lag=5, long=240, short=20, volume_rank=5),
    39: dict(lag=2, price_decay=8, volume_mean=180, volume_sum=37, corr=14, corr_decay=12),
    44: dict(
        volume_mean=10, corr=7, corr_decay=6, corr_rank=4, lag=3, price_decay=10, price_rank=15
    ),
    56: dict(trough_open=12, price_sum=19, volume_mean=40, volume_sum=19, corr=13),
    73: dict(
        corr=10,
        inner_decay=16,
        outer_decay=4,
        corr_rank=5,
        volume_mean=30,
        second_corr=4,
        corr_decay=3,
    ),
    74: dict(price_sum=20, volume_mean=40, volume_sum=20, corr=7, rank_corr=6),
    77: dict(price_decay=20, volume_mean=40, corr=3, corr_decay=6),
    101: dict(volume_mean=30, volume_sum=37, corr=15, rank_corr=11),
    123: dict(price_sum=20, volume_mean=60, volume_sum=20, corr=9, second_corr=6),
    125: dict(volume_mean=80, corr=17, corr_decay=20, lag=3, price_decay=16),
    130: dict(volume_mean=40, corr=9, corr_decay=10, rank_corr=7, rank_decay=3),
    141: dict(volume_mean=15, rank_corr=9),
}
INPUTS = {
    25: ("close", "volume"),
    33: ("close", "low", "volume"),
    39: ("open", "close", "volume", "vwap"),
    44: ("low", "volume", "vwap"),
    56: ("open", "high", "low", "volume"),
    73: ("close", "volume", "vwap"),
    74: ("low", "volume", "vwap"),
    77: ("high", "low", "volume", "vwap"),
    101: ("close", "high", "volume", "vwap"),
    123: ("high", "low", "volume"),
    125: ("close", "volume", "vwap"),
    130: ("high", "low", "volume", "vwap"),
    141: ("high", "volume"),
}
WARMUP = {
    25: 251,
    33: 241,
    39: 240,
    44: 27,
    56: 70,
    73: 35,
    74: 65,
    77: 47,
    101: 80,
    123: 87,
    125: 115,
    130: 57,
    141: 23,
}


def custom(n, size=3):
    return {k: size + 2 if k == "long" else size for k in DEFAULTS[n]}


def warmup(n, p):
    if n == 25:
        return max(p["lag"] + 1, p["volume_mean"] + p["volume_decay"] - 1, p["return_sum"] + 1)
    if n == 33:
        return max(p["trough"] + p["lag"], p["long"] + 1, p["volume_rank"])
    if n == 39:
        return max(
            p["lag"] + p["price_decay"],
            p["volume_mean"] + p["volume_sum"] + p["corr"] + p["corr_decay"] - 3,
        )
    if n == 44:
        return max(
            p["volume_mean"] + p["corr"] + p["corr_decay"] + p["corr_rank"] - 3,
            p["lag"] + p["price_decay"] + p["price_rank"] - 1,
        )
    if n in {56, 74, 123}:
        a = max(p["price_sum"] + p["corr"] - 1, p["volume_mean"] + p["volume_sum"] + p["corr"] - 2)
        return max(a, p[{56: "trough_open", 74: "rank_corr", 123: "second_corr"}[n]])
    if n == 73:
        return max(
            p["corr"] + p["inner_decay"] + p["outer_decay"] + p["corr_rank"] - 3,
            p["volume_mean"] + p["second_corr"] + p["corr_decay"] - 2,
        )
    if n == 77:
        return max(p["price_decay"], p["volume_mean"] + p["corr"] + p["corr_decay"] - 2)
    if n == 101:
        return max(p["volume_mean"] + p["volume_sum"] + p["corr"] - 2, p["rank_corr"])
    if n == 125:
        return max(p["volume_mean"] + p["corr"] + p["corr_decay"] - 2, p["lag"] + p["price_decay"])
    if n == 130:
        return max(
            p["volume_mean"] + p["corr"] + p["corr_decay"] - 2, p["rank_corr"] + p["rank_decay"] - 1
        )
    if n == 141:
        return p["volume_mean"] + p["rank_corr"] - 1
    raise AssertionError(n)


def independent(data, n, p):
    dates = sorted({d for f in data.values() for d in f.datetime})
    # Pure time-series windows count this stock's observations, not other stocks' dates.
    if n == 44 and len(data) > 1:
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

    def delta(a):
        return mask(a - lag(a, p["lag"]), p["lag"] + 1)

    def decay(a, length):
        return roll(
            a,
            length,
            lambda x: math.fsum((i + 1) * y for i, y in enumerate(x)) / (length * (length + 1) / 2),
        )

    def tr(a, length):
        return roll(
            a,
            length,
            lambda x: (sum(y < x[-1] for y in x) + (sum(y == x[-1] for y in x) + 1) / 2) / length,
        )

    def avg(a, length):
        return roll(a, length, statistics.mean)

    def total(a, length):
        return roll(a, length, math.fsum)

    def rcorr(a, b):
        return pairs(xs(a), xs(b), p["rank_corr"], rank_bounds=(2 * len(data), 2 * len(data)))

    def compare(a, b, sign=1):
        return np.where(np.isfinite(a) & np.isfinite(b), sign * (a < b).astype(float), np.nan)

    with np.errstate(all="ignore"):
        ret = c / lag(c) - 1
        if n == 25:
            out = -xs(
                delta(c) * (1 - xs(decay(v / avg(v, p["volume_mean"]), p["volume_decay"])))
            ) * (1 + xs(total(ret, p["return_sum"])))
        elif n == 33:
            low = roll(lo, p["trough"], min)
            # Deliberately evaluate the report's original parenthesized difference.
            out = (
                (lag(low, p["lag"]) - low)
                * xs((total(ret, p["long"]) - total(ret, p["short"])) / (p["long"] - p["short"]))
                * tr(v, p["volume_rank"])
            )
        elif n == 39:
            out = xs(
                decay(
                    pairs(
                        0.3 * w + 0.7 * o,
                        total(avg(v, p["volume_mean"]), p["volume_sum"]),
                        p["corr"],
                    ),
                    p["corr_decay"],
                )
            ) - xs(decay(delta(c), p["price_decay"]))
        elif n == 44:
            out = tr(
                decay(pairs(lo, avg(v, p["volume_mean"]), p["corr"]), p["corr_decay"]),
                p["corr_rank"],
            ) + tr(decay(delta(w), p["price_decay"]), p["price_rank"])
        elif n == 56:
            out = compare(
                xs(o - roll(o, p["trough_open"], min)),
                xs(
                    xs(
                        pairs(
                            total((h + lo) / 2, p["price_sum"]),
                            total(avg(v, p["volume_mean"]), p["volume_sum"]),
                            p["corr"],
                        )
                    )
                    ** 5
                ),
            )
        elif n == 73:
            out = xs(
                decay(pairs(w, avg(v, p["volume_mean"]), p["second_corr"]), p["corr_decay"])
            ) - tr(
                decay(decay(pairs(c, v, p["corr"]), p["inner_decay"]), p["outer_decay"]),
                p["corr_rank"],
            )
        elif n == 74:
            out = xs(
                pairs(
                    total(0.35 * lo + 0.65 * w, p["price_sum"]),
                    total(avg(v, p["volume_mean"]), p["volume_sum"]),
                    p["corr"],
                )
            ) + xs(rcorr(w, v))
        elif n == 77:
            out = np.minimum(
                xs(decay((h + lo) / 2 - w, p["price_decay"])),
                xs(
                    decay(pairs((h + lo) / 2, avg(v, p["volume_mean"]), p["corr"]), p["corr_decay"])
                ),
            )
        elif n == 101:
            out = compare(
                xs(pairs(c, total(avg(v, p["volume_mean"]), p["volume_sum"]), p["corr"])),
                xs(rcorr(0.1 * h + 0.9 * w, v)),
                -1,
            )
        elif n == 123:
            out = compare(
                xs(
                    pairs(
                        total((h + lo) / 2, p["price_sum"]),
                        total(avg(v, p["volume_mean"]), p["volume_sum"]),
                        p["corr"],
                    )
                ),
                xs(pairs(lo, v, p["second_corr"])),
                -1,
            )
        elif n == 125:
            out = xs(decay(pairs(w, avg(v, p["volume_mean"]), p["corr"]), p["corr_decay"])) / xs(
                decay(delta((c + w) / 2), p["price_decay"])
            )
        elif n == 130:
            out = xs(
                decay(pairs((h + lo) / 2, avg(v, p["volume_mean"]), p["corr"]), p["corr_decay"])
            ) / xs(decay(rcorr(w, v), p["rank_decay"]))
        elif n == 141:
            out = -xs(rcorr(h, avg(v, p["volume_mean"])))
        else:
            raise AssertionError(n)
    return np.where(np.isfinite(out), mask(out, warmup(n, p)), np.nan)


def calculate(data, n, p=None):
    return FactorEngine().compute_matrix(data, configure_factor(f"gtja191_{n:03d}", p or {}))


@pytest.mark.parametrize("n", sorted(DEFAULTS))
@pytest.mark.parametrize("size", [None, 3, 7])
def test_multistage_independent_defaults_custom_causal_order(n, size):
    p = DEFAULTS[n] if size is None else custom(n, size)
    data = sample(270)
    out = calculate(data, n, p)
    np.testing.assert_allclose(out, independent(data, n, p), equal_nan=True, atol=2e-10)
    assert out.notna().any().any()
    assert out.iloc[: warmup(n, p) - 1].isna().all().all()
    pd.testing.assert_frame_equal(
        out.iloc[:260], calculate({s: f.iloc[:260] for s, f in data.items()}, n, p)
    )
    pd.testing.assert_frame_equal(
        out, calculate(dict(reversed(list(data.items()))), n, p)[out.columns]
    )


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_multistage_invalid_missing_constant_zero_recovery(n):
    p, data = custom(n), sample(150)
    for k in INPUTS[n]:
        changed = copy.deepcopy(data)
        for s, pos, bad in [("S0", 20, np.nan), ("S1", 24, np.inf), ("S2", 28, -1.0)]:
            changed[s].loc[pos, k] = bad
        changed["S3"] = changed["S3"].drop(index=33)
        out = calculate(changed, n, p)
        np.testing.assert_allclose(out, independent(changed, n, p), equal_nan=True, atol=2e-10)
        assert out.iloc[100:].notna().any().any()
    for f in data.values():
        for k in ("open", "high", "low", "close", "vwap"):
            f[k] = 10.0
        f["volume"] = 0.0
    out = calculate(data, n, p)
    np.testing.assert_allclose(out, independent(data, n, p), equal_nan=True, atol=2e-10)
    if n != 33:
        assert out.isna().all().all()


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_multistage_real_ten_stock_default_values(n):
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
    assert out.notna().any().any()


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_multistage_metadata_inputs_adjustment_cancel(n, monkeypatch):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import gtja191
    from easy_tdx.factor.catalog import describe_factor

    factor = configure_factor(f"gtja191_{n:03d}")
    assert factor.spec.inputs == INPUTS[n]
    assert factor.spec.resolved_parameters == DEFAULTS[n]
    assert factor.spec.warmup == WARMUP[n] == warmup(n, DEFAULTS[n])
    assert factor.spec.panel == (n != 44)
    assert describe_factor(type(factor))["implementation_version"] == gtja191.VERSION
    data = sample(40)
    if n != 44:
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


def test_multistage_044_real_minute_is_single_series_not_pool_rank():
    f = long_frozen("0-300750-MIN_30-NONE.json")
    out = calculate({"300750": f}, 44)
    np.testing.assert_allclose(out, independent({"300750": f}, 44, DEFAULTS[44]), equal_nan=True)
    assert out.notna().any().any()


def test_multistage_033_long_short_constraint():
    for p in [{"short": 240}, {"short": 8, "long": 8}, {"short": 9, "long": 8}]:
        with pytest.raises(ValueError):
            configure_factor("gtja191_033", p)


def test_multistage_033_report_parentheses_change_rank():
    # Long=3, short=1: A's older returns are .2,.2; B's are .1,.1.
    # Recent returns -0.5 and +0.5 reverse rank if only the short sum is divided.
    data = {}
    for code, close in [("A", [100.0, 120.0, 144.0, 72.0]), ("B", [100.0, 110.0, 121.0, 181.5])]:
        data[code] = pd.DataFrame(
            dict(
                datetime=pd.date_range("2025-01-01", periods=4),
                close=close,
                low=[20.0, 19.0, 18.0, 17.0],
                volume=[1.0, 2.0, 3.0, 4.0],
            )
        )
    p = dict(trough=1, lag=1, long=3, short=1, volume_rank=1)
    out = calculate(data, 33, p)
    assert out.iloc[-1].tolist() == [1.0, 0.5]
    assert out.iloc[:3].isna().all().all()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "group", [(25, 33, 39, 44), (56, 73, 74, 77), (101, 123, 125, 130), (141,)]
)
async def test_multistage_research_archive_readonly_recompute(monkeypatch, group):
    from easy_tdx.factor.builtin.gtja191 import GTJAFactor, GTJAPanelFactor
    from easy_tdx.web.factor_archive import validate_factor_archive
    from easy_tdx.web.routers import research
    from tests.unit.test_factor_archive import record
    from tests.unit.test_factor_data import frozen
    from tests.unit.test_gtja191_archive import envelope

    async def fetch(*args):
        # Synthetic pool with stated frozen source; not six real stock tapes.
        f = frozen("0-000001-DAILY-NONE.json").copy()
        scale = np.exp(int(args[3][-1]) * 0.0005 * np.arange(len(f)))
        f[["open", "high", "low", "close"]] = f[["open", "high", "low", "close"]].mul(scale, axis=0)
        f["amount"] *= scale
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
