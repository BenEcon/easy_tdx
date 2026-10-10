"""Independent list/closed-weight oracle for recursive GTJA definitions.

The reference smoother expands geometric weights instead of using production's
recursive state update. Defaults, inputs and nested expressions are transcribed
independently; no production Spec determines expected values or warmups.
"""

import math
import statistics

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.builtin.gtja191 import SPECS, _sma
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from easy_tdx.factor.data import qualify_factor_fields
from tests.unit.test_factor_data import FILES, frozen
from tests.unit.test_gtja191 import sample

DEFAULTS = {
    9: 7,
    24: 5,
    47: 9,
    57: 3,
    63: 6,
    67: 24,
    68: 15,
    72: 15,
    79: 12,
    81: 21,
    82: 20,
    96: 3,
    102: 6,
    109: 10,
    122: 13,
    135: 20,
    151: 20,
    160: 20,
    173: 13,
    174: 20,
    188: 11,
}
INPUTS = {
    **{n: ("close",) for n in (24, 63, 67, 79, 122, 135, 151, 160, 173, 174)},
    **{n: ("volume",) for n in (81, 102)},
    **{n: ("close", "high", "low") for n in (47, 57, 72, 82, 96)},
    **{n: ("high", "low", "volume") for n in (9, 68)},
    **{n: ("high", "low") for n in (109, 188)},
}


def warmup(n, w):
    if n in (9, 68, 63, 67, 79, 102):
        return w + 1
    if n in (24, 151):
        return 2 * w
    if n in (47, 72, 82):
        return w + 5
    if n == 57:
        return w + 8
    if n == 96:
        return 2 * w + 7
    if n in (109, 160, 174):
        return 2 * w - 1
    if n == 122:
        return 3 * w - 1
    if n == 173:
        return 3 * w - 2
    if n == 135:
        return 2 * w + 1
    return w


def weighted(values, w, m):
    """Closed geometric sum, first seed coefficient (1−alpha)^(length−1)."""
    result, segment = [], []
    a, b = m / w, 1 - m / w
    for value in values:
        if not math.isfinite(value):
            segment = []
        else:
            segment.append(float(value))
        if len(segment) < w:
            result.append(math.nan)
        else:
            size = len(segment)
            result.append(
                math.fsum(
                    [segment[0] * b ** (size - 1)]
                    + [a * segment[i] * b ** (size - i - 1) for i in range(1, size)]
                )
            )
    return result


def rolling(values, w, fn):
    return [
        fn(values[i - w + 1 : i + 1])
        if i >= w - 1 and all(math.isfinite(x) for x in values[i - w + 1 : i + 1])
        else math.nan
        for i in range(len(values))
    ]


def shift(values, lag=1):
    return [math.nan] * min(len(values), lag) + values[: max(0, len(values) - lag)]


def combine(a, b, op):
    return [op(x, y) if math.isfinite(x) and math.isfinite(y) else math.nan for x, y in zip(a, b)]


def divide(x, y):
    return x / y if y else math.nan


def independent(frame, n, w):
    data = {field: frame[field].tolist() for field in INPUTS[n]}
    valid = [
        all(
            math.isfinite(data[f][i]) and (data[f][i] >= 0 if f == "volume" else data[f][i] > 0)
            for f in INPUTS[n]
        )
        for i in range(len(frame))
    ]
    for field in data:
        data[field] = [x if valid[i] else math.nan for i, x in enumerate(data[field])]
    c, h, l, v = (data.get(f) for f in ("close", "high", "low", "volume"))  # noqa: E741

    def diff(arr, lag=1):
        return combine(arr, shift(arr, lag), lambda x, y: x - y)

    if n in (9, 68):
        mid = combine(h, l, lambda x, y: (x + y) / 2)
        raw = combine(
            combine(diff(mid), combine(h, l, lambda x, y: x - y), lambda x, y: x * y),
            v,
            divide,
        )
        return weighted(raw, w, 2)
    if n in (24, 151, 135):
        raw = diff(c, w) if n != 135 else shift(combine(c, shift(c, w), divide))
        span = w + 1 if n != 135 else w + 2
        raw = [
            x if i >= span - 1 and all(valid[i - span + 1 : i + 1]) else math.nan
            for i, x in enumerate(raw)
        ]
        return weighted(raw, w, 1)
    if n in (47, 57, 72, 82, 96):
        extent = 6 if n in (47, 72, 82) else 9
        hi, lo = rolling(h, extent, max), rolling(l, extent, min)
        distance = (
            combine(hi, c, lambda x, y: x - y)
            if extent == 6
            else combine(c, lo, lambda x, y: x - y)
        )
        raw = combine(
            distance, combine(hi, lo, lambda x, y: x - y), lambda x, y: divide(x, y) * 100
        )
        first = weighted(raw, w, 1)
        return weighted(first, w, 1) if n == 96 else first
    if n in (63, 67, 79, 102):
        change = diff(v if n == 102 else c)
        up = weighted([max(x, 0) for x in change], w, 1)
        total = weighted([abs(x) for x in change], w, 1)
        return combine(up, total, lambda x, y: divide(x, y) * 100)
    if n == 81:
        return weighted(v, w, 2)
    if n in (109, 188):
        amplitude = combine(h, l, lambda x, y: x - y)
        first = weighted(amplitude, w, 2)
        return (
            combine(first, weighted(first, w, 2), divide)
            if n == 109
            else combine(amplitude, first, lambda x, y: (divide(x, y) - 1) * 100)
        )
    if n in (122, 173):
        triple = weighted(
            weighted(
                weighted([math.log(x) if math.isfinite(x) else math.nan for x in c], w, 2), w, 2
            ),
            w,
            2,
        )
        if n == 122:
            return combine(triple, shift(triple), lambda x, y: divide(x, y) - 1)
        first = weighted(c, w, 2)
        second = weighted(first, w, 2)
        return combine(
            combine(first, second, lambda x, y: 3 * x - 2 * y), triple, lambda x, y: x + y
        )
    std = rolling(c, w, statistics.stdev)
    change = diff(c)
    raw = [sd if ((d <= 0) if n == 160 else (d > 0)) else 0.0 for sd, d in zip(std, change)]
    raw = [
        x if math.isfinite(sd) and math.isfinite(d) else math.nan
        for x, sd, d in zip(raw, std, change)
    ]
    return weighted(raw, w, 1)


@pytest.mark.parametrize("number", sorted(DEFAULTS))
@pytest.mark.parametrize("window", [None, 3, 7])
def test_independent_expanded_weights_every_row_and_causal_prefix(number, window):
    w = window or DEFAULTS[number]
    frame = sample(100)
    factor = configure_factor(f"gtja191_{number:03}", {"window": w})
    assert factor.spec.warmup == warmup(number, w)
    assert factor.spec.inputs == INPUTS[number]
    actual = factor.compute(frame)
    np.testing.assert_allclose(
        actual, independent(frame, number, w), rtol=2e-10, atol=1e-10, equal_nan=True
    )
    pd.testing.assert_series_equal(actual.iloc[:71], factor.compute(frame.iloc[:71]))


@pytest.mark.parametrize("number", sorted(DEFAULTS))
def test_every_input_invalid_resets_state_and_recovers_like_fresh_history(number):
    factor = get_factor(f"gtja191_{number:03}")()
    for field in INPUTS[number]:
        with pytest.raises(ValueError, match="缺少"):
            factor.compute(sample().drop(columns=field))
        for bad in (np.nan, np.inf, -1.0):
            frame = sample(145)
            frame.loc[45, field] = bad
            actual = factor.compute(frame)
            assert actual.iloc[45 : 45 + warmup(number, DEFAULTS[number])].isna().all()
            np.testing.assert_allclose(
                actual,
                independent(frame, number, DEFAULTS[number]),
                rtol=2e-9,
                atol=1e-9,
                equal_nan=True,
            )
            pd.testing.assert_series_equal(actual.iloc[46:], factor.compute(frame.iloc[46:]))
            assert np.isfinite(actual.iloc[-1])


@pytest.mark.parametrize("number", sorted(DEFAULTS))
def test_flat_zero_volume_empty_and_short_are_explicit(number):
    factor = get_factor(f"gtja191_{number:03}")()
    frame = sample(100)
    frame[["open", "close", "high", "low"]] = 10.0
    frame["volume"] = 0.0
    actual = factor.compute(frame)
    assert factor.compute(frame.iloc[:0]).empty
    assert factor.compute(frame.iloc[: warmup(number, DEFAULTS[number]) - 1]).isna().all()
    np.testing.assert_allclose(
        actual, independent(frame, number, DEFAULTS[number]), rtol=1e-10, atol=1e-10, equal_nan=True
    )
    assert not np.isinf(actual).any()


@pytest.mark.parametrize("filename", list(FILES))
def test_all_recursive_formulas_real_frozen_independent_values(filename):
    frame = qualify_factor_fields(
        frozen(filename), frozen(filename.rsplit("-", 1)[0] + "-NONE.json")
    )
    for n, w in DEFAULTS.items():
        actual = get_factor(f"gtja191_{n:03}")().compute(frame)
        np.testing.assert_allclose(
            actual,
            independent(frame, n, w),
            rtol=2e-9,
            atol=2e-7,
            equal_nan=True,
            err_msg=f"{filename}:{n}",
        )


def test_seed_m2_original_formula_and_nested_publication_hand_cases():
    pd.testing.assert_series_equal(
        _sma(pd.Series([3.0, 6.0, 9.0, 12.0]), 3, 1), pd.Series([np.nan, np.nan, 17 / 3, 70 / 9])
    )
    actual = configure_factor("gtja191_081", {"window": 3}).compute(
        pd.DataFrame({"volume": [3.0, 6.0, 9.0]})
    )
    assert actual.iloc[-1] == pytest.approx(23 / 3)  # 3 → 5 → 23/3, not adjusted EWM or m=1.
    close = pd.DataFrame({"close": [10.0] * 7})
    mixed = configure_factor("gtja191_173", {"window": 3}).compute(close)
    assert mixed.iloc[:6].isna().all()
    assert mixed.iloc[-1] == pytest.approx(10 + math.log(10))  # Third term is logarithmic.


def test_history_start_dependency_and_gap_reset_are_not_hidden():
    values = pd.Series([100.0] + [1.0] * 9 + [np.nan] + [1.0] * 6)
    full = _sma(values, 3, 1)
    short = _sma(values.iloc[1:10], 3, 1)
    assert full.iloc[9] != short.iloc[-1]
    assert full.iloc[10:13].isna().all()
    assert full.iloc[13] == 1
    assert "历史起点" in " ".join(describe_factor(get_factor("gtja191_081"))["limitations"])


def test_defaults_family_dedup_and_parameter_boundaries():
    assert {n: s.window for n, s in SPECS.items() if s.family.startswith("sma_")} == DEFAULTS
    for n in (9, 68, 81, 109, 122, 160, 173, 174, 188):
        with pytest.raises(ValueError, match="窗口"):
            configure_factor(f"gtja191_{n:03}", {"window": 1})
    for pair in ((9, 68), (24, 151), (47, 72), (63, 79)):
        with pytest.raises(ValueError, match="重复"):
            configured_selection(
                [f"gtja191_{n:03}" for n in pair], {f"gtja191_{n:03}": {"window": 7} for n in pair}
            )


@pytest.mark.parametrize("filename", list(FILES))
@pytest.mark.parametrize("window", [3, 7])
def test_custom_recursive_windows_on_all_frozen_inputs(filename, window):
    frame = qualify_factor_fields(
        frozen(filename), frozen(filename.rsplit("-", 1)[0] + "-NONE.json")
    )
    for n in DEFAULTS:
        actual = configure_factor(f"gtja191_{n:03}", {"window": window}).compute(frame)
        np.testing.assert_allclose(
            actual,
            independent(frame, n, window),
            rtol=2e-9,
            atol=2e-7,
            equal_nan=True,
            err_msg=f"{filename}:{n}:{window}",
        )


def test_zero_denominators_reset_derived_state_without_fake_values():
    frame = sample(100)
    frame.loc[45, "volume"] = 0
    for n in (9, 68):
        actual = get_factor(f"gtja191_{n:03}")().compute(frame)
        assert actual.iloc[45 : 45 + DEFAULTS[n]].isna().all()
        np.testing.assert_allclose(actual, independent(frame, n, DEFAULTS[n]), equal_nan=True)
    frame.loc[35:50, ["close", "high", "low"]] = 10.0
    for n in (47, 57, 72, 82, 96):
        actual = get_factor(f"gtja191_{n:03}")().compute(frame)
        assert actual.iloc[50 : 50 + DEFAULTS[n]].isna().all()
        assert np.isfinite(actual.iloc[-1])
        np.testing.assert_allclose(actual, independent(frame, n, DEFAULTS[n]), equal_nan=True)
    frame["close"] = 1.0
    assert get_factor("gtja191_122")().compute(frame).isna().all()


@pytest.mark.parametrize("number", sorted(DEFAULTS))
def test_cancel_inside_recursive_loop_does_not_return_partial_output(monkeypatch, number):
    from easy_tdx.computation import ComputationControl, ComputationStopped, computation_scope
    from easy_tdx.factor.builtin import gtja191

    control = ComputationControl()
    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 17:
            control.request()
        control.check()

    monkeypatch.setattr(gtja191, "computation_checkpoint", checkpoint)
    with pytest.raises(ComputationStopped), computation_scope(control):
        get_factor(f"gtja191_{number:03}")().compute(sample(100))
    assert calls == 17


@pytest.mark.parametrize("number", sorted(DEFAULTS))
def test_recursive_pool_alignment_and_independent_per_symbol_state(number):
    frames = {}
    for i in range(5):
        frame = sample(100).iloc[i * 3 :].copy()
        frame[["open", "high", "low", "close"]] *= 1 + i * 0.15
        frame["volume"] *= i + 1
        if i == 2:
            frame = frame.drop(frame.index[15:22])
        frames[f"asset-{i}"] = frame
    engine = FactorEngine()
    factor = get_factor(f"gtja191_{number:03}")()
    result = engine.compute_matrix(frames, factor)
    for name, frame in frames.items():
        expected = pd.Series(
            independent(frame, number, DEFAULTS[number]), index=pd.DatetimeIndex(frame.datetime)
        ).reindex(result.index)
        np.testing.assert_allclose(result[name], expected, rtol=2e-9, atol=1e-9, equal_nan=True)
    reversed_pool = dict(reversed(list(frames.items())))
    pd.testing.assert_frame_equal(
        result.sort_index(axis=1), engine.compute_matrix(reversed_pool, factor).sort_index(axis=1)
    )
