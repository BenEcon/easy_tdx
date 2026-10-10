"""Per-definition edge contracts, separate from the default numerical oracle."""

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor.builtin.alpha158 import SPECS, compute_alpha158
from tests.unit.test_alpha158 import oracle, sample
from tests.unit.test_factor_data import FILES, frozen

DEPENDENCIES = [(key, field) for key, spec in SPECS.items() for field in spec.inputs]


@pytest.mark.parametrize("key,field", DEPENDENCIES)
@pytest.mark.parametrize("bad", [np.nan, np.inf, -1.0])
def test_every_declared_dependency_requires_complete_valid_window(key, field, bad):
    frame = sample(150)
    spec = SPECS[key]
    clean = compute_alpha158(frame, spec)
    frame.loc[frame.index[70], field] = bad
    before = frame.copy(deep=True)
    result = compute_alpha158(frame, spec)
    assert result.iloc[70 : 70 + spec.warmup].isna().all()
    pd.testing.assert_series_equal(result.iloc[:70], clean.iloc[:70])
    pd.testing.assert_series_equal(result.iloc[70 + spec.warmup :], clean.iloc[70 + spec.warmup :])
    pd.testing.assert_series_equal(result.iloc[:90], compute_alpha158(frame.iloc[:90], spec))
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("key", SPECS)
@pytest.mark.parametrize("volume", [0.0, 100.0])
def test_every_constant_window_has_explicit_mathematical_result(key, volume):
    spec = SPECS[key]
    frame = sample(80)
    frame.loc[:, ["open", "high", "low", "close", "vwap"]] = 10.0
    frame["volume"] = volume
    family, window = spec.family, spec.window
    if family in {"RSQR", "CORR", "CORD"}:
        expected = np.nan  # Undefined correlation, not a fake zero.
    elif family in {"OPEN0", "HIGH0", "LOW0", "VWAP0", "ROC", "MA", "MAX", "MIN", "QTLU", "QTLD"}:
        expected = 1.0
    elif family == "VMA":
        expected = volume / (volume + 1e-12)
    elif family == "RANK":
        expected = (window + 1) / (2 * window)
    elif family in {"IMAX", "IMIN"}:
        expected = 1 / window  # First tied occurrence, one-based.
    else:
        expected = 0.0
    result = compute_alpha158(frame, spec)
    assert result.iloc[: spec.warmup - 1].isna().all()
    np.testing.assert_allclose(
        result.iloc[spec.warmup - 1 :], expected, rtol=1e-12, atol=1e-12, equal_nan=True
    )


@pytest.mark.parametrize("key", SPECS)
def test_bar_windows_do_not_fill_missing_calendar_rows(key):
    # A removed row simulates absent input, NOT a verified real suspension.
    frame = sample(85).drop(sample(85).index[20:25])
    spec = SPECS[key]
    result = compute_alpha158(frame, spec)
    assert result.index.equals(frame.index) and len(result) == 80
    expected = [oracle(frame, key, i) for i in range(len(frame))]
    np.testing.assert_allclose(result, expected, atol=2e-10, rtol=2e-8, equal_nan=True)


@pytest.mark.parametrize("key", SPECS)
def test_short_empty_and_absent_required_columns_are_not_fake_results(key):
    frame = sample(65)
    spec = SPECS[key]
    assert compute_alpha158(frame.iloc[:0], spec).empty
    assert compute_alpha158(frame.iloc[: spec.warmup - 1], spec).isna().all()
    for field in spec.inputs:
        with pytest.raises(ValueError, match="缺少字段"):
            compute_alpha158(frame.drop(columns=field), spec)


@pytest.mark.parametrize("filename", FILES)
def test_every_qualified_real_value_against_independent_oracle(filename):
    from easy_tdx.factor.data import qualify_factor_fields

    frame = frozen(filename)
    raw = frozen(filename.rsplit("-", 1)[0] + "-NONE.json")
    vwap_allowed = filename.endswith("-NONE.json")
    data = qualify_factor_fields(frame, raw, need_vwap=vwap_allowed)
    for key, spec in SPECS.items():
        if "vwap" in spec.inputs and not vwap_allowed:
            continue  # Explicitly unsupported adjusted VWAP, not a price-ratio proxy.
        actual = compute_alpha158(data, spec)
        expected = [oracle(data, key, i) for i in range(len(data))]
        np.testing.assert_allclose(
            actual, expected, atol=2e-8, rtol=2e-8, equal_nan=True, err_msg=f"{filename}: {key}"
        )
