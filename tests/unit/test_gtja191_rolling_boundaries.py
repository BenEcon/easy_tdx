"""Hand boundary cases outside the generic scalar oracle for rolling GTJA factors."""

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor.configuration import configure_factor, configured_selection


def run(number, data, window=None):
    return configure_factor(f"gtja191_{number:03}", {"window": window} if window else {}).compute(
        pd.DataFrame(data)
    )


def test_acceleration_exact_decimal_zero_and_threshold():
    # Falling straight line has zero acceleration: keep −ΔC, not the +1 branch.
    assert run(86, {"close": [20.50, 20.49, 20.48]}, 1).iloc[-1] == pytest.approx(0.01)
    assert run(86, {"close": [10.04, 10.05, 10.06]}, 1).iloc[-1] == pytest.approx(-0.01)
    assert run(86, {"close": [10.1, 10.2, 10.55]}, 1).iloc[-1] == pytest.approx(-0.35)
    assert run(86, {"close": [10, 10, 10.26]}, 1).iloc[-1] == -1
    assert run(86, {"close": [10, 11, 11.9]}, 1).iloc[-1] == 1


def test_regression_uses_mean_close_not_reference_modules_raw_close():
    # Means: 2, 14/3, 29/3; slope over these 3 values = (29/3−2)/2.
    result = run(21, {"close": [1, 2, 3, 9, 17]}, 3)
    assert result.iloc[:4].isna().all()
    assert result.iloc[4] == pytest.approx(23 / 6)
    assert run(116, {"close": [3, 9, 17]}, 3).iloc[-1] == 7
    with pytest.raises(ValueError, match="重复"):
        configured_selection(["gtja191_021", "gtja191_147"], {"gtja191_021": {"window": 12}})


def test_extreme_distance_zero_based_recent_ties():
    data = {"high": [12, 15, 14, 15], "low": [8, 7, 7, 9]}
    assert run(177, data, 4).iloc[-1] == 100
    assert run(103, data, 4).iloc[-1] == 75
    assert run(133, data, 4).iloc[-1] == 25
    for n in (103, 177):
        assert run(n, {"high": [10] * 4, "low": [10] * 4}, 4).iloc[-1] == 100


def test_decimal_equal_price_sums_are_not_false_directional_money_flow():
    data = {
        "high": [20, 20.08, 20],
        "low": [10.03, 9.95, 10.03],
        "close": [15] * 3,
        "volume": [100] * 3,
    }
    for number in (49, 50, 51, 128):
        assert np.isnan(run(number, data, 2).iloc[-1])


def test_conditional_pressure_ties_and_denominator_semantics():
    # Rising bar's max endpoint change 3, falling bar's 2: U=3, D=2.
    data = {"high": [12, 15, 13], "low": [8, 9, 7]}
    for n, expected in ((49, 0.4), (50, 0.2), (51, 0.6)):
        assert run(n, data, 2).iloc[-1] == pytest.approx(expected)
    flat = {
        "open": [10] * 4,
        "close": [10] * 4,
        "high": [11] * 4,
        "low": [9] * 4,
        "volume": [0] * 4,
    }
    assert run(69, flat, 3).iloc[-1] == 0  # Explicit equality branch in the formula.
    for n in (40, 49, 50, 51, 76, 112, 128, 139):
        assert np.isnan(run(n, flat, 3).iloc[-1])
    # No negative money-flow denominator: do not silently replace undefined by 100.
    up = {k: [10, 11, 12, 13] for k in ("open", "close", "high", "low")}
    up["volume"] = [100] * 4
    assert np.isnan(run(128, up, 3).iloc[-1])


def test_correlation_and_slope_large_offset_and_constants():
    data = {"open": np.array([1, 3, 5, 7]) * 2**-10 + 2**40, "volume": [10, 20, 30, 40]}
    assert run(139, data, 4).iloc[-1] == pytest.approx(-1)
    assert run(116, {"close": data["open"]}, 4).iloc[-1] == pytest.approx(2**-9)
    assert np.isnan(run(139, {"open": [10] * 4, "volume": [10, 20, 30, 40]}, 4).iloc[-1])


def test_nested_peak_rms_has_two_complete_windows():
    result = run(127, {"close": [1, 2, 3, 2, 1]}, 3)
    assert result.iloc[:4].isna().all()
    assert result.iloc[-1] == pytest.approx(np.sqrt(50000 / 27))


def test_volume_mean_correlation_uses_fixed_five_outer_bars():
    # Three-bar volume means are 20,30,40,50,60; low is perfectly aligned.
    data = {
        "volume": [10, 20, 30, 40, 50, 60, 70],
        "low": [1, 2, 3, 4, 5, 6, 7],
        "high": [5, 6, 7, 8, 9, 10, 11],
        "close": [2, 3, 4, 5, 6, 7, 8],
    }
    result = run(191, data, 3)
    assert result.iloc[:6].isna().all()
    assert result.iloc[-1] == pytest.approx(2)  # corr 1 + midpoint9 − close8


def test_power_ratio_is_price_scale_invariant_without_intermediate_overflow():
    base = {"open": [10.0], "close": [11.0], "high": [12.0], "low": [9.0]}
    expected = -(9 - 11) * 10**5 / ((11 - 12) * 11**5)
    for scale in (1e-70, 1, 1e70):
        values = {key: np.asarray(value) * scale for key, value in base.items()}
        assert run(171, values).iloc[-1] == pytest.approx(expected)
        assert run(158, values).iloc[-1] == pytest.approx(3 / 11)
    base["close"] = [12.0]
    assert np.isnan(run(171, base).iloc[-1])


@pytest.mark.parametrize("number", [21, 76, 116, 139, 147])
def test_undefined_one_point_statistics_rejected_in_parameters(number):
    with pytest.raises(ValueError, match="窗口"):
        configure_factor(f"gtja191_{number:03}", {"window": 1})
