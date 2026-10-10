"""Independent least-squares and orthogonal hand oracle; risks are synthetic."""

from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import get_factor
from easy_tdx.factor.builtin.risk_residuals import residual_energy
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.risk_inputs import attach_risk_inputs, freeze_risk_tape
from tests.unit.test_factor_risk_inputs import tape


def attach(frame, risks=None):
    frame = frame.copy(deep=True)
    if "datetime" not in frame:
        frame["datetime"] = frame.index
    frame["is_closed"] = True
    frame.attrs["snapshot_metadata"] = {
        **frame.attrs.get("snapshot_metadata", {}),
        "category": "DAY",
        "bar_time": "end",
        "actual_adjust": "QFQ",
    }
    if risks is None:
        t = np.arange(len(frame))
        risks = np.array([np.sin(t / 2), np.cos(t / 3), np.sin(t / 7)]).T / 100
    metadata = tape()["metadata"]
    metadata["vintage_at"] = "2030-01-01T15:00:00+08:00"
    rows = []
    for day, values in zip(pd.to_datetime(frame.datetime), risks):
        date = day.strftime("%Y-%m-%d")
        rows.append(
            {
                "date": date,
                "available_at": date + "T15:00:00+08:00",
                **{
                    k: float(v) if np.isfinite(v) else None
                    for k, v in zip(("mkt", "smb", "hml"), values)
                },
            }
        )
    return attach_risk_inputs(frame, freeze_risk_tape(metadata, rows))


def sample(n=120):
    t = np.arange(n)
    return attach(
        pd.DataFrame(
            {"close": 40 + np.sin(t / 4) + t / 30}, index=pd.date_range("2025-01-01", periods=n)
        )
    )


def independent(frame, regression=60, smoothing=20):
    close = frame.close.to_numpy(float)
    y = close[1:] / close[:-1] - 1
    y = np.insert(y, 0, np.nan)
    y[(close <= 0) | ~np.isfinite(close)] = np.nan
    y[1:][(close[:-1] <= 0) | ~np.isfinite(close[:-1])] = np.nan
    x = np.column_stack([np.ones(len(frame)), frame[["risk_mkt", "risk_smb", "risk_hml"]]])
    residuals = np.full(len(frame), np.nan)
    for end in range(regression, len(frame)):
        xx, yy = x[end - regression + 1 : end + 1], y[end - regression + 1 : end + 1]
        if not np.isfinite(xx).all() or not np.isfinite(yy).all():
            continue
        beta, _, rank, _ = np.linalg.lstsq(xx, yy, rcond=1e-12)
        if rank == 4:
            residuals[end] = (yy[-1] - xx[-1] @ beta) ** 2
    out = np.full(len(frame), np.nan)
    weights = np.array([0.9**age for age in range(smoothing)])
    for end in range(regression + smoothing - 1, len(frame)):
        window = residuals[end - smoothing + 1 : end + 1][::-1]
        if np.isfinite(window).all():
            out[end] = np.dot(window, weights) / sum(weights)
    return out


@pytest.mark.parametrize("regression,smoothing", [(60, 20), (5, 1), (8, 3), (20, 7)])
def test_risk_default_custom_independent_and_prefix(regression, smoothing):
    frame = sample()
    factor = get_factor("gtja191_030")(regression=regression, smoothing=smoothing)
    actual = factor.compute(frame)
    np.testing.assert_allclose(
        actual, independent(frame, regression, smoothing), rtol=1e-7, atol=1e-18
    )
    assert actual.first_valid_index() == frame.index[regression + smoothing - 1]
    for end in (79, 80, 100):
        prefix = frame.iloc[:end].drop(columns=["risk_mkt", "risk_smb", "risk_hml"]).copy()
        source = prefix.attrs.pop("factor_risk_inputs")["snapshot"]
        prefix = attach_risk_inputs(prefix, source)
        pd.testing.assert_series_equal(actual.iloc[:end], factor.compute(prefix))


def test_risk_hand_orthogonal_design():
    risks = np.array([[(-1) ** i, (-1) ** (i // 2), (-1) ** (i // 4)] for i in range(8)])
    closes = [100, 101, 103, 102, 99, 104, 102, 107, 105]
    frame = attach(
        pd.DataFrame({"close": closes}, index=pd.date_range("2025-01-01", periods=9)),
        np.vstack([risks[0], risks]),
    )
    returns = [Fraction(closes[i], closes[i - 1]) - 1 for i in range(1, 9)]
    fit = sum(returns) / 8
    for j in range(3):
        fit += sum(y * int(row[j]) for y, row in zip(returns, risks)) / 8 * int(risks[-1, j])
    expected = float((returns[-1] - fit) ** 2)
    actual = get_factor("gtja191_030")(regression=8, smoothing=1).compute(frame)
    assert actual.iloc[-1] == pytest.approx(expected, rel=1e-14)
    assert actual.iloc[:-1].isna().all()


def test_risk_gaps_rank_constant_and_recovery():
    frame = sample()
    risks = frame[["risk_mkt", "risk_smb", "risk_hml"]].to_numpy().copy()
    risks[35] = np.nan
    clean = frame.drop(columns=["risk_mkt", "risk_smb", "risk_hml"])
    clean.attrs.pop("factor_risk_inputs")
    broken = attach(clean, risks)
    factor = get_factor("gtja191_030")(regression=8, smoothing=3)
    actual = factor.compute(broken)
    np.testing.assert_allclose(actual, independent(broken, 8, 3), rtol=1e-8, atol=1e-18)
    assert actual.iloc[35:45].isna().all() and pd.notna(actual.iloc[45])
    flat = clean.copy()
    flat["close"] = 100
    assert factor.compute(attach(flat, risks)).dropna().eq(0).all()
    risks[:, 2] = risks[:, 1]
    assert factor.compute(attach(clean, risks)).isna().all()
    risks[60:, 2] = np.cos(np.arange(60) / 5) / 100
    recovered = factor.compute(attach(clean, risks))
    assert recovered.iloc[-10:].notna().all()


@pytest.mark.parametrize("scale", [1e-150, 1e150])
def test_risk_scaling_does_not_change_regression(scale):
    source = sample()
    baseline = residual_energy(source, 8, 3)
    source["close"] *= scale
    source[["risk_mkt", "risk_smb", "risk_hml"]] *= scale
    np.testing.assert_allclose(residual_energy(source, 8, 3), baseline, rtol=1e-8, atol=1e-18)


def test_risk_metadata_and_missing_data_are_not_false_availability():
    from easy_tdx.factor.catalog import availability_reason
    from easy_tdx.factor.configuration import configure_factor

    cls = get_factor("gtja191_030")
    d = describe_factor(cls)
    assert d["implemented"] and d["status"] == "needs_data"
    assert not d["available"] and not d["evaluation_available"]
    assert d["warmup_bars"] == 80 and d["supported_categories"] == ["DAY"]
    assert "MKT" in availability_reason(d, "QFQ")
    for params in (
        {"regression": 4},
        {"regression": True},
        {"smoothing": 0},
        {"regression": 590, "smoothing": 20},
    ):
        with pytest.raises(ValueError):
            configure_factor("gtja191_030", params)
    with pytest.raises(ValueError, match="数据包"):
        cls().compute(pd.DataFrame({"close": [1, 2, 3]}))


@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_risk_real_prices_synthetic_factors_oracle(adjust):
    from tests.unit.test_factor_data import frozen
    from tests.unit.test_gtja191_benchmark import real_equity

    raw = real_equity(frozen(f"0-000001-DAILY-{adjust}.json"))
    frame = attach(raw)
    frame.attrs["snapshot_metadata"]["actual_adjust"] = adjust
    np.testing.assert_allclose(
        get_factor("gtja191_030")().compute(frame), independent(frame), rtol=1e-9, atol=1e-18
    )


def test_risk_cancellation(monkeypatch):
    import easy_tdx.factor.builtin.risk_residuals as implementation

    calls = []

    def stop():
        calls.append(1)
        if len(calls) == 10:
            raise RuntimeError("cancelled")

    monkeypatch.setattr(implementation, "computation_checkpoint", stop)
    with pytest.raises(RuntimeError, match="cancelled"):
        residual_energy(sample(), 8, 3)
    assert len(calls) == 10


def test_risk_web_refuses_missing_source():
    from easy_tdx.web.routers.research import (
        FactorComputeRequest,
        FactorEvaluationRequest,
        _factor_result,
    )

    req = FactorComputeRequest(market="SZ", code="000001", factors=["gtja191_030"], count=160)
    result = _factor_result(req, sample()).data
    assert "MKT" in result["errors"]["gtja191_030"]
    assert not any(row.get("gtja191_030") is not None for row in result["rows"])
    with pytest.raises(ValueError, match="MKT"):
        FactorEvaluationRequest(
            stocks=[{"market": "SZ", "code": f"{i:06d}"} for i in range(5)], factors=["gtja191_030"]
        )


def test_risk_raw_snapshot_readonly_and_explicit_kernel_recompute(monkeypatch):
    import copy

    import easy_tdx.factor.builtin.risk_residuals as implementation
    from easy_tdx.factor.snapshot import freeze_input, restore_input

    frame = sample()
    factor = get_factor("gtja191_030")()
    expected = factor.compute(frame)
    saved = freeze_input("SZ:000001", frame)
    before = copy.deepcopy(saved)
    with monkeypatch.context() as guard:
        guard.setattr(
            implementation,
            "residual_energy",
            lambda *a, **k: pytest.fail("readonly must not compute"),
        )
        restored = restore_input(saved)
    pd.testing.assert_series_equal(factor.compute(restored), expected, check_freq=False)
    assert saved == before


@pytest.mark.parametrize("invalid", [0.0, -1.0, np.nan, np.inf])
def test_risk_invalid_close_rewarms_all_dependencies(invalid):
    data = sample()
    data.loc[data.index[30], "close"] = invalid
    result = residual_energy(data, 8, 3)
    assert result.iloc[30:41].isna().all()
    assert pd.notna(result.iloc[41])
    np.testing.assert_allclose(result, independent(data, 8, 3), rtol=1e-8, atol=1e-18)


def test_risk_ill_conditioned_not_silently_regularized():
    data = sample()
    data["risk_hml"] = data.risk_mkt + 1e-14 * data.risk_hml
    assert residual_energy(data, 8, 3).isna().all()
