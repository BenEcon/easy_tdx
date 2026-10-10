"""Independent scalar oracles and integration for the first local Alpha101 batch."""

import copy
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import get_factor, list_factors
from easy_tdx.factor.builtin.alpha101 import SPECS, Alpha101Factor, Alpha101PanelFactor
from easy_tdx.factor.configuration import configure_factor
from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.factor.panel import FactorPanel
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import frozen

FIRST = (3, 4, 6, 9, 12, 23, 53, 101)


def name(n):
    return f"alpha101_{n:03d}"


def sample(size=80):
    t = np.arange(size)
    close = 30 + np.sin(t / 3) + t / 40
    return pd.DataFrame(
        dict(
            open=close + np.cos(t / 7) / 3,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=1000 + (t * 137 % 1103),
        ),
        index=pd.date_range("2025-01-01", periods=size, freq="B"),
    )


def percentile(values, value):
    values = [v for v in values if math.isfinite(v)]
    if not math.isfinite(value) or not values:
        return math.nan
    return (sum(v < value for v in values) + (sum(v == value for v in values) + 1) / 2) / len(
        values
    )


def corr(a, b):
    if not all(math.isfinite(v) for v in [*a, *b]):
        return math.nan
    a = [v - math.fsum(a) / len(a) for v in a]
    b = [v - math.fsum(b) / len(b) for v in b]
    sa, sb = math.fsum(v * v for v in a), math.fsum(v * v for v in b)
    return math.fsum(x * y for x, y in zip(a, b)) / math.sqrt(sa * sb) if sa and sb else math.nan


def independent(frame, spec):
    if spec.number in {24, 41}:
        from tests.unit.test_alpha101_fifth import series_oracle

        return series_oracle(frame, spec)
    if spec.number == 26:
        from tests.unit.test_alpha101_fourth import series_oracle

        return series_oracle(frame, spec)
    if spec.number == 35:
        from tests.unit.test_alpha101_third import series_oracle

        return series_oracle(frame, spec)
    if spec.number not in FIRST:
        from tests.unit.test_alpha101_second import series_oracle

        return series_oracle(frame, spec)
    data = frame[list(spec.inputs)].to_numpy(float)
    cols = {key: frame[key].tolist() for key in spec.inputs}
    out = np.full(len(frame), np.nan)
    n, w = spec.number, spec.window or 1
    for i in range(spec.warmup - 1, len(frame)):
        block = data[i - spec.warmup + 1 : i + 1]
        if not np.isfinite(block).all() or any(
            (block[:, j] < 0 if key == "volume" else block[:, j] <= 0).any()
            for j, key in enumerate(spec.inputs)
        ):
            continue
        if n == 6:
            out[i] = -corr(cols["open"][i - w + 1 : i + 1], cols["volume"][i - w + 1 : i + 1])
        elif n == 9:
            d = [cols["close"][j] - cols["close"][j - 1] for j in range(i - w + 1, i + 1)]
            out[i] = d[-1] if all(v > 0 for v in d) or all(v < 0 for v in d) else -d[-1]
        elif n == 12:
            dv = cols["volume"][i] - cols["volume"][i - w]
            out[i] = (1 if dv > 0 else -1 if dv < 0 else 0) * (
                cols["close"][i - w] - cols["close"][i]
            )
        elif n == 23:
            out[i] = (
                cols["high"][i - 2] - cols["high"][i]
                if cols["high"][i] > math.fsum(cols["high"][i - w + 1 : i + 1]) / w
                else 0
            )
        elif n == 53:

            def ratio(j):
                c, h, low = (cols[k][j] for k in ("close", "high", "low"))
                return ((c - low) - (h - c)) / (c - low) if c != low else math.nan

            out[i] = ratio(i - w) - ratio(i)
        elif n == 101:
            out[i] = (cols["close"][i] - cols["open"][i]) / (
                cols["high"][i] - cols["low"][i] + 0.001
            )
    return pd.Series(out, index=frame.index)


def pool():
    result = {}
    for i in range(6):
        f = sample()
        scale = 1 + i * 0.03 + np.sin(np.arange(len(f)) / (3 + i)) * 0.1
        f[["open", "high", "low", "close"]] = f[["open", "high", "low", "close"]].mul(scale, axis=0)
        f.volume += (np.arange(len(f)) * (i + 1) * 73) % 601
        result[f"SZ:{i + 1:06d}"] = f
    return result


def panel_oracle(frames, spec):
    if spec.number in {32, 57, 60}:
        from tests.unit.test_alpha101_seventh import expected

        return expected(frames, spec)
    if spec.number in {5, 11, 27, 52}:
        from tests.unit.test_alpha101_sixth import expected

        return expected(frames, spec)
    if spec.number in {42, 50, 55}:
        from tests.unit.test_alpha101_fifth import expected

        return expected(frames, spec)
    if spec.number in {8, 19, 30, 34, 45}:
        from tests.unit.test_alpha101_fourth import panel_oracle as fourth_oracle

        return fourth_oracle(frames, spec)
    if spec.number in {14, 15, 18, 20, 37}:
        from tests.unit.test_alpha101_third import panel_oracle as third_oracle

        return third_oracle(frames, spec)
    if spec.number not in FIRST:
        from tests.unit.test_alpha101_second import panel_oracle as second_oracle

        return second_oracle(frames, spec)
    dates = sorted(set().union(*(set(f.index) for f in frames.values())))
    fields = {}
    for key in spec.inputs:
        rows = []
        for date in dates:
            vals = [f.at[date, key] if date in f.index else math.nan for f in frames.values()]
            vals = [
                v if math.isfinite(v) and (v >= 0 if key == "volume" else v > 0) else math.nan
                for v in vals
            ]
            rows.append(
                [
                    percentile(vals, v) if sum(math.isfinite(x) for x in vals) >= 2 else math.nan
                    for v in vals
                ]
            )
        fields[key] = np.array(rows)
    w = spec.window
    output = np.full((len(dates), len(frames)), np.nan)
    for i in range(w - 1, len(dates)):
        for j in range(len(frames)):
            if spec.number == 3:
                output[i, j] = -corr(
                    fields["open"][i - w + 1 : i + 1, j].tolist(),
                    fields["volume"][i - w + 1 : i + 1, j].tolist(),
                )
            else:
                values = fields["low"][i - w + 1 : i + 1, j].tolist()
                if all(math.isfinite(v) for v in values):
                    output[i, j] = -percentile(values, values[-1])
    return pd.DataFrame(output, index=pd.DatetimeIndex(dates), columns=list(frames))


@pytest.mark.parametrize("n", FIRST)
@pytest.mark.parametrize("custom", [False, True])
def test_alpha101_independent_prefix_and_parameters(n, custom):
    default = SPECS[n]
    params = {"window": 3} if custom and default.window else {}
    factor = configure_factor(name(n), params)
    assert get_factor(name(n)).spec == default
    if default.panel:
        frames = pool()
        frames["SZ:000002"] = frames["SZ:000002"].drop(index=frames["SZ:000002"].index[35])
        panel = FactorPanel.build(frames, default.inputs)
        actual = factor.compute_panel(panel)
        expected = panel_oracle(frames, factor.spec)
        prefix = factor.compute_panel(
            FactorPanel.build({s: f.iloc[:30] for s, f in frames.items()}, default.inputs)
        )
        np.testing.assert_allclose(actual, expected, atol=1e-12, equal_nan=True)
        pd.testing.assert_frame_equal(prefix, actual.iloc[:30])
        with pytest.raises(ValueError, match="股票池"):
            factor.compute(sample())
    else:
        frame = sample()
        actual = factor.compute(frame)
        expected = independent(frame, factor.spec)
        np.testing.assert_allclose(actual, expected, atol=1e-12, equal_nan=True)
        pd.testing.assert_series_equal(factor.compute(frame.iloc[:30]), actual.iloc[:30])
        assert actual.iloc[: factor.spec.warmup - 1].isna().all()


@pytest.mark.parametrize("n", [6, 9, 12, 23, 53, 101])
def test_alpha101_missing_invalid_constant_and_recovery(n):
    f = sample()
    factor = get_factor(name(n))()
    key = factor.inputs[0]
    for bad in (np.nan, np.inf, 0.0, -1.0):
        broken = f.copy()
        broken.loc[broken.index[30], key] = bad
        out = factor.compute(broken)
        assert out.iloc[30 : 30 + factor.spec.warmup].isna().all()
        np.testing.assert_allclose(
            out.iloc[30 + factor.spec.warmup :],
            factor.compute(f).iloc[30 + factor.spec.warmup :],
            equal_nan=True,
        )
    constant = f.copy()
    constant.loc[:, :] = 10.0
    out = factor.compute(constant)
    if n in {6, 53}:
        assert out.isna().all()
    else:
        assert out.iloc[factor.spec.warmup - 1 :].eq(0).all()


def test_alpha101_hand_examples_and_ties():
    f = pd.DataFrame(
        dict(
            close=[2.0, 3.0, 4.0, 3.0, 2.0],
            volume=[5.0, 7.0, 7.0, 6.0, 9.0],
            high=[3.0, 4.0, 5.0, 4.0, 3.0],
            low=[1.0, 2.0, 3.0, 2.0, 1.0],
            open=[1.0, 2.0, 3.0, 2.0, 1.0],
        )
    )
    assert get_factor(name(12))().compute(f).tolist()[1:] == [-1, 0, -1, 1]
    assert configure_factor(name(9), {"window": 2}).compute(f).tolist()[2:] == [1, 1, -1]
    np.testing.assert_allclose(get_factor(name(101))().compute(f), [1 / 2.001] * 5)
    frames = {"a": sample(5), "b": sample(5)}
    out = configure_factor(name(4), {"window": 3}).compute_panel(
        FactorPanel.build(frames, ("low",))
    )
    np.testing.assert_allclose(out.iloc[2:], -2 / 3)
    one = configure_factor(name(4), {"window": 3}).compute_panel(
        FactorPanel.build({"a": sample(5)}, ("low",))
    )
    assert one.isna().all().all()


@pytest.mark.parametrize("n", [3, 4, 6, 9, 12, 23, 53, 101])
def test_alpha101_metadata_validation_and_no_mutation(n):
    row = next(r for r in list_factors() if r["name"] == name(n))
    assert row["library"] == "alpha101" and row["implemented"]
    assert row["available"] == (not SPECS[n].panel)
    assert row["release_status"] == "local_validation_only_pending_license_review"
    if SPECS[n].window is not None:
        from easy_tdx.factor.catalog import describe_factor

        for w in (3, 12, 500):
            metadata = describe_factor(get_factor(name(n)), {"window": w})
            predicted = max(
                term["offset"] + sum(w for _ in term["windows"])
                for term in metadata["warmup_terms"]
            )
            assert predicted == metadata["warmup_bars"]
    for params in (
        {"window": True},
        {"window": 1.5},
        {"window": 501},
        {"window": -1},
        {"extra": 2},
    ):
        with pytest.raises(ValueError):
            configure_factor(name(n), params)
    if n == 101:
        with pytest.raises(ValueError):
            configure_factor(name(n), {"window": 3})
    f = sample()
    before = f.copy(deep=True)
    if not SPECS[n].panel:
        get_factor(name(n))().compute(f)
    pd.testing.assert_frame_equal(f, before)


@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
@pytest.mark.parametrize("n", [6, 9, 12, 23, 53, 101])
def test_alpha101_real_three_adjustment_oracle(n, adjust):
    raw = frozen("0-000001-DAILY-NONE.json")
    f = qualify_factor_fields(frozen(f"0-000001-DAILY-{adjust}.json"), raw)
    np.testing.assert_allclose(
        get_factor(name(n))().compute(f),
        independent(f, SPECS[n]),
        rtol=1e-10,
        atol=1e-12,
        equal_nan=True,
    )


@pytest.mark.parametrize("n", [6, 9, 12, 23, 53, 101])
def test_alpha101_series_archive_readonly_recompute(monkeypatch, n):
    raw = frozen("0-000001-DAILY-NONE.json")
    f = qualify_factor_fields(frozen("0-000001-DAILY-QFQ.json"), raw)
    req = research.FactorComputeRequest(
        market="SZ", code="000001", count=160, adjust="QFQ", factors=[name(n)]
    )
    result = research._factor_result(req, f).data
    assert not result["errors"]
    original = {
        "format": "factor-research-v1",
        "mode": "series",
        "title": "Alpha101 本地核验",
        "savedAt": "2026-10-10T10:00:00Z",
        "result": result,
    }
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(Alpha101Factor, "compute", lambda *a: pytest.fail("read executes"))
        validate_factor_archive(original)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("live fetch"))
    newer = research.recompute_factor_payload(record(original))
    assert newer["result"]["rows"] == result["rows"]
    assert original == before


def test_alpha101_cancellation_and_relative_scale(monkeypatch):
    from easy_tdx.factor.builtin import alpha101

    calls = 0

    def stop():
        nonlocal calls
        calls += 1
        if calls == 10:
            raise RuntimeError("cancel")

    with monkeypatch.context() as guard:
        guard.setattr(alpha101, "computation_checkpoint", stop)
        with pytest.raises(RuntimeError, match="cancel"):
            get_factor(name(6))().compute(sample())
    f = sample()
    for scale in (1e-150, 1e150):
        np.testing.assert_allclose(
            get_factor(name(6))().compute(f * scale),
            get_factor(name(6))().compute(f),
            atol=1e-12,
            equal_nan=True,
        )


@pytest.mark.parametrize("n", [3, 4])
def test_alpha101_real_panel_oracle(n):
    from tests.unit.test_gtja191_vwap import long_frozen

    root = Path(__file__).parents[1] / "fixtures/factor_vwap_long"
    frames = {
        path.stem: long_frozen(path.name).set_index("datetime")
        for path in sorted(root.glob("*-DAILY-NONE.json"))
    }
    factor = get_factor(name(n))()
    result = factor.compute_panel(FactorPanel.build(frames, factor.inputs))
    np.testing.assert_allclose(
        result, panel_oracle(frames, factor.spec), atol=1e-12, equal_nan=True
    )
    assert result.notna().any().any()


@pytest.mark.parametrize("n", FIRST)
def test_alpha101_minute_real_oracle(n):
    from tests.unit.test_gtja191_vwap import long_frozen

    frame = long_frozen("0-300750-MIN_30-NONE.json").set_index("datetime")
    factor = get_factor(name(n))()
    if SPECS[n].panel:
        # One actual stock cannot supply a cross-section; never fabricate peers.
        result = factor.compute_panel(FactorPanel.build({"SZ:300750": frame}, factor.inputs))
        assert result.isna().all().all()
    else:
        np.testing.assert_allclose(
            factor.compute(frame), independent(frame, SPECS[n]), atol=1e-12, equal_nan=True
        )


@pytest.mark.asyncio
async def test_alpha101_joint_pool_archive(monkeypatch):
    async def fetch(*args):
        f = frozen("0-000001-DAILY-NONE.json").copy()
        i = int(args[3][-1])
        scale = 1 + i * 0.01 + np.sin(np.arange(len(f)) / (i + 3)) * 0.01
        f[["open", "high", "low", "close"]] = f[["open", "high", "low", "close"]].mul(scale, axis=0)
        f["amount"] *= scale
        return f

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 7)],
        factors=[name(3), name(4), name(9)],
        count=160,
        adjust="NONE",
    )
    result = (await research.factor_evaluate(req, None, None)).data
    assert not result["errors"]
    original = {
        "format": "factor-research-v1",
        "mode": "evaluation",
        "title": "Alpha101 本地核验",
        "savedAt": "2026-10-10T10:00:00Z",
        "result": result,
    }
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(Alpha101PanelFactor, "compute_panel", lambda *a: pytest.fail("read executes"))
        guard.setattr(Alpha101Factor, "compute", lambda *a: pytest.fail("read executes"))
        validate_factor_archive(original)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("live fetch"))
    newer = research.recompute_factor_payload(record(original))
    assert newer["result"]["reports"] == result["reports"]
    assert original == before
