"""Cross-library adapters: independent oracles, not reused production kernels."""

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.builtin.alpha101 import SPECS, Alpha101Factor, Alpha101PanelFactor
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.factor.panel import FactorPanel
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_alpha101 import name, sample
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import FILES, frozen
from tests.unit.test_gtja191_vwap import long_frozen

NUMBERS = (14, 15, 18, 20, 35, 37)
ALIASES = {14: 136, 15: 32, 20: 107, 35: 117, 37: 184}


def series_oracle(frame, spec):
    from tests.unit.test_gtja191_compound import independent

    return pd.Series(independent(frame, 117, dict(spec.reference_parameters)), index=frame.index)


def panel_oracle(frames, spec):
    data = {s: f.rename_axis("datetime").reset_index() for s, f in frames.items()}
    if spec.number == 18:
        from tests.unit.test_gtja191_literal import independent

        return independent(data, 54, dict(spec.reference_parameters))
    from tests.unit.test_gtja191_panel_compound import independent

    out = independent(data, spec.reference, dict(spec.reference_parameters))
    dates = sorted(set().union(*(set(f.index) for f in frames.values())))
    return pd.DataFrame(out, index=pd.DatetimeIndex(dates), columns=list(frames))


def expected(frames, spec):
    return (
        pd.DataFrame({s: series_oracle(f, spec) for s, f in frames.items()})
        if spec.number == 35
        else panel_oracle(frames, spec)
    )


def pool(size=240):
    frames = {}
    for j in range(4):
        f = sample(size)
        t = np.arange(size)
        shift = np.sin(t / (4 + j)) * (j + 1) / 3
        for field in ("open", "close", "high", "low"):
            f[field] = f[field] * (1 + j / 3) + shift
        f["open"] += np.sin(t / 2 + j) / 4
        f["volume"] += (t * (53 + j * 11) + 70 * j) % 333
        frames[f"S{j}"] = f
    return frames


def parameters(n, custom):
    return {k: 3 for k, _ in SPECS[n].reference_parameters} if custom else {}


@pytest.mark.parametrize("n", NUMBERS)
@pytest.mark.parametrize("custom", [False, True])
def test_third_independent_default_custom_prefix_permutation(n, custom):
    factor = configure_factor(name(n), parameters(n, custom))
    data = pool()
    data["S1"] = data["S1"].drop(data["S1"].index[12])
    actual = FactorEngine().compute_matrix(data, factor)
    np.testing.assert_allclose(actual, expected(data, factor.spec), atol=2e-10, equal_nan=True)
    assert actual.notna().any().any()
    prefix = {s: f.loc[: actual.index[210]] for s, f in data.items()}
    pd.testing.assert_frame_equal(FactorEngine().compute_matrix(prefix, factor), actual.iloc[:211])
    reverse = FactorEngine().compute_matrix(dict(reversed(list(data.items()))), factor)
    pd.testing.assert_frame_equal(reverse[actual.columns], actual)


@pytest.mark.parametrize("n", NUMBERS)
def test_third_missing_invalid_constant_and_zero_volume(n):
    factor = configure_factor(name(n), parameters(n, True))
    data = pool(45)
    baseline = FactorEngine().compute_matrix(data, factor)
    for field in factor.inputs:
        for value in (np.nan, np.inf, -1, 0):
            modified = copy.deepcopy(data)
            modified["S0"] = modified["S0"].astype(float)
            modified["S0"].loc[modified["S0"].index[10], field] = value
            actual = FactorEngine().compute_matrix(modified, factor)
            np.testing.assert_allclose(
                actual, expected(modified, factor.spec), atol=2e-10, equal_nan=True
            )
            if field != "volume" or value != 0:
                assert actual.iloc[10 : 10 + factor.spec.warmup, 0].isna().all()
            pd.testing.assert_frame_equal(actual.iloc[30:], baseline.iloc[30:])
    constant = {s: f * 0 + 10 for s, f in data.items()}
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(constant, factor),
        expected(constant, factor.spec),
        equal_nan=True,
    )
    if "volume" in factor.inputs:
        for f in data.values():
            f["volume"] = 0.0
        np.testing.assert_allclose(
            FactorEngine().compute_matrix(data, factor), expected(data, factor.spec), equal_nan=True
        )


@pytest.mark.parametrize("n", NUMBERS)
def test_third_metadata_parameters_scope_and_isolation(n):
    cls = get_factor(name(n))
    before = describe_factor(cls)
    defaults = dict(SPECS[n].reference_parameters)
    assert before["resolved_parameters"] == defaults
    assert {k: p["default"] for k, p in before["parameters"].items()} == defaults
    assert before["release_status"] == "local_validation_only_pending_license_review"
    assert before["alias_of"] == (f"gtja191_{ALIASES[n]:03d}" if n in ALIASES else None)
    factor = configure_factor(name(n), parameters(n, True))
    if parameters(n, True) != defaults:
        assert (
            describe_factor(cls, parameters(n, True))["formula_sha256"] != before["formula_sha256"]
        )
    for key in defaults:
        for bad in (True, None, -1, 0.5, np.nan, np.inf, 1001):
            with pytest.raises(ValueError):
                configure_factor(name(n), {key: bad})
    with pytest.raises(ValueError):
        configure_factor(name(n), {"unknown": 1})
    data = pool(40)
    original = copy.deepcopy(data)
    FactorEngine().compute_matrix(data, factor)
    for s in data:
        pd.testing.assert_frame_equal(data[s], original[s])
    assert describe_factor(cls) == before
    if n != 35:
        with pytest.raises(ValueError, match="股票池"):
            cls().compute(data["S0"])
        single = FactorPanel.build({"S0": data["S0"]}, cls.inputs)
        assert cls().compute_panel(single).isna().all().all()


def test_third_aliases_and_distinct_body_std_defaults():
    for n, ref in ALIASES.items():
        with pytest.raises(ValueError, match="重复"):
            configured_selection([name(n), f"gtja191_{ref:03d}"])
    configured_selection([name(18), "gtja191_054"])
    with pytest.raises(ValueError, match="重复"):
        configured_selection([name(18), "gtja191_054"], {name(18): {"body_std": 10}})
    with pytest.raises(ValueError, match="重复"):
        configured_selection([name(18), "gtja191_054"], {"gtja191_054": {"body_std": 5}})
    meta = describe_factor(get_factor(name(18)))
    assert "原表STD未写窗口" not in meta["formula"]
    assert "原文省略" not in meta["parameters"]["body_std"]["label"]
    assert meta["warmup_bars"] == 10
    f = configure_factor(name(37), {"lag": 1, "corr": 2})
    assert f.spec.warmup == 3
    with pytest.raises(ValueError, match="600"):
        configure_factor(name(37), {"lag": 400, "corr": 400})


def test_third_014_correlation_not_covariance_and_scale():
    data = pool(35)
    factor = get_factor(name(14))()
    actual = FactorEngine().compute_matrix(data, factor)
    assert actual.abs().max().max() <= 1
    scaled = copy.deepcopy(data)
    for f in scaled.values():
        f["volume"] *= 1000
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(scaled, factor), actual, equal_nan=True, atol=1e-11
    )
    meta = describe_factor(type(factor))
    assert "mcovar" in meta["reference_differences"][0]


@pytest.mark.parametrize("n", NUMBERS)
def test_third_frozen_ten_stocks_and_minute(n):
    root = Path(__file__).parents[1] / "fixtures/factor_vwap_long"
    data = {
        p.stem: long_frozen(p.name).set_index("datetime")
        for p in sorted(root.glob("*-DAILY-NONE.json"))
    }
    factor = get_factor(name(n))()
    actual = FactorEngine().compute_matrix(data, factor)
    np.testing.assert_allclose(actual, expected(data, factor.spec), equal_nan=True, atol=2e-10)
    assert actual.notna().any().any()
    minute = long_frozen("0-300750-MIN_30-NONE.json").set_index("datetime")
    if n == 35:
        np.testing.assert_allclose(
            factor.compute(minute), series_oracle(minute, factor.spec), equal_nan=True
        )
    else:
        assert (
            factor.compute_panel(FactorPanel.build({"real": minute}, factor.inputs))
            .isna()
            .all()
            .all()
        )


@pytest.mark.parametrize("n", NUMBERS)
@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_third_real_adjustments(n, adjust):
    files = [f for f in FILES if f.endswith(f"-DAILY-{adjust}.json")]
    data = {
        f: qualify_factor_fields(frozen(f), frozen(f.replace(adjust, "NONE"))).set_index("datetime")
        for f in files
    }
    factor = configure_factor(name(n), parameters(n, True))
    actual = FactorEngine().compute_matrix(data, factor)
    np.testing.assert_allclose(actual, expected(data, factor.spec), equal_nan=True, atol=2e-10)
    if n == 15:
        # These three real tapes retain the same cross-sectional high-price
        # ordering throughout. Correlation of that constant rank is undefined.
        highs = pd.DataFrame({s: f.high for s, f in data.items()})
        assert highs.rank(axis=1).nunique().eq(1).all()
        assert actual.isna().all().all()
    else:
        assert actual.notna().any().any()


@pytest.mark.asyncio
@pytest.mark.parametrize("n", NUMBERS)
async def test_third_frozen_archive_readonly_recompute(monkeypatch, n):
    frame = long_frozen("0-000001-DAILY-NONE.json").iloc[-80:]
    if n == 35:
        req = research.FactorComputeRequest(
            market="SZ",
            code="000001",
            count=80,
            adjust="NONE",
            factors=[name(n)],
            factor_parameters={name(n): parameters(n, True)},
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
            factor_parameters={name(n): parameters(n, True)},
        )
        result = (await research.factor_evaluate(req, None, None)).data
        mode = "evaluation"
    assert not result["errors"]
    original = {
        "format": "factor-research-v1",
        "mode": mode,
        "title": "Alpha third local",
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


def test_third_cancellation_is_not_success(monkeypatch):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import alpha101

    def cancel():
        raise ComputationStopped("cancelled")

    monkeypatch.setattr(alpha101, "computation_checkpoint", cancel)
    for n in NUMBERS:
        with pytest.raises(ComputationStopped):
            FactorEngine().compute_matrix(pool(20), get_factor(name(n))())
