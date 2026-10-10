"""Independent direct-window checks for positional and L1-scale Alpha formulas."""

import copy
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.builtin.alpha101 import Alpha101PanelFactor
from easy_tdx.factor.catalog import availability_reason, describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_alpha101 import name
from tests.unit.test_alpha101_fifth import sample
from tests.unit.test_alpha101_fourth import rank
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import FILES, frozen
from tests.unit.test_gtja191_vwap import long_frozen

NUMBERS = (32, 57, 60)
CUSTOM = {32: {"mean": 3, "lag": 2, "corr": 5}, 57: {"peak": 4, "decay": 3}, 60: {"peak": 4}}


def scale(row):
    good = [v for v in row if v is not None]
    denominator = sum(map(abs, good), Fraction(0))
    return [
        v / denominator if v is not None and len(good) >= 2 and denominator else None for v in row
    ]


def expected(frames, spec):
    dates = sorted({d for f in frames.values() for d in f.index})
    rows, columns = len(dates), len(frames)
    first, second, extra = ([[None] * columns for _ in dates] for _ in range(3))
    full = np.zeros((rows, columns), bool)
    p, n = spec.resolved_parameters, spec.number
    for j, f in enumerate(frames.values()):
        f = f.reindex(dates)
        valid = np.isfinite(f[list(spec.inputs)]).all(axis=1)
        for k in spec.inputs:
            valid &= f[k].ge(0) if k == "volume" else f[k].gt(0)
        if n == 60:
            valid &= f.low.le(f.close) & f.close.le(f.high)
        for i in range(rows):
            full[i, j] = i + 1 >= spec.warmup and valid.iloc[i + 1 - spec.warmup : i + 1].all()
            if n != 32 and i + 1 >= p["peak"] and valid.iloc[i + 1 - p["peak"] : i + 1].all():
                values = f.close.iloc[i + 1 - p["peak"] : i + 1].tolist()
                second[i][j] = Fraction(values.index(max(values)))
            if not full[i, j]:
                continue
            c = Fraction(str(f.close.iloc[i]))
            if n == 32:
                first[i][j] = (
                    sum(
                        (Fraction(str(v)) for v in f.close.iloc[i + 1 - p["mean"] : i + 1]),
                        Fraction(0),
                    )
                    / p["mean"]
                    - c
                )
                # Direct centered sums, independent of production's normalized-dot routine.
                x = f.vwap.iloc[i + 1 - p["corr"] : i + 1].to_numpy()
                y = f.close.iloc[i + 1 - p["corr"] - p["lag"] : i + 1 - p["lag"]].to_numpy()
                a, b = x / np.max(abs(x)), y / np.max(abs(y))
                a, b = a - a.mean(), b - b.mean()
                if np.linalg.norm(a) > 1e-12 and np.linalg.norm(b) > 1e-12:
                    second[i][j] = Fraction(str(float(np.corrcoef(x, y)[0, 1])))
            elif n == 57:
                extra[i][j] = Fraction(str(f.vwap.iloc[i])) - c
            else:
                high, low, volume = (Fraction(str(f[k].iloc[i])) for k in ("high", "low", "volume"))
                if high != low:
                    first[i][j] = ((c - low) - (high - c)) * volume / (high - low)
    if n == 32:
        a, b = list(map(scale, first)), list(map(scale, second))
    elif n == 60:
        a, b = [scale(rank(r)) for r in first], [scale(rank(r)) for r in second]
    else:
        a, b = extra, list(map(rank, second))
    out = pd.DataFrame(np.nan, index=dates, columns=list(frames))
    for i in range(rows):
        for j in range(columns):
            if not full[i, j] or a[i][j] is None:
                continue
            if n == 57:
                history = [b[t][j] for t in range(i + 1 - p["decay"], i + 1)]
                if any(v is None for v in history):
                    continue
                # Expand each observation k times rather than share weighted kernel.
                expanded = [v for k, v in enumerate(history, 1) for _ in range(k)]
                value = a[i][j] / (sum(expanded) / len(expanded))
            elif b[i][j] is None:
                continue
            else:
                value = a[i][j] + 20 * b[i][j] if n == 32 else b[i][j] - 2 * a[i][j]
            out.iloc[i, j] = float(value)
    return out


@pytest.mark.parametrize("n", NUMBERS)
@pytest.mark.parametrize("custom", (False, True))
def test_seventh_independent_prefix_and_permutation(n, custom):
    frames = sample(255 if n == 32 and not custom else 70)
    before = copy.deepcopy(frames)
    factor = configure_factor(name(n), CUSTOM[n] if custom else {})
    result = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(result, expected(frames, factor.spec), equal_nan=True, atol=1e-10)
    assert result.notna().any().any()
    prefix = {s: f.iloc[:-7] for s, f in frames.items()}
    pd.testing.assert_frame_equal(result.iloc[:-7], FactorEngine().compute_matrix(prefix, factor))
    reverse = FactorEngine().compute_matrix(dict(reversed(list(frames.items()))), factor)
    pd.testing.assert_frame_equal(result, reverse[result.columns])
    for s in frames:
        pd.testing.assert_frame_equal(frames[s], before[s])


@pytest.mark.parametrize("n", NUMBERS)
def test_seventh_invalid_constant_missing_and_recovery(n):
    factor = configure_factor(name(n), CUSTOM[n])
    for field in factor.inputs:
        for bad in (np.nan, np.inf, -1.0):
            frames = sample(45)
            frames["S0"].loc[frames["S0"].index[15], field] = bad
            out = FactorEngine().compute_matrix(frames, factor)
            np.testing.assert_allclose(
                out, expected(frames, factor.spec), equal_nan=True, atol=1e-10
            )
            assert out.S0.iloc[15 : 15 + factor.spec.warmup].isna().all()
            assert out.S0.iloc[35:].notna().any()
    frames = sample(45)
    frames["S0"] = frames["S0"].drop(frames["S0"].index[15])
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(frames, factor),
        expected(frames, factor.spec),
        equal_nan=True,
        atol=1e-10,
    )
    frames = sample(35)
    for f in frames.values():
        f[["open", "high", "low", "close", "vwap"]] = 10.0
        f["volume"] = 0.0
    out = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(out, expected(frames, factor.spec), equal_nan=True, atol=1e-10)
    if n in {32, 60}:
        assert out.isna().all().all()


@pytest.mark.parametrize("n", NUMBERS)
def test_seventh_metadata_parameter_and_scope(n):
    meta = describe_factor(get_factor(name(n)))
    assert meta["warmup_bars"] == {32: 235, 57: 31, 60: 10}[n]
    for key in CUSTOM[n]:
        for value in (True, None, 0, 501, 2.5):
            with pytest.raises(ValueError):
                configure_factor(name(n), {key: value})
    with pytest.raises(ValueError):
        configure_factor(name(n), {"unknown": 1})
    factor = configure_factor(name(n), CUSTOM[n])
    assert meta == describe_factor(get_factor(name(n)))
    with pytest.raises(ValueError, match="股票池"):
        factor.compute(sample(40)["S0"])
    with pytest.raises(ValueError, match="至少需要 2"):
        FactorEngine().compute_matrix({"s": sample(40)["S0"]}, factor)
    if n != 60:
        for adj in ("QFQ", "HFQ"):
            assert availability_reason(meta, adj, evaluation=True)
            frames = sample(40)
            for f in frames.values():
                f.attrs["snapshot_metadata"]["actual_adjust"] = adj
            with pytest.raises(ValueError, match="不复权"):
                FactorEngine().compute_matrix(frames, factor)
        with pytest.raises(ValueError, match="600"):
            configure_factor(name(n), {k: 400 for k in CUSTOM[n]})


def test_seventh_position_ties_decay_scale_and_non_alias():
    frames = {}
    for s, seq in zip(("A", "B", "C"), ([3.0, 1.0, 3.0], [1.0, 2.0, 3.0], [1.0, 3.0, 2.0])):
        f = pd.DataFrame({"close": seq}, index=pd.date_range("2025-01-01", periods=3))
        f["vwap"], f["high"], f["low"], f["volume"] = f.close + 1, f.close + 1, f.close - 0.5, 100.0
        frames[s] = f
    result = FactorEngine().compute_matrix(
        frames, configure_factor(name(57), {"peak": 3, "decay": 1})
    )
    np.testing.assert_allclose(result.iloc[-1], [3, 1, 1.5])
    # Every close has the same relative range position; its exact rational rank ties.
    result = FactorEngine().compute_matrix(frames, configure_factor(name(60), {"peak": 3}))
    np.testing.assert_allclose(result.iloc[-1], [-0.5, -1 / 6, -1 / 3])
    assert len(configured_selection([name(57), "gtja191_124"])) == 2
    factor = configure_factor(name(57), {"peak": 2, "decay": 3})
    data = sample(40)
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(data, factor), expected(data, factor.spec), equal_nan=True
    )
    # Zero range excludes only that component; the position normalization still includes A.
    frames["A"].loc[frames["A"].index[-1], ["high", "low"]] = 3.0
    factor = configure_factor(name(60), {"peak": 3})
    out = FactorEngine().compute_matrix(frames, factor)
    assert pd.isna(out.A.iloc[-1])
    np.testing.assert_allclose(out, expected(frames, factor.spec), equal_nan=True)


@pytest.mark.parametrize("n", NUMBERS)
def test_seventh_real_frozen_default_pool_and_minute(n):
    root = Path(__file__).parents[1] / "fixtures/factor_vwap_long"
    frames = {
        p.stem: long_frozen(p.name).set_index("datetime")
        for p in sorted(root.glob("*-DAILY-NONE.json"))
    }
    factor = configure_factor(name(n))
    out = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(out, expected(frames, factor.spec), equal_nan=True, atol=1e-10)
    assert out.notna().any().any()
    minute = long_frozen("0-300750-MIN_30-NONE.json").set_index("datetime")
    with pytest.raises(ValueError, match="至少需要 2"):
        FactorEngine().compute_matrix({"real": minute}, factor)


@pytest.mark.parametrize("adjust", ("NONE", "QFQ", "HFQ"))
def test_seventh_060_real_adjustments(adjust):
    frames = {
        f: qualify_factor_fields(frozen(f), frozen(f.replace(adjust, "NONE"))).set_index("datetime")
        for f in FILES
        if f.endswith(f"-DAILY-{adjust}.json")
    }
    factor = configure_factor(name(60))
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(frames, factor),
        expected(frames, factor.spec),
        equal_nan=True,
        atol=1e-10,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("n", NUMBERS)
async def test_seventh_archive_readonly_frozen_recompute(monkeypatch, n):
    frame = long_frozen("0-000001-DAILY-NONE.json").iloc[-80:]

    async def fetch(*args):
        return frame.copy()

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda f: f)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 7)],
        count=80,
        adjust="NONE",
        factors=[name(n)],
        factor_parameters={name(n): CUSTOM[n]},
    )
    result = (await research.factor_evaluate(req, None, None)).data
    assert not result["errors"]
    original = {
        "format": "factor-research-v1",
        "mode": "evaluation",
        "title": "Alpha seventh local",
        "savedAt": "2026-10-10T12:00:00Z",
        "result": result,
    }
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(Alpha101PanelFactor, "compute_panel", lambda *a: pytest.fail("read computes"))
        validate_factor_archive(original)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("live fetch"))
    replay = research.recompute_factor_payload(record(original))
    assert replay["result"]["reports"] == original["result"]["reports"]
    assert original == before


def test_seventh_cancellation_and_extreme_scale(monkeypatch):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import alpha101_compound

    frames = sample(40)
    for n in NUMBERS:
        factor = configure_factor(name(n), CUSTOM[n])
        for multiplier in (1e-150, 1e150):
            data = copy.deepcopy(frames)
            for f in data.values():
                f[["open", "high", "low", "close", "vwap"]] *= multiplier
            np.testing.assert_allclose(
                FactorEngine().compute_matrix(data, factor),
                expected(data, factor.spec),
                equal_nan=True,
                atol=1e-10,
            )
    calls = 0

    def stop():
        nonlocal calls
        calls += 1
        if calls == 12:
            raise ComputationStopped("cancelled")

    monkeypatch.setattr(alpha101_compound, "computation_checkpoint", stop)
    with pytest.raises(ComputationStopped):
        FactorEngine().compute_matrix(frames, configure_factor(name(57), CUSTOM[57]))
    assert calls == 12
