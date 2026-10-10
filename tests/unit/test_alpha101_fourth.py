"""Independent window-slice oracles for compound Alpha101 formulas."""

import copy
import math
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.builtin.alpha101 import Alpha101Factor, Alpha101PanelFactor
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.factor.panel import FactorPanel
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_alpha101 import corr, name, percentile
from tests.unit.test_alpha101_third import pool
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import FILES, frozen
from tests.unit.test_gtja191_vwap import long_frozen

NUMBERS = (8, 19, 26, 30, 34, 45)
CUSTOM = {
    8: {"sum": 3, "lag": 2},
    19: {"lag": 3, "returns": 7},
    26: {"rank": 3, "corr": 3, "max": 2},
    30: {"direction": 2, "short": 3, "long": 7},
    34: {"short": 3, "long": 7, "lag": 2},
    45: {"lag": 2, "mean": 3, "corr": 3, "short": 3, "long": 7},
}


def fraction(value):
    return Fraction(str(value))


def rank(row):
    # Independent count-of-less/count-of-equal, not production sorted groups.
    good = [v for v in row if v is not None]
    return [
        Fraction(2 * sum(x < v for x in good) + sum(x == v for x in good) + 1, 2 * len(good))
        if v is not None and len(good) >= 2
        else None
        for v in row
    ]


def series_oracle(frame, spec):
    p = spec.resolved_parameters
    out = pd.Series(np.nan, index=frame.index)
    for end in range(spec.warmup - 1, len(frame)):
        block = frame.iloc[end + 1 - spec.warmup : end + 1]
        if (
            not np.isfinite(block[list(spec.inputs)]).all().all()
            or not block.high.gt(0).all()
            or not block.volume.ge(0).all()
        ):
            continue
        values = []
        for t in range(end - p["max"] + 1, end + 1):
            pairs = []
            for k in ("volume", "high"):
                seq = []
                for j in range(t - p["corr"] + 1, t + 1):
                    window = frame[k].iloc[j - p["rank"] + 1 : j + 1].tolist()
                    seq.append(percentile(window, window[-1]))
                pairs.append(seq)
            values.append(corr(*pairs))
        if all(math.isfinite(v) for v in values):
            out.iloc[end] = -max(values)
    return out


def panel_oracle(frames, spec):
    if spec.number == 45:
        from tests.unit.test_gtja191_panel_compound import independent

        data = {s: f.rename_axis("datetime").reset_index() for s, f in frames.items()}
        values = independent(data, 113, dict(spec.reference_parameters))
        dates = sorted(set().union(*(set(f.index) for f in frames.values())))
        return pd.DataFrame(values, index=pd.DatetimeIndex(dates), columns=list(frames))
    dates = sorted(set().union(*(set(f.index) for f in frames.values())))
    first, second, weights = ([[None] * len(frames) for _ in dates] for _ in range(3))
    p, n = spec.resolved_parameters, spec.number
    for j, frame in enumerate(frames.values()):
        aligned = frame.reindex(dates)
        for end in range(spec.warmup - 1, len(dates)):
            block = aligned.iloc[end + 1 - spec.warmup : end + 1][list(spec.inputs)]
            if not np.isfinite(block).all().all():
                continue
            if any(
                not (block[k].ge(0) if k == "volume" else block[k].gt(0)).all() for k in spec.inputs
            ):
                continue

            def close(i):
                return fraction(aligned.close.iloc[i])

            def returns(t, length):
                return [close(i) / close(i - 1) - 1 for i in range(t - length + 1, t + 1)]

            def total(field, t, length):
                return sum(fraction(v) for v in aligned[field].iloc[t - length + 1 : t + 1])

            if n == 8:

                def value(t):
                    return total("open", t, p["sum"]) * sum(returns(t, p["sum"]))

                first[end][j] = value(end) - value(end - p["lag"])
            elif n == 19:
                first[end][j] = 1 + sum(returns(end, p["returns"]))
                delta = 2 * (close(end) - close(end - p["lag"]))
                weights[end][j] = -int(delta > 0) + int(delta < 0)
            elif n == 30:
                first[end][j] = sum(
                    int(close(i) > close(i - 1)) - int(close(i) < close(i - 1))
                    for i in range(end - p["direction"] + 1, end + 1)
                )
                denominator = total("volume", end, p["long"])
                if denominator:
                    weights[end][j] = total("volume", end, p["short"]) / denominator
            else:

                def variance(length):
                    values = returns(end, length)
                    mean = sum(values) / length
                    return sum((v - mean) ** 2 for v in values) / (length - 1)

                denominator = variance(p["long"])
                if denominator:
                    first[end][j] = variance(p["short"]) / denominator
                second[end][j] = close(end) - close(end - p["lag"])
    output = np.full((len(dates), len(frames)), np.nan)
    for i, row in enumerate(first):
        ranked = rank(row)
        if n == 34:
            other = rank(second[i])
            ranked = rank(
                [
                    2 - a - b if a is not None and b is not None else None
                    for a, b in zip(ranked, other)
                ]
            )
        for j, value in enumerate(ranked):
            if value is None:
                continue
            if n == 8:
                value = -value
            elif n in {19, 30}:
                if weights[i][j] is None:
                    continue
                value = weights[i][j] * (1 + value if n == 19 else 1 - value)
            output[i, j] = float(value)
    return pd.DataFrame(output, index=pd.DatetimeIndex(dates), columns=list(frames))


def expected(frames, spec):
    if spec.number == 26:
        return pd.DataFrame({s: series_oracle(f, spec) for s, f in frames.items()})
    return panel_oracle(frames, spec)


@pytest.mark.parametrize("n", NUMBERS)
@pytest.mark.parametrize("custom", [False, True])
def test_fourth_default_custom_independent_prefix_permutation(n, custom):
    factor = configure_factor(name(n), CUSTOM[n] if custom else {})
    data = pool(270 if n == 19 and not custom else 60)
    data["S1"] = data["S1"].drop(data["S1"].index[7])
    actual = FactorEngine().compute_matrix(data, factor)
    np.testing.assert_allclose(actual, expected(data, factor.spec), equal_nan=True, atol=1e-11)
    assert actual.notna().any().any()
    cutoff = actual.index[-5]
    prefix = {s: f.loc[:cutoff] for s, f in data.items()}
    pd.testing.assert_frame_equal(
        FactorEngine().compute_matrix(prefix, factor), actual.loc[:cutoff]
    )
    reverse = FactorEngine().compute_matrix(dict(reversed(list(data.items()))), factor)
    pd.testing.assert_frame_equal(reverse[actual.columns], actual)


@pytest.mark.parametrize("n", NUMBERS)
def test_fourth_missing_invalid_constant_and_zero(n):
    factor = configure_factor(name(n), CUSTOM[n])
    data = pool(35)
    baseline = FactorEngine().compute_matrix(data, factor)
    for key in factor.inputs:
        for bad in (np.nan, np.inf, -1, 0):
            changed = copy.deepcopy(data)
            changed["S0"] = changed["S0"].astype(float)
            changed["S0"].loc[changed["S0"].index[10], key] = bad
            out = FactorEngine().compute_matrix(changed, factor)
            np.testing.assert_allclose(
                out, expected(changed, factor.spec), equal_nan=True, atol=1e-11
            )
            if key != "volume" or bad != 0:
                assert out.iloc[10 : 10 + factor.spec.warmup, 0].isna().all()
            pd.testing.assert_frame_equal(out.iloc[25:], baseline.iloc[25:])
    same = {s: f * 0 + 10 for s, f in data.items()}
    np.testing.assert_allclose(
        FactorEngine().compute_matrix(same, factor),
        expected(same, factor.spec),
        equal_nan=True,
        atol=1e-11,
    )
    if "volume" in factor.inputs:
        for f in data.values():
            f["volume"] = 0.0
        np.testing.assert_allclose(
            FactorEngine().compute_matrix(data, factor),
            expected(data, factor.spec),
            equal_nan=True,
            atol=1e-11,
        )


@pytest.mark.parametrize("n", NUMBERS)
def test_fourth_metadata_limits_empty_scope_and_no_mutation(n):
    cls = get_factor(name(n))
    meta = describe_factor(cls)
    factor = configure_factor(name(n), CUSTOM[n])
    params = describe_factor(cls, CUSTOM[n])
    assert params["resolved_parameters"] == CUSTOM[n]
    assert params["formula_sha256"] != meta["formula_sha256"]
    assert meta["release_status"] == "local_validation_only_pending_license_review"
    if n != 45:
        assert meta["warmup_limit"] == 600
        assert params["warmup_bars"] == max(
            t["offset"] + sum(CUSTOM[n][k] for k in t["windows"]) for t in params["warmup_terms"]
        )
    for key in CUSTOM[n]:
        for bad in (True, None, 0, -1, 1.5, meta["parameters"][key]["max"] + 1, np.inf):
            with pytest.raises(ValueError):
                configure_factor(name(n), {key: bad})
    with pytest.raises(ValueError):
        configure_factor(name(n), {"unknown": 1})
    if n in {30, 34, 45}:
        with pytest.raises(ValueError, match="短窗口"):
            configure_factor(name(n), {"short": 10, "long": 10})
    frames = pool(20)
    original = copy.deepcopy(frames)
    FactorEngine().compute_matrix(frames, factor)
    for s in frames:
        pd.testing.assert_frame_equal(frames[s], original[s])
    assert describe_factor(cls) == meta
    if n == 26:
        assert factor.compute(frames["S0"].iloc[:0]).empty
    else:
        with pytest.raises(ValueError, match="股票池"):
            factor.compute(frames["S0"])
        assert (
            factor.compute_panel(FactorPanel.build({"S0": frames["S0"]}, factor.inputs))
            .isna()
            .all()
            .all()
        )


def test_fourth_exact_nested_ties_extreme_scale_and_boundaries():
    # Three proportional price paths: variance ratios remain tied exactly,
    # price differences do not. Scale must not create false volatility ranks.
    dates = pd.date_range("2025-01-01", periods=6)
    frames = {
        str(i): pd.DataFrame({"close": np.array([10, 12, 9, 11, 13, 12]) * i}, index=dates)
        for i in (1, 2, 3)
    }
    factor = configure_factor(name(34), {"short": 2, "long": 3, "lag": 1})
    out = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(out, expected(frames, factor.spec), equal_nan=True)
    np.testing.assert_allclose(out.iloc[-1], [1 / 3, 2 / 3, 1.0])
    for scale in (1e-150, 1e150):
        scaled = {s: f * scale for s, f in frames.items()}
        np.testing.assert_allclose(
            FactorEngine().compute_matrix(scaled, factor),
            expected(scaled, factor.spec),
            equal_nan=True,
        )
    for n in (8, 26):
        keys = {k: 400 for k in CUSTOM[n]}
        with pytest.raises(ValueError, match="600"):
            configure_factor(name(n), keys)
    assert get_factor(name(19))().spec.warmup == 251
    assert get_factor(name(26))().spec.warmup == 11
    assert get_factor(name(30))().spec.warmup == 20
    assert get_factor(name(34))().spec.warmup == 6
    with pytest.raises(ValueError, match="重复"):
        configured_selection([name(45), "gtja191_113"])


def test_fourth_nested_ties_and_volume_sum_overflow():
    # Volatility ratios rise strictly, price deltas fall strictly. The two
    # ranks add to 7/6 for every security, so ALL outer ranks must be 7/12.
    paths = [
        (12, 7, 7, 12),
        (11, 8, 8, 12),
        (10, 8, 8, 11),
        (12, 8, 7, 9),
        (7, 9, 11, 12),
        (10, 12, 7, 7),
    ]
    dates = pd.date_range("2025-01-01", periods=4)
    frames = {str(i): pd.DataFrame({"close": p}, index=dates) for i, p in enumerate(paths)}
    factor = configure_factor(name(34), {"short": 2, "long": 3, "lag": 1})
    actual = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(actual.iloc[-1], [7 / 12] * 6, rtol=0, atol=0)
    np.testing.assert_allclose(actual, expected(frames, factor.spec), equal_nan=True)
    frames = pool(12)
    for f in frames.values():
        f["close"] = 10.0
        f["volume"] = 1e308
    factor = configure_factor(name(30), CUSTOM[30])
    actual = FactorEngine().compute_matrix(frames, factor)
    np.testing.assert_allclose(actual.iloc[-1], [9 / 56] * 4)
    np.testing.assert_allclose(actual, expected(frames, factor.spec), equal_nan=True)


@pytest.mark.parametrize("n", NUMBERS)
def test_fourth_frozen_pool_and_minute(n):
    root = Path(__file__).parents[1] / "fixtures/factor_vwap_long"
    data = {
        p.stem: long_frozen(p.name).set_index("datetime")
        for p in sorted(root.glob("*-DAILY-NONE.json"))
    }
    factor = get_factor(name(n))()
    actual = FactorEngine().compute_matrix(data, factor)
    np.testing.assert_allclose(actual, expected(data, factor.spec), equal_nan=True, atol=1e-11)
    assert actual.notna().any().any()
    minute = long_frozen("0-300750-MIN_30-NONE.json").set_index("datetime")
    if n == 26:
        np.testing.assert_allclose(
            factor.compute(minute), series_oracle(minute, factor.spec), equal_nan=True, atol=1e-11
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
def test_fourth_real_adjustments(n, adjust):
    paths = [f for f in FILES if f.endswith(f"-DAILY-{adjust}.json")]
    data = {
        f: qualify_factor_fields(frozen(f), frozen(f.replace(adjust, "NONE"))).set_index("datetime")
        for f in paths
    }
    factor = configure_factor(name(n), CUSTOM[n])
    actual = FactorEngine().compute_matrix(data, factor)
    np.testing.assert_allclose(actual, expected(data, factor.spec), equal_nan=True, atol=1e-11)
    assert actual.notna().any().any()


@pytest.mark.asyncio
@pytest.mark.parametrize("n", NUMBERS)
async def test_fourth_frozen_archive_readonly_recompute(monkeypatch, n):
    frame = long_frozen("0-000001-DAILY-NONE.json").iloc[-80:]
    if n == 26:
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
        "title": "Alpha fourth local",
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


def test_fourth_midway_cancel_and_compound_source_fingerprint(monkeypatch):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor import catalog
    from easy_tdx.factor.builtin import alpha101_compound

    original = catalog.inspect.getsource
    before = describe_factor(get_factor(name(34)))["formula_sha256"]
    monkeypatch.setattr(
        catalog.inspect,
        "getsource",
        lambda obj: original(obj) + ("\n# changed kernel" if obj is alpha101_compound else ""),
    )
    assert describe_factor(get_factor(name(34)))["formula_sha256"] != before
    calls = 0

    def stop():
        nonlocal calls
        calls += 1
        if calls == 12:
            raise ComputationStopped("cancelled during rational accumulation")

    monkeypatch.setattr(alpha101_compound, "computation_checkpoint", stop)
    with pytest.raises(ComputationStopped):
        FactorEngine().compute_matrix(pool(100), get_factor(name(19))())
    assert calls == 12
