"""VWAP formulas: independent list/matrix arithmetic and real qualified fixtures.

Synthetic inputs are expressly unadjusted mathematical samples, not real quotes.
No production rolling/ranking/formula helper is used to produce expected values.
"""

import copy
import hashlib
import json
import math
import statistics
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine
from easy_tdx.factor.builtin.gtja191 import SPECS, GTJAFactor, GTJAPanelFactor
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor
from easy_tdx.factor.data import qualify_factor_fields
from tests.unit.test_factor_data import frozen
from tests.unit.test_gtja191_panel_compound import lag, pairs, pool, roll, xs

DEFAULTS = {
    7: dict(range=3, lag=3),
    8: dict(lag=4),
    12: dict(mean=10),
    13: {},
    16: dict(corr=5, peak=5),
    17: dict(peak=15, lag=5),
    26: dict(mean=7, lag=5, corr=230),
    36: dict(corr=6, sum=2),
    41: dict(lag=3, peak=5),
    45: dict(lag=1, volume_mean=150, corr=15),
    90: dict(corr=5),
    108: dict(trough=2, volume_mean=120, corr=6),
    114: dict(mean=5, lag=2),
    120: {},
    124: dict(peak=30, decay=2),
    131: dict(lag=1, volume_mean=50, corr=18, rank=18),
    154: dict(trough=16, volume_mean=180, corr=18),
    163: dict(volume_mean=20),
    170: dict(volume_mean=20, high_mean=5, lag=5),
    179: dict(corr=4, volume_mean=50, rank_corr=12),
}
SERIES = {13, 26, 154}
INPUTS = {
    7: ("vwap", "close", "volume"),
    8: ("high", "low", "vwap"),
    12: ("open", "close", "vwap"),
    13: ("high", "low", "vwap"),
    16: ("volume", "vwap"),
    17: ("vwap", "close"),
    26: ("close", "vwap"),
    36: ("volume", "vwap"),
    41: ("vwap",),
    45: ("close", "open", "vwap", "volume"),
    90: ("vwap", "volume"),
    108: ("high", "vwap", "volume"),
    114: ("high", "low", "close", "volume", "vwap"),
    120: ("vwap", "close"),
    124: ("close", "vwap"),
    131: ("vwap", "close", "volume"),
    154: ("vwap", "volume"),
    163: ("close", "high", "volume", "vwap"),
    170: ("close", "high", "volume", "vwap"),
    179: ("vwap", "volume", "low"),
}
WARMUP = {
    7: 4,
    8: 5,
    12: 10,
    13: 1,
    16: 9,
    17: 15,
    26: 235,
    36: 7,
    41: 8,
    45: 164,
    90: 5,
    108: 125,
    114: 7,
    120: 1,
    124: 31,
    131: 84,
    154: 197,
    163: 20,
    170: 20,
    179: 61,
}


def custom(n, size=3):
    return dict.fromkeys(DEFAULTS[n], size)


def warmup(n, p):
    if n in {13, 120}:
        return 1
    if n == 7:
        return max(p["range"], p["lag"] + 1)
    if n == 8:
        return p["lag"] + 1
    if n == 12:
        return p["mean"]
    if n in {16, 36}:
        return p["corr"] + p["peak" if n == 16 else "sum"] - 1
    if n == 17:
        return max(p["peak"], p["lag"] + 1)
    if n == 26:
        return max(p["mean"], p["lag"] + p["corr"])
    if n == 41:
        return p["lag"] + p["peak"]
    if n == 45:
        return max(p["lag"] + 1, p["volume_mean"] + p["corr"] - 1)
    if n == 90:
        return p["corr"]
    if n in {108, 154}:
        return max(p["trough"], p["volume_mean"] + p["corr"] - 1)
    if n == 114:
        return p["mean"] + p["lag"]
    if n == 124:
        return p["peak"] + p["decay"] - 1
    if n == 131:
        return max(p["lag"] + 1, p["volume_mean"] + p["corr"] + p["rank"] - 2)
    if n == 163:
        return max(2, p["volume_mean"])
    if n == 170:
        return max(p["volume_mean"], p["high_mean"], p["lag"] + 1)
    if n == 179:
        return max(p["corr"], p["volume_mean"] + p["rank_corr"] - 1)
    raise AssertionError(n)


def sample(size=260):
    data = pool(size)
    for i, f in enumerate(data.values()):
        f["vwap"] = f.low + (f.high - f.low) * (0.2 + 0.1 * i)
        f.attrs["snapshot_metadata"] = {"actual_adjust": "NONE"}
    return data


def calculate(data, n, p=None):
    return FactorEngine().compute_matrix(data, configure_factor(f"gtja191_{n:03d}", p or {}))


def independent(data, n, p):
    dates = sorted({d for f in data.values() for d in f.datetime})
    if n in SERIES and len(data) > 1:
        # Time-series bars count actual observations of each stock, as before.
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
    blank = np.full(shape, np.nan)
    c, o, h, lo, v, w = [
        fields.get(k, blank) for k in ("close", "open", "high", "low", "volume", "vwap")
    ]

    def avg(a, length):
        return roll(a, length, statistics.mean)

    def mask(a, length):
        good = roll(valid.astype(float), length, sum) == length
        return np.where(good, a, np.nan)

    def rp(a, b, length):
        return pairs(a, b, length, rank_bounds=(2 * len(data), 2 * len(data)))

    def tr(a, length):
        return roll(
            a,
            length,
            lambda x: (sum(y < x[-1] for y in x) + (sum(y == x[-1] for y in x) + 1) / 2) / length,
        )

    with np.errstate(all="ignore"):
        if n == 7:
            out = (xs(roll(w - c, p["range"], max)) + xs(roll(w - c, p["range"], min))) * xs(
                mask(v - lag(v, p["lag"]), p["lag"] + 1)
            )
        elif n == 8:
            x = 0.2 * (h + lo) / 2 + 0.8 * w
            out = xs(mask(lag(x, p["lag"]) - x, p["lag"] + 1))
        elif n == 12:
            out = -xs(o - avg(w, p["mean"])) * xs(abs(c - w))
        elif n == 13:
            out = np.array(
                [
                    [math.sqrt(a) * math.sqrt(b) - d for a, b, d in zip(hh, ll, ww)]
                    for hh, ll, ww in zip(h, lo, w)
                ]
            )
        elif n == 16:
            out = -roll(xs(rp(xs(v), xs(w), p["corr"])), p["peak"], max)
        elif n == 17:
            base, exponent = xs(w - roll(w, p["peak"], max)), c - lag(c, p["lag"])
            out = np.where(np.isfinite(base) & np.isfinite(exponent), base**exponent, np.nan)
        elif n == 26:
            out = avg(c, p["mean"]) - c + pairs(w, lag(c, p["lag"]), p["corr"])
        elif n == 36:
            out = xs(roll(rp(xs(v), xs(w), p["corr"]), p["sum"], sum))
        elif n == 41:
            out = -xs(mask(roll(w - lag(w, p["lag"]), p["peak"], max), warmup(n, p)))
        elif n == 45:
            x = 0.6 * c + 0.4 * o
            out = xs(mask(x - lag(x, p["lag"]), p["lag"] + 1)) * xs(
                pairs(w, avg(v, p["volume_mean"]), p["corr"])
            )
        elif n == 90:
            out = -xs(rp(xs(w), xs(v), p["corr"]))
        elif n == 108:
            base, exponent = (
                xs(h - roll(h, p["trough"], min)),
                xs(pairs(w, avg(v, p["volume_mean"]), p["corr"])),
            )
            out = np.where(np.isfinite(base) & np.isfinite(exponent), -(base**exponent), np.nan)
        elif n == 114:
            x = (h - lo) / avg(c, p["mean"])
            divisor = x / (w - c)
            out = (
                xs(mask(lag(x, p["lag"]), warmup(n, p)))
                * xs(xs(v))
                / np.where(np.isfinite(divisor), divisor, np.nan)
            )
        elif n == 120:
            out = xs(w - c) / xs(w + c)
        elif n == 124:
            decay = p["decay"]
            out = (c - w) / roll(
                xs(roll(c, p["peak"], max)),
                decay,
                lambda x: sum((i + 1) * a for i, a in enumerate(x)) / (decay * (decay + 1) / 2),
            )
        elif n == 131:
            base = xs(mask(w - lag(w, p["lag"]), p["lag"] + 1))
            exponent = tr(pairs(c, avg(v, p["volume_mean"]), p["corr"]), p["rank"])
            out = np.where(np.isfinite(base) & np.isfinite(exponent), base**exponent, np.nan)
        elif n == 154:
            left, right = (
                w - roll(w, p["trough"], min),
                pairs(w, avg(v, p["volume_mean"]), p["corr"]),
            )
            out = np.where(
                np.isfinite(left) & np.isfinite(right), (left < right).astype(float), np.nan
            )
        elif n == 163:
            out = xs(mask(-(c / lag(c) - 1) * avg(v, p["volume_mean"]) * w * (h - c), warmup(n, p)))
        elif n == 170:
            out = xs(1 / c) * v / avg(v, p["volume_mean"]) * h * xs(h - c) / avg(
                h, p["high_mean"]
            ) - xs(mask(w - lag(w, p["lag"]), p["lag"] + 1))
        elif n == 179:
            out = xs(pairs(w, v, p["corr"])) * xs(
                rp(xs(lo), xs(avg(v, p["volume_mean"])), p["rank_corr"])
            )
        else:
            raise AssertionError(n)
    return np.where(np.isfinite(out), mask(out, warmup(n, p)), np.nan)


@pytest.mark.parametrize("n", sorted(DEFAULTS))
@pytest.mark.parametrize("size", [None, 3, 7])
def test_vwap_independent_defaults_custom_future_and_permutation(n, size):
    p = DEFAULTS[n] if size is None else custom(n, size)
    data = sample()
    out = calculate(data, n, p)
    np.testing.assert_allclose(out, independent(data, n, p), atol=2e-10, rtol=2e-8, equal_nan=True)
    assert out.iloc[: warmup(n, p) - 1].isna().all().all()
    assert out.notna().any().any()
    assert configure_factor(f"gtja191_{n:03d}", p).spec.warmup == warmup(n, p)
    pd.testing.assert_frame_equal(
        out.iloc[:245], calculate({s: f.iloc[:245] for s, f in data.items()}, n, p)
    )
    pd.testing.assert_frame_equal(
        out, calculate(dict(reversed(list(data.items()))), n, p)[out.columns]
    )


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_vwap_invalid_inputs_missing_date_constant_zero_and_recovery(n):
    data, p = sample(60), custom(n)
    for key in INPUTS[n]:
        changed = copy.deepcopy(data)
        for stock, pos, bad in [("S0", 18, np.nan), ("S1", 22, np.inf), ("S2", 26, -1.0)]:
            changed[stock].loc[pos, key] = bad
        changed["S3"] = changed["S3"].drop(index=30)
        out = calculate(changed, n, p)
        np.testing.assert_allclose(
            out, independent(changed, n, p), atol=2e-10, rtol=2e-8, equal_nan=True
        )
        assert out.S0.iloc[18 : 18 + warmup(n, p)].isna().all()
        assert out.S0.iloc[18 + warmup(n, p) :].notna().any()
    for f in data.values():
        f[["open", "high", "low", "close", "vwap"]] = 10.0
        f["volume"] = 0.0
    np.testing.assert_allclose(
        calculate(data, n, p), independent(data, n, p), atol=2e-10, equal_nan=True
    )


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_vwap_real_qualified_none_daily_minute_and_zero_transactions(n):
    data = {
        code: qualify_factor_fields(
            frozen(f"{m}-{code}-DAILY-NONE.json"),
            frozen(f"{m}-{code}-DAILY-NONE.json"),
            need_vwap=True,
        )
        for m, code in [(0, "000001"), (0, "300750"), (1, "600036")]
    }
    for p in (DEFAULTS[n], custom(n)):
        np.testing.assert_allclose(
            calculate(data, n, p), independent(data, n, p), atol=2e-10, rtol=2e-8, equal_nan=True
        )
    if n in SERIES:
        raw = frozen("0-300750-MIN_30-NONE.json")
        f = qualify_factor_fields(raw, raw, need_vwap=True)
        np.testing.assert_allclose(
            calculate({"300750": f}, n, custom(n)),
            independent({"300750": f}, n, custom(n)),
            atol=2e-10,
            rtol=2e-8,
            equal_nan=True,
        )
    raw = frozen("0-000001-DAILY-NONE.json")
    raw.loc[70, ["vol", "amount"]] = 0.0
    f = qualify_factor_fields(raw, raw, need_vwap=True)
    assert pd.isna(f.vwap.iloc[70])
    data["000001"] = f
    out = calculate(data, n, custom(n))
    assert out["000001"].iloc[70 : 70 + warmup(n, custom(n))].isna().all()


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_vwap_metadata_parameters_adjustment_rejection_and_missing(n):
    factor = configure_factor(f"gtja191_{n:03d}")
    meta = describe_factor(type(factor))
    assert meta["supported_adjustments"] == ["NONE"]
    assert factor.spec.inputs == INPUTS[n]
    assert factor.spec.warmup == WARMUP[n]
    assert factor.spec.resolved_parameters == DEFAULTS[n]
    for key, val in DEFAULTS[n].items():
        p = {key: val + 1}
        changed = configure_factor(factor.name, p)
        effective = DEFAULTS[n] | p
        assert changed.spec.warmup == warmup(n, effective)
        assert describe_factor(type(changed), p)["formula_sha256"] != meta["formula_sha256"]
        np.testing.assert_allclose(
            calculate(sample(70), n, p),
            independent(sample(70), n, effective),
            atol=2e-10,
            rtol=2e-8,
            equal_nan=True,
        )
        for bad in (True, 0, 601, 1.5):
            with pytest.raises(ValueError):
                configure_factor(factor.name, {key: bad})
    for adjust in ("QFQ", "HFQ"):
        data = sample(30)
        for f in data.values():
            f.attrs["snapshot_metadata"]["actual_adjust"] = adjust
        with pytest.raises(ValueError, match="不复权"):
            calculate(data, n)
        if n in SERIES:
            with pytest.raises(ValueError, match="不复权"):
                factor.compute(data["S0"])
    data = sample(30)
    data["S0"] = data["S0"].drop(columns="vwap")
    with pytest.raises(ValueError, match="缺少字段"):
        calculate(data, n)
    if n not in SERIES:
        with pytest.raises(ValueError, match="股票池"):
            factor.compute(sample(5)["S0"])


def test_vwap_hand_weights_power_missing_boolean_and_nested_division():
    from easy_tdx.factor.builtin.gtja191 import _linear_mean

    weighted = _linear_mean(pd.DataFrame({"x": [2.0, 4.0, 8.0]}), 3)
    assert weighted.x.iloc[-1] == pytest.approx(34 / 6)
    assert weighted.x.iloc[:2].isna().all()
    data = sample(35)
    # At this date only one stock has a valid base rank, its exponent is 0.
    for s, f in data.items():
        f["close"] = 10.0
        if s != "S0":
            f.loc[15, "vwap"] = np.nan
    assert pd.isna(calculate(data, 17, custom(17)).S0.iloc[15])
    for f in data.values():
        f["vwap"] = f.close
    assert calculate(data, 114, custom(114)).isna().all().all()
    assert calculate(data, 154, custom(154)).isna().all().all()
    factor = configure_factor("gtja191_013")
    frame = pd.DataFrame({"high": [9.0, 1e300], "low": [4.0, 1e300], "vwap": [5.0, 1e300]})
    assert factor.compute(frame).iloc[0] == 1.0
    assert np.isfinite(factor.compute(frame).iloc[1])


def test_vwap_036_window_sum_preserves_exact_zero_rank_tie():
    data = sample(60)
    for stock, pos, bad in [("S0", 18, np.nan), ("S1", 22, np.inf), ("S2", 26, -1.0)]:
        data[stock].loc[pos, "volume"] = bad
    data["S3"] = data["S3"].drop(index=30)
    # Last three ranked correlations are (-.5,.5,0) and (.5,0,-.5).
    # Both totals are exactly zero; stale rolling state must not split them.
    result = calculate(data, 36, dict(corr=3, sum=3))
    assert result.S2.iloc[54] == result.S4.iloc[54] == 0.5


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_vwap_cancellation_no_partial_success(monkeypatch, n):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import gtja191

    def stop():
        raise ComputationStopped("cancelled")

    monkeypatch.setattr(gtja191, "computation_checkpoint", stop)
    with pytest.raises(ComputationStopped):
        calculate(sample(30), n, custom(n))


@pytest.mark.asyncio
async def test_vwap_panel_real_evaluation_freeze_readonly_and_recompute(monkeypatch):
    from easy_tdx.web.factor_archive import validate_factor_archive
    from easy_tdx.web.routers import research
    from tests.unit.test_factor_archive import record
    from tests.unit.test_gtja191_archive import envelope

    async def fetch(*args):
        # Six explicitly synthetic pool members derived from one frozen tape;
        # real three-stock numerical coverage is a separate test above.
        f = frozen("0-000001-DAILY-NONE.json").copy()
        scale = np.exp(int(args[3][-1]) * 0.0005 * np.arange(len(f)))
        f[["open", "high", "low", "close"]] = f[["open", "high", "low", "close"]].mul(scale, axis=0)
        f["amount"] *= scale
        return f

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda f: f)
    # Respect the production endpoint's four-factor resource limit.
    for start in range(0, len(DEFAULTS), 4):
        group = sorted(DEFAULTS)[start : start + 4]
        names = [f"gtja191_{n:03d}" for n in group]
        req = research.FactorEvaluationRequest(
            stocks=[
                {"market": m, "code": c} for m, c in [("SZ", f"00000{i}") for i in range(1, 7)]
            ],
            factors=names,
            count=160,
            adjust="NONE",
            factor_parameters={
                name: custom(int(name[-3:])) for name in names if DEFAULTS[int(name[-3:])]
            },
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
            guard.setattr(
                research, "fetch_adjusted_bars", lambda *a: pytest.fail("recompute fetches")
            )
            newer = research.recompute_factor_payload(record(original))
        validate_factor_archive(newer)
        assert newer["result"]["reports"] == result["reports"]
        assert newer["result"]["latest"] == result["latest"]
        assert original == before


def test_vwap_inventory_not_panel_substitutes():
    assert {n for n, s in SPECS.items() if "vwap" in s.inputs} == set(DEFAULTS) | {
        39,
        44,
        61,
        64,
        73,
        74,
        77,
        87,
        92,
        101,
        119,
        121,
        125,
        130,
        138,
        156,
    }
    assert {n for n in DEFAULTS if not SPECS[n].panel} == SERIES


def long_frozen(name):
    root = Path(__file__).parents[1] / "fixtures/factor_vwap_long"
    hashes = dict(line.split()[::-1] for line in (root / "SHA256SUMS").read_text().splitlines())
    raw = (root / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == hashes[name]
    payload = json.loads(raw)
    encoded = json.dumps(payload["bars"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(encoded.encode()).hexdigest() == payload["bars_sha256"]
    assert payload["source"] == "MAC" and payload["adjust"] == "NONE"
    assert payload["requested_count"] == len(payload["bars"]) == 320
    frame = pd.DataFrame(payload["bars"])
    frame["datetime"] = pd.to_datetime(frame.datetime)
    frame.attrs["snapshot_metadata"] = dict(
        source="MAC",
        actual_adjust="NONE",
        category="DAY" if payload["period"] == "DAILY" else payload["period"],
        observed_at=payload["observed_at"],
    )
    return qualify_factor_fields(frame, frame, need_vwap=True)


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_vwap_long_real_default_windows_have_observed_values(n):
    data = {
        code: long_frozen(f"{market}-{code}-DAILY-NONE.json")
        for market, code in [
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
    }
    values = calculate(data, n)
    np.testing.assert_allclose(
        values, independent(data, n, DEFAULTS[n]), atol=2e-10, rtol=2e-8, equal_nan=True
    )
    assert values.notna().any().any(), "Default formula must produce actual post-warmup evidence"
    if n in SERIES:
        data = {"300750": long_frozen("0-300750-MIN_30-NONE.json")}
        values = calculate(data, n)
        np.testing.assert_allclose(
            values, independent(data, n, DEFAULTS[n]), atol=2e-10, rtol=2e-8, equal_nan=True
        )
        assert values.notna().any().any()


@pytest.mark.parametrize("n", [16, 36, 90, 179])
def test_vwap_real_constant_price_ranks_are_undefined_not_zero(n):
    data = {
        code: long_frozen(f"{market}-{code}-DAILY-NONE.json")
        for market, code in [(0, "000001"), (0, "300750"), (1, "600036")]
    }
    values = calculate(data, n)
    np.testing.assert_allclose(values, independent(data, n, DEFAULTS[n]), equal_nan=True)
    assert values.isna().all().all()
