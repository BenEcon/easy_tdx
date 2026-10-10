"""Independent rational price oracle plus previously independent GTJA oracles.

Never generate expectations by calling the reused production kernel.
"""

import copy
from fractions import Fraction
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
from tests.unit.test_alpha101 import name, percentile, pool, sample
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import frozen
from tests.unit.test_gtja191_vwap import long_frozen

NUMBERS = (2, 10, 13, 16, 22, 33, 38, 40, 44, 46, 49, 51, 54)
SERIES = (46, 49, 51, 54)
PANEL = tuple(n for n in NUMBERS if n not in SERIES)
ALIASES = {3: 105, 13: 99, 16: 83, 22: 104, 40: 42, 44: 62, 46: 86}


def frac(value):
    return Fraction(str(value))


def series_oracle(frame, spec):
    n = spec.number
    w = dict(spec.reference_parameters).get("window", spec.window or 1)
    out = np.full(len(frame), np.nan)
    for i in range(spec.warmup - 1, len(frame)):
        block = frame.iloc[i + 1 - spec.warmup : i + 1][list(spec.inputs)]
        if not np.isfinite(block).all().all() or not block.gt(0).all().all():
            continue
        if n == 54:
            o, c, h, low = [frac(frame.iloc[i][k]) for k in ("open", "close", "high", "low")]
            if low == h or max(o, c, low) > h or min(o, c, h) < low:
                continue
            value = (c - low) * o**5 / ((low - h) * c**5)
        else:
            a, b, previous, c = [frac(frame.close.iloc[j]) for j in (i - 2 * w, i - w, i - 1, i)]
            curvature = ((a - b) - (b - c)) / w
            if n == 46:
                value = -1 if curvature > frac(0.25) else 1 if curvature < 0 else previous - c
            else:
                value = 1 if curvature < frac(spec.threshold) else previous - c
        try:
            out[i] = float(value)
        except OverflowError:
            pass
    return pd.Series(out, index=frame.index)


def panel_oracle(frames, spec):
    if spec.reference is not None:
        from tests.unit.test_gtja191_panel_compound import independent

        data = {s: f.rename_axis("datetime").reset_index() for s, f in frames.items()}
        result = independent(data, spec.reference, dict(spec.reference_parameters))
        dates = sorted(set().union(*(set(f.index) for f in frames.values())))
        return pd.DataFrame(result, index=pd.DatetimeIndex(dates), columns=list(frames))
    dates = sorted(set().union(*(set(f.index) for f in frames.values())))
    width = len(frames)
    raw = np.full((len(dates), width), np.nan, dtype=object)
    ratios = raw.copy()
    for j, f in enumerate(frames.values()):
        aligned = f.reindex(dates)
        for i in range(spec.warmup - 1, len(dates)):
            block = aligned.iloc[i + 1 - spec.warmup : i + 1][list(spec.inputs)]
            if not np.isfinite(block).all().all() or not block.gt(0).all().all():
                continue
            c = frac(aligned.close.iloc[i])
            if spec.number == 10:
                values = [frac(v) for v in block.close]
                deltas = [b - a for a, b in zip(values, values[1:])]
                raw[i, j] = float(deltas[-1] if min(deltas) > 0 or max(deltas) < 0 else -deltas[-1])
            elif spec.number == 33:
                raw[i, j] = frac(aligned.open.iloc[i]) / c - 1
            else:
                raw[i, j] = percentile(block.close.tolist(), float(c))
                ratios[i, j] = c / frac(aligned.open.iloc[i])

    def rank(values):
        out = np.full(values.shape, np.nan)
        for i, row in enumerate(values):
            valid = [v for v in row if isinstance(v, Fraction) or np.isfinite(v)]
            if len(valid) >= 2:
                for j, v in enumerate(row):
                    if isinstance(v, Fraction) or np.isfinite(v):
                        out[i, j] = (
                            sum(x < v for x in valid) + (sum(x == v for x in valid) + 1) / 2
                        ) / len(valid)
        return out

    result = rank(raw)
    if spec.number == 38:
        result = -result * rank(ratios)
    return pd.DataFrame(result, index=pd.DatetimeIndex(dates), columns=list(frames))


def params(n, custom):
    if not custom:
        return {}
    spec = SPECS[n]
    if spec.reference is not None:
        return {key: 3 for key, _ in spec.reference_parameters}
    result = {"window": 3} if spec.window is not None else {}
    if spec.threshold is not None:
        result["threshold"] = -0.075
    return result


@pytest.mark.parametrize("n", NUMBERS)
@pytest.mark.parametrize("custom", [False, True])
def test_second_default_custom_independent_prefix_permutation(n, custom):
    factor = configure_factor(name(n), params(n, custom))
    if n in PANEL:
        frames = pool()
        f = frames["SZ:000002"]
        frames["SZ:000002"] = f.drop(f.index[30])
        actual = FactorEngine().compute_matrix(frames, factor)
        expected = panel_oracle(frames, factor.spec)
        np.testing.assert_allclose(actual, expected, atol=1e-11, equal_nan=True)
        before = FactorEngine().compute_matrix(
            {s: f.loc[: actual.index[40]] for s, f in frames.items()}, factor
        )
        pd.testing.assert_frame_equal(before, actual.iloc[:41])
        reverse = FactorEngine().compute_matrix(dict(reversed(list(frames.items()))), factor)
        pd.testing.assert_frame_equal(reverse[actual.columns], actual)
    else:
        f = sample()
        actual = factor.compute(f)
        np.testing.assert_allclose(
            actual, series_oracle(f, factor.spec), atol=1e-12, equal_nan=True
        )
        pd.testing.assert_series_equal(factor.compute(f.iloc[:40]), actual.iloc[:40])


@pytest.mark.parametrize("n", NUMBERS)
def test_second_every_input_missing_invalid_constant_and_recovery(n):
    factor = get_factor(name(n))()
    frames = pool()
    baseline = FactorEngine().compute_matrix(frames, factor)
    for key in factor.inputs:
        for bad in (np.nan, np.inf, -1, 0):
            if key == "volume" and bad == 0:
                continue
            data = copy.deepcopy(frames)
            data["SZ:000001"] = data["SZ:000001"].astype(float)
            data["SZ:000001"].loc[data["SZ:000001"].index[30], key] = bad
            actual = FactorEngine().compute_matrix(data, factor)
            expected = (
                panel_oracle(data, factor.spec)
                if n in PANEL
                else pd.DataFrame({s: series_oracle(f, factor.spec) for s, f in data.items()})
            )
            np.testing.assert_allclose(actual, expected, atol=1e-11, equal_nan=True)
            assert actual.iloc[30 : 30 + factor.spec.warmup, 0].isna().all()
            np.testing.assert_allclose(
                actual.iloc[30 + factor.spec.warmup :],
                baseline.iloc[30 + factor.spec.warmup :],
                atol=1e-11,
                equal_nan=True,
            )
    constant = {s: f * 0 + 10 for s, f in frames.items()}
    actual = FactorEngine().compute_matrix(constant, factor)
    expected = (
        panel_oracle(constant, factor.spec)
        if n in PANEL
        else pd.DataFrame({s: series_oracle(f, factor.spec) for s, f in constant.items()})
    )
    np.testing.assert_allclose(actual, expected, atol=1e-12, equal_nan=True)
    # Empty/short inputs remain empty/undefined, never fabricate warmup values.
    if n in SERIES:
        assert factor.compute(sample().iloc[:0]).empty
        assert factor.compute(sample().iloc[: factor.spec.warmup - 1]).isna().all()
    else:
        with pytest.raises(ValueError, match="至少需要"):
            FactorEngine().compute_matrix({"a": sample()}, factor)
        one = factor.compute_panel(FactorPanel.build({"a": sample()}, factor.inputs))
        assert one.isna().all().all()


@pytest.mark.parametrize("n", NUMBERS)
def test_second_metadata_validation_identity_and_no_mutation(n):
    cls = get_factor(name(n))
    default = cls.spec
    custom = params(n, True)
    d = describe_factor(cls, custom)
    assert d["release_status"] == "local_validation_only_pending_license_review"
    assert d["warmup_bars"] == max(
        t["offset"] + sum(d["resolved_parameters"][k] for k in t["windows"])
        for t in d["warmup_terms"]
    )
    assert d["available"] == (n in SERIES)
    assert cls.spec == default
    if custom:
        assert describe_factor(cls)["formula_sha256"] != d["formula_sha256"]
    for key in d["parameters"]:
        for value in (True, None, float("nan"), float("inf"), -1000, 1001):
            with pytest.raises(ValueError):
                configure_factor(name(n), {key: value})
    with pytest.raises(ValueError):
        configure_factor(name(n), {"unknown": 2})
    f = sample()
    before = f.copy(deep=True)
    FactorEngine().compute_matrix({"a": f, "b": f}, cls())
    pd.testing.assert_frame_equal(f, before)


@pytest.mark.parametrize("n", SERIES)
@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_second_real_three_adjustments(n, adjust):
    raw = frozen("0-000001-DAILY-NONE.json")
    frame = qualify_factor_fields(frozen(f"0-000001-DAILY-{adjust}.json"), raw)
    factor = get_factor(name(n))()
    np.testing.assert_allclose(
        factor.compute(frame),
        series_oracle(frame, factor.spec),
        rtol=1e-10,
        atol=1e-12,
        equal_nan=True,
    )


@pytest.mark.parametrize("n", NUMBERS)
def test_second_real_pool_and_minute(n):
    factor = get_factor(name(n))()
    root = Path(__file__).parents[1] / "fixtures/factor_vwap_long"
    frames = {
        p.stem: long_frozen(p.name).set_index("datetime")
        for p in sorted(root.glob("*-DAILY-NONE.json"))
    }
    actual = FactorEngine().compute_matrix(frames, factor)
    expected = (
        panel_oracle(frames, factor.spec)
        if n in PANEL
        else pd.DataFrame({s: series_oracle(f, factor.spec) for s, f in frames.items()})
    )
    np.testing.assert_allclose(actual, expected, atol=1e-11, equal_nan=True)
    frame = long_frozen("0-300750-MIN_30-NONE.json").set_index("datetime")
    if n in PANEL:
        assert (
            factor.compute_panel(FactorPanel.build({"a": frame}, factor.inputs)).isna().all().all()
        )
    else:
        np.testing.assert_allclose(
            factor.compute(frame), series_oracle(frame, factor.spec), atol=1e-12, equal_nan=True
        )


def test_second_alias_reuse_and_parameter_duplicates():
    for a, g in ALIASES.items():
        alpha, gtja = name(a), f"gtja191_{g:03d}"
        assert describe_factor(get_factor(alpha))["alias_of"] == gtja
        with pytest.raises(ValueError, match="重复"):
            configured_selection([alpha, gtja])
        if a != 3:
            frames = pool()
            pd.testing.assert_frame_equal(
                FactorEngine().compute_matrix(frames, get_factor(alpha)()),
                FactorEngine().compute_matrix(frames, get_factor(gtja)()),
            )
    configured_selection([name(2), "gtja191_001"])
    with pytest.raises(ValueError, match="重复"):
        configured_selection([name(2), "gtja191_001"], {name(2): {"lag": 1}})
    configured_selection([name(49), name(51)])
    with pytest.raises(ValueError, match="重复"):
        configured_selection([name(49), name(51)], {name(49): {"threshold": -0.05}})
    with pytest.raises(ValueError, match="600"):
        configure_factor(name(49), {"window": 300})
    configured_selection([name(3), "gtja191_105"], {name(3): {"window": 7}})


def test_second_hand_thresholds_ties_zero_volume_and_scale():
    for n, threshold in ((49, -0.1), (51, -0.05)):
        f = pd.DataFrame({"close": [10.0, 10.0, 10 + threshold]})
        factor = configure_factor(name(n), {"window": 1})
        assert factor.compute(f).iloc[-1] == pytest.approx(-threshold)  # equality is not '<'
        f.iloc[-1, 0] -= 0.00001
        assert factor.compute(f).iloc[-1] == 1
    f = sample(10)
    for scale in (1e-150, 1e150):
        np.testing.assert_allclose(
            get_factor(name(54))().compute(f * scale), get_factor(name(54))().compute(f), atol=1e-12
        )
    f.loc[:, "low"] = f.high
    assert get_factor(name(54))().compute(f).isna().all()
    # Exact decimal price differences must remain tied across different levels.
    frames = {
        "a": pd.DataFrame({"close": [10.0, 10.1]}, index=pd.date_range("2025-01-01", periods=2)),
        "b": pd.DataFrame({"close": [20.0, 20.1]}, index=pd.date_range("2025-01-01", periods=2)),
    }
    actual = FactorEngine().compute_matrix(frames, configure_factor(name(10), {"window": 1}))
    np.testing.assert_allclose(actual.iloc[-1], [0.75, 0.75])
    frames = pool()
    for f in frames.values():
        f.loc[:, "volume"] = 0
    assert FactorEngine().compute_matrix(frames, get_factor(name(2))()).isna().all().all()


@pytest.mark.asyncio
@pytest.mark.parametrize("n", NUMBERS)
async def test_second_frozen_archive_readonly_recompute(monkeypatch, n):
    frame = long_frozen("0-000001-DAILY-NONE.json").iloc[-80:]
    if n in SERIES:
        req = research.FactorComputeRequest(
            market="SZ",
            code="000001",
            count=80,
            adjust="NONE",
            factors=[name(n)],
            factor_parameters={name(n): params(n, True)},
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
            factor_parameters={name(n): params(n, True)},
        )
        result = (await research.factor_evaluate(req, None, None)).data
        mode = "evaluation"
    assert not result["errors"]
    original = {
        "format": "factor-research-v1",
        "mode": mode,
        "title": "Alpha second local",
        "savedAt": "2026-10-10T10:00:00Z",
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


def test_second_midway_cancellation(monkeypatch):
    from easy_tdx.factor.builtin import alpha101

    calls = 0

    def stop():
        nonlocal calls
        calls += 1
        if calls == 15:
            raise RuntimeError("cancel")

    monkeypatch.setattr(alpha101, "computation_checkpoint", stop)
    with pytest.raises(RuntimeError, match="cancel"):
        FactorEngine().compute_matrix(pool(), get_factor(name(10))())


def test_second_ratio_ranks_survive_overflow_and_close_ratios():
    frames = {
        "a": pd.DataFrame(
            {"open": [1e200], "close": [1e-200]}, index=pd.date_range("2025-01-01", periods=1)
        ),
        "b": pd.DataFrame(
            {"open": [2e200], "close": [1e-200]}, index=pd.date_range("2025-01-01", periods=1)
        ),
    }
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(frames, get_factor(name(33))()).iloc[0], [0.5, 1.0]
    )


def test_second_proportional_volume_and_return_ties_do_not_create_correlation():
    frames = pool()
    volumes = np.arange(80) ** 2 + 100.0
    for i, f in enumerate(frames.values()):
        f["volume"] = volumes * (i + 1)
    for identifier in (name(2), "gtja191_001"):
        assert FactorEngine().compute_matrix(frames, get_factor(identifier)()).isna().all().all()
    frames = pool()
    for i, f in enumerate(frames.values()):
        f["open"] = (np.arange(80) + 100.0) * (i + 1)
        f["close"] = f.open * 2
    for identifier in (name(2), "gtja191_001"):
        assert FactorEngine().compute_matrix(frames, get_factor(identifier)()).isna().all().all()
