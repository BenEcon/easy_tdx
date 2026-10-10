"""Independent complete-window list oracle for linear-decay panel formulas."""

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
    35: dict(lag=1, price_decay=15, corr=17, corr_decay=7),
    61: dict(lag=1, price_decay=12, volume_mean=80, corr=8, corr_decay=17),
    87: dict(lag=4, price_decay=7, ratio_decay=11, rank=7),
    92: dict(lag=2, price_decay=3, volume_mean=180, corr=13, corr_decay=5, rank=15),
    156: dict(lag=5, price_decay=3, mix_lag=2, mix_decay=3),
}
INPUTS = {
    35: ("open", "volume"),
    61: ("vwap", "low", "volume"),
    87: ("vwap", "open", "high", "low"),
    92: ("close", "vwap", "volume"),
    156: ("vwap", "open", "low"),
}
WARMUP = {35: 23, 61: 103, 87: 17, 92: 210, 156: 8}


def warmup(n, p):
    left = p["lag"] + p["price_decay"]
    if n == 35:
        right = p["corr"] + p["corr_decay"] - 1
    elif n == 61:
        right = p["volume_mean"] + p["corr"] + p["corr_decay"] - 2
    elif n == 87:
        right = p["ratio_decay"] + p["rank"] - 1
    elif n == 92:
        right = p["volume_mean"] + p["corr"] + p["corr_decay"] + p["rank"] - 3
    else:
        right = p["mix_lag"] + p["mix_decay"]
    return max(left, right)


def independent(data, n, p):
    dates = sorted({d for f in data.values() for d in f.datetime})
    shape = len(dates), len(data)
    fields = {k: np.full(shape, np.nan) for k in INPUTS[n]}
    for j, f in enumerate(data.values()):
        for row in f.to_dict("records"):
            for k in fields:
                fields[k][dates.index(row["datetime"]), j] = row[k]
    valid = np.ones(shape, dtype=bool)
    for k, a in fields.items():
        valid &= np.isfinite(a) & (a >= 0 if k == "volume" else a > 0)
    for top, bottom in [("high", "low"), ("high", "open"), ("open", "low")]:
        if top in fields and bottom in fields:
            valid &= fields[top] >= fields[bottom]
    blank = np.full(shape, np.nan)
    c, o, h, lo, v, w = [
        np.where(valid, fields.get(k, blank), np.nan)
        for k in ("close", "open", "high", "low", "volume", "vwap")
    ]

    def mask(a, length):
        return np.where(roll(valid.astype(float), length, sum) == length, a, np.nan)

    def decay(a, length):
        return roll(
            a,
            length,
            lambda x: math.fsum((i + 1) * y for i, y in enumerate(x)) / (length * (length + 1) / 2),
        )

    def rank_decay(a, length):
        return roll(
            a,
            length,
            lambda x: float(
                sum(
                    (i + 1) * Fraction(float(y)).limit_denominator(2 * len(data))
                    for i, y in enumerate(x)
                )
                / (length * (length + 1) // 2)
            ),
        )

    def delta(a, length):
        return mask(a - lag(a, length), length + 1)

    def tr(a, length):
        return roll(
            a,
            length,
            lambda x: (sum(y < x[-1] for y in x) + (sum(y == x[-1] for y in x) + 1) / 2) / length,
        )

    with np.errstate(all="ignore"):
        if n == 35:
            out = -np.minimum(
                xs(decay(delta(o, p["lag"]), p["price_decay"])),
                xs(decay(pairs(v, o, p["corr"]), p["corr_decay"])),
            )
        elif n == 61:
            out = -np.maximum(
                xs(decay(delta(w, p["lag"]), p["price_decay"])),
                xs(
                    rank_decay(
                        xs(pairs(lo, roll(v, p["volume_mean"], statistics.mean), p["corr"])),
                        p["corr_decay"],
                    )
                ),
            )
        elif n == 87:
            out = -xs(decay(delta(w, p["lag"]), p["price_decay"])) - tr(
                decay((lo - w) / (o - (h / 2 + lo / 2)), p["ratio_decay"]), p["rank"]
            )
        elif n == 92:
            out = -np.maximum(
                xs(decay(delta(0.35 * c + 0.65 * w, p["lag"]), p["price_decay"])),
                tr(
                    decay(
                        abs(pairs(roll(v, p["volume_mean"], statistics.mean), c, p["corr"])),
                        p["corr_decay"],
                    ),
                    p["rank"],
                ),
            )
        elif n == 156:
            mix = 0.15 * o + 0.85 * lo
            out = -np.maximum(
                xs(decay(delta(w, p["lag"]), p["price_decay"])),
                xs(decay(-delta(mix, p["mix_lag"]) / mix, p["mix_decay"])),
            )
        else:
            raise AssertionError(n)
    return np.where(np.isfinite(out), mask(out, warmup(n, p)), np.nan)


def calculate(data, n, p=None):
    return FactorEngine().compute_matrix(data, configure_factor(f"gtja191_{n:03d}", p or {}))


@pytest.mark.parametrize("n", sorted(DEFAULTS))
@pytest.mark.parametrize("size", [None, 3, 7])
def test_decay_independent_defaults_custom_causal_and_order(n, size):
    p = DEFAULTS[n] if size is None else dict.fromkeys(DEFAULTS[n], size)
    data = sample(250)
    out = calculate(data, n, p)
    np.testing.assert_allclose(out, independent(data, n, p), equal_nan=True, atol=2e-10)
    assert out.notna().any().any()
    assert out.iloc[: warmup(n, p) - 1].isna().all().all()
    pd.testing.assert_frame_equal(
        out.iloc[:240], calculate({s: f.iloc[:240] for s, f in data.items()}, n, p)
    )
    pd.testing.assert_frame_equal(
        out, calculate(dict(reversed(list(data.items()))), n, p)[out.columns]
    )


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_decay_invalid_fields_dates_constant_zero_recovery(n):
    p, data = dict.fromkeys(DEFAULTS[n], 3), sample(70)
    for k in INPUTS[n]:
        changed = copy.deepcopy(data)
        for s, pos, bad in [("S0", 20, np.nan), ("S1", 24, np.inf), ("S2", 28, -1.0)]:
            changed[s].loc[pos, k] = bad
        changed["S3"] = changed["S3"].drop(index=33)
        out = calculate(changed, n, p)
        np.testing.assert_allclose(out, independent(changed, n, p), equal_nan=True, atol=2e-10)
        assert out.iloc[55:].notna().any().any()
    for f in data.values():
        for k in ("open", "high", "low", "close", "vwap"):
            f[k] = 10.0
        f["volume"] = 0.0
    out = calculate(data, n, p)
    np.testing.assert_allclose(out, independent(data, n, p), equal_nan=True, atol=2e-10)
    if n in {35, 61, 87, 92}:
        assert out.isna().all().all()
    else:
        assert (out.iloc[warmup(n, p) - 1 :] == 0).sum().sum() == 0


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_decay_real_ten_stock_default_values(n):
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
def test_decay_metadata_reject_single_missing_adjusted_and_cancel(monkeypatch, n):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import gtja191
    from easy_tdx.factor.catalog import describe_factor

    factor = configure_factor(f"gtja191_{n:03d}")
    assert factor.spec.inputs == INPUTS[n]
    assert factor.spec.resolved_parameters == DEFAULTS[n]
    assert factor.spec.warmup == WARMUP[n]
    data = sample(40)
    with pytest.raises(ValueError, match="股票池"):
        factor.compute(data["S0"])
    metadata = describe_factor(type(factor))
    assert metadata["implementation_version"] == gtja191.VERSION
    for k in INPUTS[n]:
        with pytest.raises(ValueError):
            calculate({s: f.drop(columns=k) for s, f in data.items()}, n)
    for k in DEFAULTS[n]:
        with pytest.raises(ValueError):
            configure_factor(f"gtja191_{n:03d}", {k: 0})
    if n != 35:
        for f in data.values():
            f.attrs["snapshot_metadata"]["actual_adjust"] = "QFQ"
        with pytest.raises(ValueError):
            calculate(data, n)

    def stop():
        raise ComputationStopped("cancelled")

    monkeypatch.setattr(gtja191, "computation_checkpoint", stop)
    with pytest.raises(ComputationStopped):
        calculate(sample(40), n, dict.fromkeys(DEFAULTS[n], 3))


def test_decay_hand_weights_missing_branch_and_zero_denominator():
    from easy_tdx.factor.builtin.gtja191 import _linear_decay

    out = _linear_decay(pd.DataFrame({"x": [2.0, 4.0, 8.0, np.nan, 10.0, 20.0, 30.0]}), 3)
    assert out.x.iloc[2] == pytest.approx(34 / 6)
    assert out.x.iloc[3:6].isna().all()
    assert out.x.iloc[6] == pytest.approx(140 / 6)
    assert _linear_decay(pd.DataFrame({"x": [1e308] * 5}), 3).x.iloc[-1] == 1e308
    data = sample(40)
    for f in data.values():
        f["open"] = (f.high + f.low) / 2
    assert calculate(data, 87, dict.fromkeys(DEFAULTS[87], 3)).isna().all().all()


def test_decay_061_exact_rank_weight_ties_and_changing_membership():
    from easy_tdx.factor.builtin.gtja191 import _linear_rank_mean

    # Both numerators are exactly 2.6; dot(normalized weights) can split them.
    data = pd.DataFrame(
        {
            "A": [0.2, 0.6, 0.4],
            "B": [0.4, 0.2, 0.6],
            "C": [0.5, 1 / 3, 0.5],
            "D": [np.nan, 0.5, 0.75],
            "E": [1.0, 1.0, 1.0],
        }
    )
    result = _linear_rank_mean(data, 3).iloc[-1]
    assert result.A == result.B == float(Fraction(13, 30))
    assert result.C == float(Fraction(4, 9))
    assert pd.isna(result.D)


@pytest.mark.asyncio
async def test_decay_research_archive_readonly_recompute(monkeypatch):
    from easy_tdx.factor.builtin.gtja191 import GTJAPanelFactor
    from easy_tdx.web.factor_archive import validate_factor_archive
    from easy_tdx.web.routers import research
    from tests.unit.test_factor_archive import record
    from tests.unit.test_factor_data import frozen
    from tests.unit.test_gtja191_archive import envelope

    async def fetch(*args):
        # Explicit synthetic six-member pool derived from a frozen tape.
        f = frozen("0-000001-DAILY-NONE.json").copy()
        scale = np.exp(int(args[3][-1]) * 0.0005 * np.arange(len(f)))
        f[["open", "high", "low", "close"]] = f[["open", "high", "low", "close"]].mul(scale, axis=0)
        f["amount"] *= scale
        return f

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda f: f)
    for group in ([35, 61, 87, 92], [156]):
        req = research.FactorEvaluationRequest(
            stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 7)],
            factors=[f"gtja191_{n:03d}" for n in group],
            count=160,
            adjust="NONE",
            factor_parameters={f"gtja191_{n:03d}": dict.fromkeys(DEFAULTS[n], 3) for n in group},
        )
        result = (await research.factor_evaluate(req, None, None)).data
        assert not result["errors"]
        original = envelope(result, "evaluation")
        before = copy.deepcopy(original)
        with monkeypatch.context() as guard:
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
