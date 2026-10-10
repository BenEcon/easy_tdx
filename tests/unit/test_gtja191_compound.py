"""Independent list algebra and closed-weight oracle for multi-window GTJA.

No production expressions, Spec defaults, warmup paths or rolling helpers are
used to derive expected values. Shared test-only SMA expands geometric weights.
"""

import math
import statistics

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.builtin.gtja191 import SPECS, _geometric_mean, _ts_rank
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from easy_tdx.factor.data import qualify_factor_fields
from tests.unit.test_factor_data import FILES, frozen
from tests.unit.test_gtja191 import sample
from tests.unit.test_gtja191_smoothing import rolling, shift, weighted

DEFAULTS = {
    27: dict(short=3, long=6, window=12),
    85: dict(volume_mean=20, volume_rank=20, price_lag=7, price_rank=8),
    89: dict(short=13, long=27, signal=10),
    111: dict(short=4, long=11),
    117: dict(volume_rank=32, price_rank=16, return_rank=32),
    145: dict(short=9, long=26, scale_window=12),
    152: dict(lag=9, smooth=9, short=12, long=26, signal=9),
    155: dict(short=13, long=27, signal=10),
    162: dict(smooth=12, lookback=12),
    164: dict(lookback=12, smooth=13),
    169: dict(smooth=9, short=12, long=26, signal=10),
    180: dict(volume_mean=20, price_lag=7, price_rank=60),
}
INPUTS = {
    **{n: ("close",) for n in (27, 89, 152, 162, 169)},
    **{n: ("volume",) for n in (145, 155)},
    **{n: ("close", "volume") for n in (85, 180)},
    **{n: ("close", "high", "low", "volume") for n in (111, 117)},
    164: ("close", "high", "low"),
}


def custom(n, size=3):
    return {k: size + 2 if k == "long" else size for k in DEFAULTS[n]}


def warmup(n, p):
    if n == 27:
        return p["long"] + p["window"]
    if n == 85:
        return max(p["volume_mean"] + p["volume_rank"] - 1, p["price_lag"] + p["price_rank"])
    if n in (89, 155):
        return p["long"] + p["signal"] - 1
    if n == 111:
        return p["long"]
    if n == 117:
        return max(p["volume_rank"], p["price_rank"], p["return_rank"] + 1)
    if n == 145:
        return max(p["long"], p["scale_window"])
    if n == 152:
        return p["lag"] + p["smooth"] + p["long"] + p["signal"]
    if n in (162, 164):
        return p["smooth"] + p["lookback"]
    if n == 169:
        return p["smooth"] + p["long"] + p["signal"]
    return max(p["volume_mean"], p["price_lag"] + p["price_rank"])


def rank(values, w):
    def current_position(a):
        positions = [i + 1 for i, value in enumerate(sorted(a)) if value == a[-1]]
        return statistics.mean(positions) / w

    return rolling(values, w, current_position)


def independent(frame, n, p):
    arrays = {k: frame[k].tolist() for k in INPUTS[n]}
    valid = [
        all(
            math.isfinite(a[i]) and (a[i] >= 0 if k == "volume" else a[i] > 0)
            for k, a in arrays.items()
        )
        for i in range(len(frame))
    ]
    if "high" in arrays:
        valid = [
            ok and arrays["low"][i] <= arrays["close"][i] <= arrays["high"][i]
            for i, ok in enumerate(valid)
        ]
    arrays = {k: [x if valid[i] else math.nan for i, x in enumerate(a)] for k, a in arrays.items()}
    c, h, l, v = (arrays.get(k) for k in ("close", "high", "low", "volume"))  # noqa: E741

    def apply(fn, *args):
        result = []
        for row in zip(*args):
            try:
                value = fn(*row) if all(math.isfinite(x) for x in row) else math.nan
                result.append(value if math.isfinite(value) else math.nan)
            except (ZeroDivisionError, OverflowError):
                result.append(math.nan)
        return result

    def diff(a, lag=1):
        return apply(lambda x, y: x - y, a, shift(a, lag))

    def mean(a, w):
        return rolling(a, w, statistics.fmean)

    if n == 27:
        raw = apply(
            lambda x, a, b: 100 * ((x - a) / a + (x - b) / b),
            c,
            shift(c, p["short"]),
            shift(c, p["long"]),
        )
        result = rolling(
            raw,
            p["window"],
            lambda a: math.fsum(x * 0.9**i for i, x in enumerate(reversed(a)))
            / math.fsum(0.9**i for i in range(len(a))),
        )
    elif n == 85:
        result = apply(
            lambda a, b: a * b,
            rank(apply(lambda a, b: a / b, v, mean(v, p["volume_mean"])), p["volume_rank"]),
            rank(apply(lambda x: -x, diff(c, p["price_lag"])), p["price_rank"]),
        )
    elif n in (89, 155):
        source = c if n == 89 else v
        delta = apply(
            lambda a, b: a - b, weighted(source, p["short"], 2), weighted(source, p["long"], 2)
        )
        result = apply(
            lambda a, b: (a - b) * (2 if n == 89 else 1), delta, weighted(delta, p["signal"], 2)
        )
    elif n == 111:
        raw = apply(lambda c, h, low, v: v * ((c - low) - (h - c)) / (h - low), c, h, l, v)
        result = apply(
            lambda a, b: a - b, weighted(raw, p["long"], 2), weighted(raw, p["short"], 2)
        )
    elif n == 117:
        result = apply(
            lambda a, b, c: a * (1 - b) * (1 - c),
            rank(v, p["volume_rank"]),
            rank(apply(lambda c, h, low: c + h - low, c, h, l), p["price_rank"]),
            rank(apply(lambda a, b: a / b - 1, c, shift(c)), p["return_rank"]),
        )
    elif n == 145:
        result = apply(
            lambda a, b, c: 100 * (a - b) / c,
            mean(v, p["short"]),
            mean(v, p["long"]),
            mean(v, p["scale_window"]),
        )
    elif n in (152, 169):
        raw = shift(apply(lambda a, b: a / b, c, shift(c, p["lag"]))) if n == 152 else diff(c)
        if n == 152:
            span = p["lag"] + 2
            raw = [
                x if i >= span - 1 and all(valid[i - span + 1 : i + 1]) else math.nan
                for i, x in enumerate(raw)
            ]
        inner = shift(weighted(raw, p["smooth"], 1))
        result = weighted(
            apply(lambda a, b: a - b, mean(inner, p["short"]), mean(inner, p["long"])),
            p["signal"],
            1,
        )
    elif n == 162:
        delta = diff(c)
        r = apply(
            lambda a, b: 100 * a / b,
            weighted(apply(lambda x: max(x, 0), delta), p["smooth"], 1),
            weighted(apply(abs, delta), p["smooth"], 1),
        )
        result = apply(
            lambda r, hi, lo: (r - lo) / (hi - lo),
            r,
            rolling(r, p["lookback"], max),
            rolling(r, p["lookback"], min),
        )
    elif n == 164:
        inverse = apply(lambda x: 1 / x if x > 0 else 1, diff(c))
        raw = apply(
            lambda a, b, h, low: 100 * (a - b) / (h - low),
            inverse,
            rolling(inverse, p["lookback"], min),
            h,
            l,
        )
        result = weighted(raw, p["smooth"], 2)
    else:
        delta = diff(c, p["price_lag"])
        position = rank(apply(abs, delta), p["price_rank"])
        # Do not demand a finite unused branch, but keep full input warmup.
        result = [
            -r * ((d > 0) - (d < 0)) if math.isfinite(avg) and vol > avg else -vol
            for r, d, vol, avg in zip(position, delta, v, mean(v, p["volume_mean"]))
        ]
    span = warmup(n, p)
    return [
        x if i >= span - 1 and all(valid[i - span + 1 : i + 1]) else math.nan
        for i, x in enumerate(result)
    ]


def assert_values(actual, expected):
    np.testing.assert_allclose(actual, expected, rtol=3e-8, atol=3e-10, equal_nan=True)


@pytest.mark.parametrize("n", sorted(DEFAULTS))
@pytest.mark.parametrize("size", [None, 3, 7])
def test_independent_compound_values_and_future_prefix(n, size):
    p = DEFAULTS[n] if size is None else custom(n, size)
    factor = configure_factor(f"gtja191_{n:03d}", p)
    frame = sample(180)
    actual = factor.compute(frame)
    assert_values(actual, independent(frame, n, p))
    assert factor.spec.warmup == warmup(n, p)
    assert actual.iloc[: warmup(n, p) - 1].isna().all()
    assert actual.iloc[warmup(n, p) - 1 :].notna().any()
    for end in [1, warmup(n, p) - 1, warmup(n, p), 95, 140]:
        assert_values(factor.compute(frame.iloc[:end]), actual.iloc[:end])


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_all_compound_inputs_missing_invalid_and_recovery(n):
    factor = configure_factor(f"gtja191_{n:03d}", custom(n))
    frame = sample(150)
    for key in INPUTS[n]:
        with pytest.raises(ValueError, match="缺少字段"):
            factor.compute(frame.drop(columns=key))
        for value in [math.nan, math.inf, -1]:
            damaged = frame.copy()
            damaged.loc[45, key] = value
            actual = factor.compute(damaged)
            assert_values(actual, independent(damaged, n, custom(n)))
            assert actual.iloc[45 : 45 + factor.spec.warmup].isna().all()
            assert_values(actual.iloc[46:], factor.compute(damaged.iloc[46:]))


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_compound_empty_short_constant_and_zero_volume(n):
    factor = configure_factor(f"gtja191_{n:03d}")
    frame = sample(100)
    assert factor.compute(frame.iloc[:0]).empty
    assert factor.compute(frame.iloc[: factor.spec.warmup - 1]).isna().all()
    for volume in [0.0, 200.0]:
        frame.loc[:, ["open", "close", "high", "low"]] = [10.0, 10.0, 11.0, 9.0]
        frame["volume"] = volume
        actual = factor.compute(frame)
        assert not np.isinf(actual.to_numpy()).any()
        if n == 162:
            assert actual.isna().all()
        elif n not in (89, 111, 155, 152, 169):
            assert_values(actual, independent(frame, n, DEFAULTS[n]))
        else:
            assert_values(
                actual,
                np.r_[
                    np.full(factor.spec.warmup - 1, np.nan),
                    np.zeros(len(frame) - factor.spec.warmup + 1),
                ],
            )


@pytest.mark.parametrize("filename", FILES)
def test_compound_all_real_frozen_defaults_and_custom(filename):
    raw = frozen(filename)
    frame = qualify_factor_fields(
        raw, frozen(filename.replace("-QFQ", "-NONE").replace("-HFQ", "-NONE"))
    )
    for n in DEFAULTS:
        for p in [DEFAULTS[n], custom(n), custom(n, 7)]:
            actual = configure_factor(f"gtja191_{n:03d}", p).compute(frame)
            assert_values(actual, independent(frame, n, p))


def test_rank_ties_complete_windows_and_exponential_weight_hand_cases():
    assert_values(
        _ts_rank(pd.Series([2.0, 1.0, 2.0, 3.0, 3.0]), 3), [np.nan, np.nan, 5 / 6, 1, 5 / 6]
    )
    assert_values(_ts_rank(pd.Series([7.0, 7.0, 7.0]), 3), [np.nan, np.nan, 2 / 3])
    assert_values(_ts_rank(pd.Series([1.0, np.nan, 2.0, 3.0, 4.0]), 3), [np.nan] * 4 + [1])
    assert _ts_rank(pd.Series([8.0]), 1).iloc[0] == 1
    assert _geometric_mean(pd.Series([1.0, 2.0, 4.0]), 3).iloc[-1] == pytest.approx(
        (0.81 + 1.8 + 4) / 2.71
    )
    assert _geometric_mean(pd.Series([1.0, 2.0, 4.0]), 3).iloc[-1] != pytest.approx(
        (1 + 4 + 12) / 6
    )


def test_named_parameters_metadata_limits_no_default_mutation():
    from tests.unit.test_gtja191_conditional import DEFAULTS as CONDITIONAL_DEFAULTS

    assert {n for n, s in SPECS.items() if s.windows and not s.panel} == set(DEFAULTS) | set(
        CONDITIONAL_DEFAULTS
    ) | {26, 154}
    for n, p in DEFAULTS.items():
        name = f"gtja191_{n:03d}"
        cls = get_factor(name)
        assert cls.spec.resolved_parameters == p
        configure_factor(name, custom(n))
        metadata = describe_factor(cls, custom(n))
        assert metadata["warmup_bars"] == warmup(n, custom(n))
        assert metadata["resolved_parameters"] == custom(n)
        assert cls.spec.resolved_parameters == p
        assert metadata["parameters"].keys() == p.keys()
        for key in p:
            for bad in [True, None, 1.5, 0, -1, 601, "3"]:
                with pytest.raises(ValueError):
                    configure_factor(name, {key: bad})
        with pytest.raises(ValueError):
            configure_factor(name, {"unknown": 3})
        with pytest.raises(ValueError, match="重复"):
            configured_selection([name, name])
    with pytest.raises(ValueError, match="短窗口"):
        configure_factor("gtja191_089", dict(short=27))
    with pytest.raises(ValueError, match="600"):
        configure_factor("gtja191_152", dict(lag=300, long=300))
    assert configure_factor("gtja191_027", dict(window=2)).spec.warmup == 8
    # Minimum m=2 is enforced, including individually edited secondary windows.
    with pytest.raises(ValueError):
        configure_factor("gtja191_089", dict(signal=1))


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_compound_pool_per_symbol_state_and_date_alignment(n):
    frames = {}
    for i in range(5):
        frame = sample(150).iloc[i * 3 :].copy()
        frame.index = pd.date_range("2025-01-01", periods=150)[i * 3 :]
        frame[["open", "close", "high", "low"]] *= i + 1
        frame["volume"] *= i + 2
        frames[str(i)] = frame.drop(frame.index[[30 + i, 55 + i]])
    factor = configure_factor(f"gtja191_{n:03d}", custom(n))
    result = FactorEngine().compute_matrix(frames, factor)
    for code, frame in frames.items():
        expected = pd.Series(independent(frame, n, custom(n)), index=frame.index)
        assert_values(result[code], expected.reindex(result.index))
    reversed_result = FactorEngine().compute_matrix(dict(reversed(list(frames.items()))), factor)
    pd.testing.assert_frame_equal(result, reversed_result.reindex(columns=result.columns))


def test_compound_original_parallel_smoothing_and_history_start():
    frame = sample(100)
    for n, field in [(89, "close"), (155, "volume")]:
        p = custom(n)
        actual = configure_factor(f"gtja191_{n:03d}", p).compute(frame)
        a = np.array(weighted(frame[field], p["short"], 2))
        wrong = a - np.array(weighted(a, p["long"], 2))
        wrong = (wrong - np.array(weighted(wrong, p["signal"], 2))) * (2 if n == 89 else 1)
        assert not np.allclose(actual.iloc[30:], wrong[30:])
    factor = get_factor("gtja191_152")()
    assert factor.compute(frame).iloc[-1] != factor.compute(frame.iloc[15:]).iloc[-1]


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_each_named_window_partial_override_and_definition_fingerprint(n):
    name = f"gtja191_{n:03d}"
    cls = get_factor(name)
    frame = sample(160)
    baseline = describe_factor(cls)
    for key, default in DEFAULTS[n].items():
        parameters = {key: default + 1}
        effective = DEFAULTS[n] | parameters
        factor = configure_factor(name, parameters)
        assert_values(factor.compute(frame), independent(frame, n, effective))
        definition = describe_factor(cls, parameters)
        assert definition["formula_sha256"] != baseline["formula_sha256"]
        assert definition["resolved_parameters"] == effective
        assert definition["warmup_bars"] == warmup(n, effective)
    assert describe_factor(cls) == baseline


@pytest.mark.parametrize("n", [111, 164])
def test_zero_price_range_resets_compound_smoothing(n):
    frame = sample(160)
    factor = configure_factor(f"gtja191_{n:03d}", custom(n))
    frame.loc[50, ["open", "close", "high", "low"]] = 12.0
    actual = factor.compute(frame)
    assert_values(actual, independent(frame, n, custom(n)))
    # Even with valid OHLC, a zero derived denominator must reset the SMA.
    assert actual.iloc[50 : 50 + custom(n).get("smooth", custom(n).get("long"))].isna().all()
    assert actual.iloc[-1] == pytest.approx(independent(frame, n, custom(n))[-1])


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_compound_cancellation_no_partial_success(monkeypatch, n):
    from easy_tdx.factor.builtin import gtja191

    class Cancelled(BaseException):
        pass

    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == (2 if n == 145 else 4):
            raise Cancelled()

    monkeypatch.setattr(gtja191, "computation_checkpoint", checkpoint)
    with pytest.raises(Cancelled):
        configure_factor(f"gtja191_{n:03d}", custom(n)).compute(sample(100))
