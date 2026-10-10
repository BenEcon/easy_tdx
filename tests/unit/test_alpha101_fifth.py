"""Independent Alpha024 oracle and cross-library sign/VWAP contract verification."""

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
from tests.unit.test_alpha101_third import pool
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import FILES, frozen
from tests.unit.test_gtja191_panel_compound import independent as compound_oracle
from tests.unit.test_gtja191_vwap import independent as vwap_oracle
from tests.unit.test_gtja191_vwap import long_frozen

NUMBERS = (24, 41, 42, 50, 55)
CUSTOM = {
    24: dict(mean=4, lag=3, trough=5, price_lag=2, threshold=0.02),
    41: {},
    42: {},
    50: dict(corr=3, peak=3),
    55: dict(range=4, corr=3),
}


def sample(size=230):
    frames = pool(size)
    for j, f in enumerate(frames.values()):
        # Deliberately crossing price paths: fixed cross-sectional ordering makes
        # rank correlations undefined and cannot exercise a nonempty result.
        scale = 1 + 0.5 * np.sin(np.arange(size) / (1.2 + j * 0.4) + j)
        f[["open", "close", "high", "low"]] = f[["open", "close", "high", "low"]].mul(scale, axis=0)
        f["volume"] = f.volume.astype(float)
        f["vwap"] = (f.high + f.low + f.close) / 3
        f.attrs["snapshot_metadata"] = {"actual_adjust": "NONE"}
    return frames


def series_oracle(frame, spec):
    if spec.number == 41:
        data = {"single": frame.rename_axis("datetime").reset_index()}
        return pd.Series(vwap_oracle(data, 13, {}).ravel(), index=frame.index)
    p = spec.resolved_parameters
    out = pd.Series(np.nan, index=frame.index)
    for i in range(spec.warmup - 1, len(frame)):
        block = frame.close.iloc[i - spec.warmup + 1 : i + 1]
        if not np.isfinite(block).all() or not block.gt(0).all():
            continue
        c = [Fraction(str(v)) if np.isfinite(v) else None for v in frame.close.iloc[: i + 1]]
        current = sum(c[i - p["mean"] + 1 : i + 1]) / p["mean"]
        t = i - p["lag"]
        previous = sum(c[t - p["mean"] + 1 : t + 1]) / p["mean"]
        change = (current - previous) / c[t]
        value = (
            min(c[i - p["trough"] + 1 : i + 1])
            if change <= Fraction(str(spec.threshold))
            else c[i - p["price_lag"]]
        ) - c[i]
        out.iloc[i] = float(value)
    return out


def expected(frames, spec):
    if not spec.panel:
        return pd.DataFrame({s: series_oracle(f, spec) for s, f in frames.items()})
    data = {s: f.rename_axis("datetime").reset_index() for s, f in frames.items()}
    p = dict(spec.reference_parameters)
    values = (
        -compound_oracle(data, 176, p)
        if spec.number == 55
        else vwap_oracle(data, {42: 120, 50: 16}[spec.number], p)
    )
    return pd.DataFrame(
        values, index=sorted({d for f in frames.values() for d in f.index}), columns=list(frames)
    )


@pytest.mark.parametrize("n", NUMBERS)
@pytest.mark.parametrize("custom", [False, True])
def test_fifth_independent_prefix_permutation(n, custom):
    factor = configure_factor(name(n), CUSTOM[n] if custom else {})
    frames = sample()
    actual = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(actual, expected(frames, factor.spec), equal_nan=True, atol=1e-10)
    assert actual.notna().any().any()
    prefix = FactorEngine().compute_matrix({s: f.iloc[:210] for s, f in frames.items()}, factor)
    pd.testing.assert_frame_equal(prefix, actual.iloc[:210])
    reverse = FactorEngine().compute_matrix(dict(reversed(list(frames.items()))), factor)
    pd.testing.assert_frame_equal(reverse[list(actual)], actual)


@pytest.mark.parametrize("n", NUMBERS)
def test_fifth_invalid_missing_constant_recovery(n):
    factor = configure_factor(name(n), CUSTOM[n])
    for field in factor.inputs:
        for invalid in (np.nan, np.inf, -1.0):
            data = sample(40)
            data["S0"].loc[data["S0"].index[15], field] = invalid
            actual = FactorEngine().compute_matrix(data, factor)
            np.testing.assert_allclose(
                actual, expected(data, factor.spec), equal_nan=True, atol=1e-10
            )
            assert actual.S0.iloc[15 : 15 + factor.spec.warmup].isna().all()
            assert actual.S0.iloc[30:].notna().any()
    data = sample(40)
    data["S0"] = data["S0"].drop(data["S0"].index[15])
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(data, factor),
        expected(data, factor.spec),
        equal_nan=True,
        atol=1e-10,
    )
    for f in data.values():
        f[["open", "close", "high", "low", "vwap"]] = 10.0
        f["volume"] = 0.0
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(data, factor),
        expected(data, factor.spec),
        equal_nan=True,
        atol=1e-10,
    )


@pytest.mark.parametrize("n", NUMBERS)
def test_fifth_metadata_parameter_scope_and_mutation(n):
    cls = get_factor(name(n))
    meta = describe_factor(cls)
    factor = configure_factor(name(n), CUSTOM[n])
    assert meta["warmup_bars"] == {24: 200, 41: 1, 42: 1, 50: 9, 55: 17}[n]
    assert meta["supported_adjustments"] == (
        ["NONE"] if n in {41, 42, 50} else ["NONE", "QFQ", "HFQ"]
    )
    assert meta["release_status"] == "local_validation_only_pending_license_review"
    for key in CUSTOM[n]:
        bad_values = (
            (True, None, float("inf"), "2", 1.01)
            if key == "threshold"
            else (True, None, 0, 601, 1.5)
        )
        for bad in bad_values:
            with pytest.raises(ValueError):
                configure_factor(name(n), {key: bad})
    with pytest.raises(ValueError):
        configure_factor(name(n), {"unknown": 1})
    data = sample(20)
    old = copy.deepcopy(data)
    FactorEngine().compute_matrix(data, factor)
    for s in data:
        pd.testing.assert_frame_equal(data[s], old[s])
    assert describe_factor(cls) == meta
    if factor.spec.panel:
        with pytest.raises(ValueError, match="股票池"):
            factor.compute(data["S0"])
        assert (
            factor.compute_panel(FactorPanel.build({"s": data["S0"]}, factor.inputs))
            .isna()
            .all()
            .all()
        )
    else:
        assert factor.compute(data["S0"].iloc[:0]).empty


def test_fifth_threshold_equality_exact_large_values_and_alias_sign():
    factor = configure_factor(name(24), dict(mean=2, lag=2, trough=2, price_lag=1))
    # Current mean 10.5 vs prior 10; delayed close 10: exactly threshold .05.
    f = pd.DataFrame({"close": [10.0, 10.0, 10.6, 10.4]})
    assert factor.compute(f).iloc[-1] == 0.0
    f.loc[3, "close"] = 10.400000000000002
    assert factor.compute(f).iloc[-1] == pytest.approx(0.2)
    for scale in (1e-150, 1e150, 1e306):
        scaled = f * scale
        np.testing.assert_allclose(
            factor.compute(scaled), series_oracle(scaled, factor.spec), equal_nan=True
        )
    with pytest.raises(ValueError, match="600"):
        configure_factor(name(24), dict(mean=400, lag=400))
    for a, g in ((41, 13), (42, 120), (50, 16)):
        with pytest.raises(ValueError, match="重复"):
            configured_selection([name(a), f"gtja191_{g:03d}"])
    assert len(configured_selection([name(55), "gtja191_176"])) == 2
    data = sample(40)
    a = FactorEngine().compute_matrix(data, configure_factor(name(55)))
    g = FactorEngine().compute_matrix(data, configure_factor("gtja191_176"))
    np.testing.assert_allclose(a, -g, equal_nan=True)
    assert describe_factor(get_factor(name(55)))["alias_of"] is None


@pytest.mark.parametrize("n", (41, 42, 50))
def test_fifth_vwap_adjustments_are_not_silently_converted(n):
    factor = configure_factor(name(n))
    for adjust in ("QFQ", "HFQ"):
        data = sample(30)
        for f in data.values():
            f.attrs["snapshot_metadata"]["actual_adjust"] = adjust
        with pytest.raises(ValueError, match="不复权"):
            FactorEngine().compute_matrix(data, factor)
        assert availability_reason(describe_factor(type(factor)), adjust)
        assert availability_reason(describe_factor(type(factor)), adjust, evaluation=True)
    data = sample(30)
    data["S0"] = data["S0"].drop(columns="vwap")
    with pytest.raises(ValueError):
        FactorEngine().compute_matrix(data, factor)


@pytest.mark.parametrize("n", NUMBERS)
def test_fifth_real_frozen_pool_minute(n):
    root = Path(__file__).parents[1] / "fixtures/factor_vwap_long"
    data = {
        p.stem: long_frozen(p.name).set_index("datetime")
        for p in sorted(root.glob("*-DAILY-NONE.json"))
    }
    factor = configure_factor(name(n))
    actual = FactorEngine().compute_matrix(data, factor)
    np.testing.assert_allclose(actual, expected(data, factor.spec), equal_nan=True, atol=1e-10)
    assert actual.notna().any().any()
    minute = long_frozen("0-300750-MIN_30-NONE.json").set_index("datetime")
    if not factor.spec.panel:
        np.testing.assert_allclose(
            factor.compute(minute), series_oracle(minute, factor.spec), equal_nan=True, atol=1e-10
        )
    else:
        assert (
            factor.compute_panel(FactorPanel.build({"real": minute}, factor.inputs))
            .isna()
            .all()
            .all()
        )


@pytest.mark.parametrize("n", (24, 55))
@pytest.mark.parametrize("adjust", ("NONE", "QFQ", "HFQ"))
def test_fifth_real_adjustments(n, adjust):
    data = {
        f: qualify_factor_fields(frozen(f), frozen(f.replace(adjust, "NONE"))).set_index("datetime")
        for f in FILES
        if f.endswith(f"-DAILY-{adjust}.json")
    }
    factor = configure_factor(name(n), CUSTOM[n])
    actual = FactorEngine().compute_matrix(data, factor)
    np.testing.assert_allclose(actual, expected(data, factor.spec), equal_nan=True, atol=1e-10)
    assert actual.notna().any().any()


@pytest.mark.asyncio
@pytest.mark.parametrize("n", NUMBERS)
async def test_fifth_archive_readonly_and_frozen_recompute(monkeypatch, n):
    frame = long_frozen("0-000001-DAILY-NONE.json").iloc[-80:]
    if n in {24, 41}:
        req = research.FactorComputeRequest(
            market="SZ",
            code="000001",
            count=80,
            adjust="NONE",
            factors=[name(n)],
            factor_parameters={name(n): CUSTOM[n]},
        )
        result = research._factor_result(req, frame).data
        mode = "series"
    else:

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
        mode = "evaluation"
    assert not result["errors"]
    original = {
        "format": "factor-research-v1",
        "mode": mode,
        "title": "Alpha fifth local",
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
    key = "rows" if mode == "series" else "reports"
    assert replay["result"][key] == original["result"][key]
    assert original == before


def test_fifth_midway_cancellation(monkeypatch):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import alpha101_compound

    calls = 0

    def stop():
        nonlocal calls
        calls += 1
        if calls == 12:
            raise ComputationStopped("cancelled")

    monkeypatch.setattr(alpha101_compound, "computation_checkpoint", stop)
    with pytest.raises(ComputationStopped):
        configure_factor(name(24), CUSTOM[24]).compute(sample(50)["S0"])
    assert calls == 12
