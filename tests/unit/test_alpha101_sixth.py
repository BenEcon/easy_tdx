"""Independent slice/rank checks for source distinctions in Alpha005/011/027/052."""

import copy
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.builtin.alpha101 import Alpha101Factor, Alpha101PanelFactor
from easy_tdx.factor.catalog import availability_reason, describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.factor.panel import FactorPanel
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_alpha101 import name
from tests.unit.test_alpha101_fifth import sample
from tests.unit.test_alpha101_fourth import rank
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import FILES, frozen
from tests.unit.test_gtja191_vwap import independent as vwap_oracle
from tests.unit.test_gtja191_vwap import long_frozen

NUMBERS = (5, 11, 27, 52)
CUSTOM = {
    5: {"mean": 3},
    11: {"range": 5, "lag": 2},
    27: {"corr": 3, "sum": 3, "threshold": 0.7},
    52: {"trough": 4, "lag": 3, "long": 12, "short": 3, "volume_rank": 4},
}


def expected(frames, spec):
    dates = sorted({d for f in frames.values() for d in f.index})
    if spec.number in {11, 27}:
        data = {s: f.rename_axis("datetime").reset_index() for s, f in frames.items()}
        values = vwap_oracle(data, {11: 7, 27: 36}[spec.number], dict(spec.reference_parameters))
        if spec.number == 27:
            values = np.where(
                np.isfinite(values), np.where(values > spec.threshold, -1.0, 1.0), np.nan
            )
        return pd.DataFrame(values, index=dates, columns=list(frames))
    p, n = spec.resolved_parameters, spec.number
    first, second, multiplier = ([[None] * len(frames) for _ in dates] for _ in range(3))
    for j, frame in enumerate(frames.values()):
        data = frame.reindex(dates)
        for i in range(spec.warmup - 1, len(dates)):
            block = data[list(spec.inputs)].iloc[i + 1 - spec.warmup : i + 1]
            if not np.isfinite(block).all().all() or any(
                not (block[k].ge(0) if k == "volume" else block[k].gt(0)).all() for k in spec.inputs
            ):
                continue

            def q(key, t):
                return Fraction(str(data[key].iloc[t]))

            if n == 5:
                avg = sum(q("vwap", t) for t in range(i - p["mean"] + 1, i + 1)) / p["mean"]
                first[i][j] = q("open", i) - avg
                second[i][j] = q("close", i) - q("vwap", i)
            else:
                if not block.low.le(block.close).all():
                    continue
                # Disjoint interval, not production's subtraction of rolling sums.
                first[i][j] = sum(
                    q("close", t) / q("close", t - 1) - 1
                    for t in range(i - p["long"] + 1, i - p["short"] + 1)
                ) / (p["long"] - p["short"])
                end = i - p["lag"]
                previous = min(q("low", t) for t in range(end - p["trough"] + 1, end + 1))
                current = min(q("low", t) for t in range(i - p["trough"] + 1, i + 1))
                volumes = data.volume.iloc[i - p["volume_rank"] + 1 : i + 1].tolist()
                position = Fraction(
                    2 * sum(v < volumes[-1] for v in volumes)
                    + sum(v == volumes[-1] for v in volumes)
                    + 1,
                    2 * len(volumes),
                )
                multiplier[i][j] = (previous - current) * position
    out = np.full((len(dates), len(frames)), np.nan)
    for i in range(len(dates)):
        other = rank(second[i]) if n == 5 else multiplier[i]
        for j, (a, b) in enumerate(zip(rank(first[i]), other)):
            if a is not None and b is not None:
                out[i, j] = float(-a * abs(b) if n == 5 else a * b)
    return pd.DataFrame(out, index=dates, columns=list(frames))


@pytest.mark.parametrize("n", NUMBERS)
@pytest.mark.parametrize("custom", [False, True])
def test_sixth_independent_prefix_and_permutation(n, custom):
    factor = configure_factor(name(n), CUSTOM[n] if custom else {})
    frames = sample(260)
    original = copy.deepcopy(frames)
    out = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(out, expected(frames, factor.spec), equal_nan=True, atol=1e-10)
    assert out.notna().any().any()
    prefix = FactorEngine().compute_matrix({s: f.iloc[:250] for s, f in frames.items()}, factor)
    pd.testing.assert_frame_equal(prefix, out.iloc[:250])
    reverse = FactorEngine().compute_matrix(dict(reversed(list(frames.items()))), factor)
    pd.testing.assert_frame_equal(reverse[list(out)], out)
    for s in frames:
        pd.testing.assert_frame_equal(frames[s], original[s])


@pytest.mark.parametrize("n", NUMBERS)
def test_sixth_invalid_missing_constant_recovery(n):
    factor = configure_factor(name(n), CUSTOM[n])
    for field in factor.inputs:
        for bad in (np.nan, np.inf, -1.0):
            frames = sample(65)
            frames["S0"].loc[frames["S0"].index[20], field] = bad
            out = FactorEngine().compute_matrix(frames, factor)
            np.testing.assert_allclose(
                out, expected(frames, factor.spec), equal_nan=True, atol=1e-10
            )
            assert out.S0.iloc[20 : 20 + factor.spec.warmup].isna().all()
            assert out.S0.iloc[45:].notna().any()
    frames = sample(65)
    frames["S0"] = frames["S0"].drop(frames["S0"].index[20])
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(frames, factor),
        expected(frames, factor.spec),
        equal_nan=True,
        atol=1e-10,
    )
    # Keep the constant-pool check balanced: a missing constituent changes
    # percentile ranks even when every observed price/volume is constant.
    frames = sample(65)
    for f in frames.values():
        f[["open", "high", "low", "close", "vwap"]] = 10.0
        f["volume"] = 0.0
    out = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(out, expected(frames, factor.spec), equal_nan=True, atol=1e-10)
    if n == 27:
        assert out.isna().all().all()


@pytest.mark.parametrize("n", NUMBERS)
def test_sixth_metadata_configuration_identity_and_limits(n):
    cls = get_factor(name(n))
    meta = describe_factor(cls)
    assert meta["warmup_bars"] == {5: 10, 11: 4, 27: 7, 52: 241}[n]
    assert meta["supported_adjustments"] == (["NONE", "QFQ", "HFQ"] if n == 52 else ["NONE"])
    for key in CUSTOM[n]:
        bad_values = (
            (True, None, -1, 1.1, np.inf) if key == "threshold" else (True, None, 0, 601, 1.5)
        )
        for bad in bad_values:
            with pytest.raises(ValueError):
                configure_factor(name(n), {key: bad})
    with pytest.raises(ValueError):
        configure_factor(name(n), {"unknown": 1})
    factor = configure_factor(name(n), CUSTOM[n])
    assert describe_factor(cls) == meta
    with pytest.raises(ValueError, match="股票池"):
        factor.compute(sample(30)["S0"])
    assert (
        factor.compute_panel(FactorPanel.build({"s": sample(30)["S0"]}, factor.inputs))
        .isna()
        .all()
        .all()
    )
    if n != 52:
        for adjust in ("QFQ", "HFQ"):
            assert availability_reason(meta, adjust, evaluation=True)
            frames = sample(40)
            for f in frames.values():
                f.attrs["snapshot_metadata"]["actual_adjust"] = adjust
            with pytest.raises(ValueError, match="不复权"):
                FactorEngine().compute_matrix(frames, factor)
    else:
        with pytest.raises(ValueError, match="短窗口"):
            configure_factor(name(n), {"short": 240, "long": 240})
        with pytest.raises(ValueError, match="600"):
            configure_factor(name(n), {"trough": 400, "lag": 400})


def test_sixth_absolute_rank_threshold_and_reference_window_distinctions():
    frames = {
        str(i): pd.DataFrame(
            {"open": [11.0], "close": [c], "vwap": [10.0]},
            index=pd.date_range("2025-01-01", periods=1),
        )
        for i, c in enumerate((8.0, 9.0, 11.0, 12.0))
    }
    a = FactorEngine().compute_matrix(frames, configure_factor(name(5), {"mean": 1}))
    np.testing.assert_allclose(a.iloc[0], [-0.625 * v for v in (0.25, 0.5, 0.75, 1)])
    g = FactorEngine().compute_matrix(frames, configure_factor("gtja191_012", {"mean": 1}))
    assert not np.allclose(a, g)
    assert len(configured_selection([name(5), "gtja191_012"])) == 2
    assert len(configured_selection([name(27), "gtja191_036"])) == 2
    with pytest.raises(ValueError, match="重复"):
        configured_selection([name(11), "gtja191_007"])
    data = sample(45)
    ranked = FactorEngine().compute_matrix(
        data, configure_factor("gtja191_036", {"corr": 3, "sum": 3})
    )
    for threshold in (0.0, 0.5, 0.625, 1.0):
        factor = configure_factor(name(27), {"corr": 3, "sum": 3, "threshold": threshold})
        out = FactorEngine().compute_matrix(data, factor)
        target = np.where(ranked.notna(), np.where(ranked > threshold, -1.0, 1.0), np.nan)
        np.testing.assert_allclose(out, target, equal_nan=True)
    assert get_factor(name(52))().spec.resolved_parameters["short"] == 20
    assert "220" in " ".join(describe_factor(get_factor(name(52)))["reference_differences"])


@pytest.mark.parametrize("n", NUMBERS)
def test_sixth_real_frozen_default_pool_and_minute(n):
    root = Path(__file__).parents[1] / "fixtures/factor_vwap_long"
    frames = {
        p.stem: long_frozen(p.name).set_index("datetime")
        for p in sorted(root.glob("*-DAILY-NONE.json"))
    }
    factor = configure_factor(name(n))
    out = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(out, expected(frames, factor.spec), equal_nan=True, atol=1e-10)
    assert out.notna().any().any()
    frame = long_frozen("0-300750-MIN_30-NONE.json").set_index("datetime")
    assert (
        factor.compute_panel(FactorPanel.build({"real": frame}, factor.inputs)).isna().all().all()
    )


@pytest.mark.parametrize("adjust", ("NONE", "QFQ", "HFQ"))
def test_sixth_052_real_adjustments(adjust):
    frames = {
        f: qualify_factor_fields(frozen(f), frozen(f.replace(adjust, "NONE"))).set_index("datetime")
        for f in FILES
        if f.endswith(f"-DAILY-{adjust}.json")
    }
    factor = configure_factor(name(52), CUSTOM[52])
    out = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(out, expected(frames, factor.spec), equal_nan=True, atol=1e-10)
    assert out.notna().any().any()


@pytest.mark.asyncio
@pytest.mark.parametrize("n", NUMBERS)
async def test_sixth_archive_readonly_frozen_recompute(monkeypatch, n):
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
        "title": "Alpha sixth local",
        "savedAt": "2026-10-10T12:00:00Z",
        "result": result,
    }
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(Alpha101Factor, "compute", lambda *a: pytest.fail("read executes"))
        guard.setattr(Alpha101PanelFactor, "compute_panel", lambda *a: pytest.fail("read executes"))
        validate_factor_archive(original)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("live fetch"))
    replay = research.recompute_factor_payload(record(original))
    assert replay["result"]["reports"] == original["result"]["reports"]
    assert original == before


def test_sixth_midway_cancellation_and_exact_ties(monkeypatch):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import alpha101_compound

    frames = sample(50)
    factor = configure_factor(name(52), CUSTOM[52])
    for scale in (1e-150, 1e150):
        scaled = {s: f.copy() for s, f in frames.items()}
        for f in scaled.values():
            f[["close", "low"]] *= scale
        np.testing.assert_allclose(
            FactorEngine().compute_matrix(scaled, factor),
            expected(scaled, factor.spec),
            equal_nan=True,
        )
    calls = 0

    def stop():
        nonlocal calls
        calls += 1
        if calls == 12:
            raise ComputationStopped("cancelled")

    monkeypatch.setattr(alpha101_compound, "computation_checkpoint", stop)
    with pytest.raises(ComputationStopped):
        FactorEngine().compute_matrix(frames, factor)
    assert calls == 12
