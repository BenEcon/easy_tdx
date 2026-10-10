"""OBV slope: independent OLS, complete local windows and finite input semantics."""

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import get_factor
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor
from tests.unit.test_builtin_factor_parameters import oracle, sample
from tests.unit.test_factor_data import ROOT, frozen


def local_oracle(frame, window):
    """Construct each local OBV path, then solve OLS (not the production weights)."""
    result = np.full(len(frame), np.nan)
    for end in range(window - 1, len(frame)):
        block = frame.iloc[end - window + 1 : end + 1]
        c, v = block.close.to_numpy(), block.vol.to_numpy()
        if not (np.isfinite(c).all() and (c > 0).all() and np.isfinite(v).all() and (v >= 0).all()):
            continue
        y = [0.0]
        for j in range(1, window):
            direction = 1 if c[j] > c[j - 1] else -1 if c[j] < c[j - 1] else 0
            y.append(y[-1] + direction * v[j])
        result[end] = np.linalg.lstsq(np.c_[np.arange(window), np.ones(window)], y, rcond=None)[0][
            0
        ]
    return result


@pytest.mark.parametrize("window", [2, 5, 20, 60, 600])
def test_obv_matches_global_ols_on_clean_data_and_local_ols(window):
    frame = sample(810)
    factor = configure_factor("obv_trend", {"window": window})
    actual = factor.compute(frame)
    for expected in (oracle(frame, "obv_trend", {"window": window}), local_oracle(frame, window)):
        np.testing.assert_allclose(actual, expected, rtol=2e-10, atol=2e-9, equal_nan=True)
    assert actual.first_valid_index() == frame.index[window - 1]
    pd.testing.assert_series_equal(actual.iloc[:650], factor.compute(frame.iloc[:650]))
    assert actual.index.equals(frame.index)


@pytest.mark.parametrize(
    "column,bad",
    [
        ("close", np.nan),
        ("close", np.inf),
        ("close", -np.inf),
        ("close", 0.0),
        ("close", -1.0),
        ("vol", np.nan),
        ("vol", np.inf),
        ("vol", -np.inf),
        ("vol", -1.0),
    ],
)
@pytest.mark.parametrize("window", [2, 5, 20])
def test_invalid_inputs_mask_entire_window_and_then_recover(column, bad, window):
    frame = sample(85)
    frame.iloc[30, frame.columns.get_loc(column)] = bad
    before = frame.copy(deep=True)
    factor = configure_factor("obv_trend", {"window": window})
    actual = factor.compute(frame)
    assert actual.iloc[30 : 30 + window].isna().all()
    assert np.isfinite(actual.iloc[30 + window])
    np.testing.assert_allclose(
        actual, local_oracle(frame, window), rtol=2e-10, atol=2e-9, equal_nan=True
    )
    pd.testing.assert_series_equal(actual.iloc[:55], factor.compute(frame.iloc[:55]))
    pd.testing.assert_frame_equal(frame, before)


def test_old_extreme_volume_does_not_destroy_local_precision():
    clean = sample(70)
    large = clean.copy()
    large.iloc[3, large.columns.get_loc("vol")] = 1e25
    factor = configure_factor("obv_trend", {"window": 5})
    actual = factor.compute(large)
    pd.testing.assert_series_equal(actual.iloc[8:], factor.compute(clean).iloc[8:])
    pd.testing.assert_series_equal(actual.iloc[20:], factor.compute(large.iloc[16:]).iloc[4:])


@pytest.mark.parametrize("direction", [-1, 0, 1])
@pytest.mark.parametrize("volume", [0.0, 10.0, 1e308])
def test_constant_signed_volume_has_known_slope_without_cumulative_overflow(direction, volume):
    frame = sample(800)
    frame["close"] = 1000 + direction * np.arange(800)
    frame["vol"] = volume
    actual = configure_factor("obv_trend", {"window": 600}).compute(frame)
    np.testing.assert_allclose(actual.iloc[599:], direction * volume, rtol=5e-15, atol=0)
    assert not np.isinf(actual).any()


def test_hand_calculated_ties_gaps_and_units():
    # Local OBV = [0, 20, 20, -20, 30]. OLS = 20 / 10 = 2,
    # whereas summing signed volume / window would incorrectly give 6.
    frame = pd.DataFrame(
        {"close": [10, 11, 11, 10, 12], "vol": [10, 20, 30, 40, 50]}, index=[2, 5, 9, 15, 22]
    )
    factor = configure_factor("obv_trend", {"window": 5})
    assert factor.compute(frame).iloc[-1] == pytest.approx(2)
    frame.loc[22, "vol"] = 100  # OBV = [0, 20, 20, -20, 80]; slope = 12.
    assert factor.compute(frame).iloc[-1] == pytest.approx(12)
    doubled = frame.assign(vol=frame.vol * 2)
    np.testing.assert_allclose(factor.compute(doubled), 2 * factor.compute(frame), equal_nan=True)
    assert factor.compute(frame.iloc[:0]).empty
    assert factor.compute(frame.iloc[:4]).isna().all()


@pytest.mark.parametrize("path", sorted(ROOT.glob("*.json")), ids=lambda p: p.stem)
def test_real_frozen_units_adjustments_and_injected_gap(path):
    frame = frozen(path.name)
    for window in (2, 13, 20, 60):
        factor = configure_factor("obv_trend", {"window": window})
        actual = factor.compute(frame)
        np.testing.assert_allclose(
            actual, local_oracle(frame, window), atol=2e-6, rtol=2e-10, equal_nan=True
        )
        pd.testing.assert_series_equal(actual.iloc[:100], factor.compute(frame.iloc[:100]))
        missing = frame.copy()
        missing.iloc[70, missing.columns.get_loc("close")] = np.nan
        np.testing.assert_allclose(
            factor.compute(missing),
            local_oracle(missing, window),
            atol=2e-6,
            rtol=2e-10,
            equal_nan=True,
        )


def test_changed_semantics_are_versioned_without_changing_other_factors():
    meta = describe_factor(get_factor("obv_trend"))
    assert meta["implementation_version"] == "obv-local-window-v3"
    assert meta["warmup_bars"] == 20
    assert any("完整窗口" in text and "缺失" in text for text in meta["limitations"])
    assert (
        describe_factor(get_factor("vol_surge"))["implementation_version"]
        == "builtin-parameters-v2"
    )
    assert (
        meta["formula_sha256"]
        != describe_factor(get_factor("obv_trend"), {"window": 5})["formula_sha256"]
    )


def test_legacy_obv_archive_remains_read_only_and_explicit_replay_records_new_version(
    tmp_path, monkeypatch
):
    from uuid import uuid4

    from easy_tdx.factor import builtin_parameters
    from easy_tdx.web.factor_archive import validate_factor_archive
    from easy_tdx.web.research_archive import ResearchArchive
    from easy_tdx.web.routers import research

    def legacy_compute(self, frame):
        direction = np.sign(frame.close.diff()).fillna(0)
        path = (direction * frame.vol).cumsum()
        x = np.arange(self.window, dtype=float)
        x -= x.mean()
        return path.rolling(self.window).apply(lambda y: x @ (y - y.mean()) / (x @ x), raw=True)

    current_metadata = builtin_parameters.metadata

    def legacy_metadata(canonical, defaults, factor):
        result = current_metadata(canonical, defaults, factor)
        if canonical == "obv_trend":
            result.update(
                implementation_version="builtin-parameters-v2",
                formula=f"OLS slope(cumsum(sign(close.diff()) * vol), {factor.window})",
            )
        return result

    frame = frozen("0-000001-DAILY-NONE.json")
    frame.loc[70, "close"] = np.nan  # Explicit injected defect, not a claimed real suspension.
    request = research.FactorComputeRequest(
        market="SZ", code="000001", adjust="NONE", count=160, factors=["obv_trend"]
    )
    with monkeypatch.context() as old:
        old.setattr(get_factor("obv_trend"), "compute", legacy_compute)
        old.setattr(builtin_parameters, "metadata", legacy_metadata)
        previous = research._factor_result(request, frame).data
    source = {
        "format": "factor-research-v1",
        "mode": "series",
        "title": "旧 OBV 验收样例",
        "savedAt": "2026-10-10T00:00:00Z",
        "result": previous,
    }
    validate_factor_archive(source)
    store = ResearchArchive(tmp_path / "archives.db")
    key = str(uuid4())
    store.create("alice", key, "factor", source, "旧版本", "")
    original = store.get("alice", key)
    assert all(row["obv_trend"] is not None for row in previous["rows"][70:90])
    # Read must neither calculate nor silently replace historical definitions.
    with monkeypatch.context() as readonly:
        readonly.setattr(
            get_factor("obv_trend"), "compute", lambda *a: pytest.fail("read computed")
        )
        validate_factor_archive(store.get("alice", key)["payload"])
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("no new prices"))
    replay = research.recompute_factor_payload(original)
    validate_factor_archive(replay)
    result = replay["result"]
    assert all(row["obv_trend"] is None for row in result["rows"][70:90])
    assert result["rows"][90]["obv_trend"] is not None
    assert result["diagnostics"]["obv_trend"]["missing_count"] == 39
    assert (
        result["factor_definitions"]["obv_trend"]["implementation_version"] == "obv-local-window-v3"
    )
    assert replay["recomputed_from"]["original_definitions"] == previous["factor_definitions"]
    assert (
        result["factor_definitions"]["obv_trend"]["formula_sha256"]
        != previous["factor_definitions"]["obv_trend"]["formula_sha256"]
    )
    store.create("alice", str(uuid4()), "factor", replay, "显式重算", "")
    assert store.get("alice", key) == original
    assert len(store.list("alice")["items"]) == 2
