"""Independent scalar arithmetic oracle, not production-generated expectations."""

from __future__ import annotations

import math
import statistics
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.builtin.gtja191 import SPECS
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from easy_tdx.factor.data import qualify_factor_fields
from tests.unit.test_factor_data import FILES, frozen

# Separate transcription of the defaults verified on report pp.11-17.
DEFAULTS = {
    2: 1,
    3: 6,
    6: 4,
    11: 6,
    14: 5,
    15: 1,
    18: 5,
    19: 5,
    20: 6,
    29: 6,
    31: 12,
    34: 12,
    43: 6,
    46: 3,
    53: 12,
    58: 20,
    59: 20,
    60: 20,
    65: 6,
    66: 6,
    71: 24,
    80: 5,
    84: 20,
    88: 20,
    94: 30,
    97: 10,
    100: 20,
    106: 20,
    110: 20,
    118: 20,
    126: None,
    129: 12,
    134: 12,
    150: None,
    153: 3,
    161: 12,
    167: 12,
    168: 20,
    175: 6,
    178: 1,
    185: None,
    187: 20,
    189: 6,
    21: 6,
    40: 26,
    49: 12,
    50: 12,
    51: 12,
    52: 26,
    69: 20,
    76: 20,
    86: 10,
    93: 20,
    103: 20,
    112: 12,
    116: 20,
    127: 12,
    128: 14,
    133: 20,
    139: 10,
    147: 12,
    158: None,
    171: None,
    177: 20,
    191: 20,
}
SERIES = [n for n in DEFAULTS if n not in {6, 185}]


def sample(size=90):
    rng = np.random.default_rng(713)
    close = 20 + np.cumsum(rng.normal(0, 0.2, size))
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2025-01-01", periods=size),
            "close": close,
            "open": close + rng.uniform(-0.4, 0.4, size),
            "high": close + rng.uniform(0.5, 1, size),
            "low": close - rng.uniform(0.5, 1, size),
            "volume": rng.integers(10, 200, size).astype(float),
        }
    )


def oracle_arrays(df):
    return {
        key: df[key].to_numpy() for key in ("close", "open", "high", "low", "volume") if key in df
    }


def scalar(d, n, t, override=None):
    w = override if override is not None else DEFAULTS[n]
    w = w or 1
    warmup = (
        8 * w
        if n in {46, 153}
        else 2 * w - 1
        if n in {21, 127, 147, 189}
        else 2 * w + 1
        if n == 86
        else w + 4
        if n == 191
        else w + 1
        if n
        in {
            2,
            3,
            14,
            15,
            18,
            19,
            20,
            29,
            43,
            53,
            58,
            59,
            80,
            84,
            88,
            94,
            106,
            110,
            129,
            134,
            161,
            167,
            175,
            178,
            187,
            40,
            49,
            50,
            51,
            52,
            69,
            76,
            93,
            112,
            128,
        }
        else w
    )
    if t < warmup - 1:
        return math.nan
    c, o, h, lo, v = (d.get(k) for k in ("close", "open", "high", "low", "volume"))

    def avg(array, end, length):
        return math.fsum(array[end - length + 1 : end + 1]) / length

    def total(fn):
        return math.fsum(fn(i) for i in range(t - w + 1, t + 1))

    def ratio(a, b):
        return a / b if b else math.nan

    if n == 2:

        def loc(i):
            return ratio(2 * c[i] - h[i] - lo[i], h[i] - lo[i])

        return loc(t - w) - loc(t)
    if n in {3, 59}:

        def flow(i):
            if c[i] == c[i - 1]:
                return 0
            return c[i] - (min(lo[i], c[i - 1]) if c[i] > c[i - 1] else max(h[i], c[i - 1]))

        return total(flow)
    if n in {11, 60}:
        return total(lambda i: ratio(2 * c[i] - h[i] - lo[i], h[i] - lo[i]) * v[i])
    if n in {14, 106}:
        return c[t] - c[t - w]
    if n == 15:
        return o[t] / c[t - w] - 1
    if n == 18:
        return c[t] / c[t - w]
    if n == 19:
        return (
            (c[t] - c[t - w]) / c[t - w]
            if c[t] < c[t - w]
            else 0
            if c[t] == c[t - w]
            else (c[t] - c[t - w]) / c[t]
        )
    if n in {20, 88}:
        return 100 * (c[t] - c[t - w]) / c[t - w]
    if n in {29, 134, 178}:
        return (c[t] - c[t - w]) / c[t - w] * v[t]
    if n in {31, 66, 71}:
        return 100 * (c[t] - avg(c, t, w)) / avg(c, t, w)
    if n in {34, 65}:
        return avg(c, t, w) / c[t]
    if n in {43, 84, 94}:
        return total(lambda i: (1 if c[i] > c[i - 1] else -1 if c[i] < c[i - 1] else 0) * v[i])
    if n in {46, 153}:
        value = math.fsum(avg(c, t, length) for length in (w, 2 * w, 4 * w, 8 * w)) / 4
        return value / c[t] if n == 46 else value
    if n in {53, 58}:
        return 100 * total(lambda i: int(c[i] > c[i - 1])) / w
    if n == 80:
        return ratio(v[t] - v[t - w], v[t - w]) * 100
    if n in {97, 100}:
        return statistics.stdev(v[t - w + 1 : t + 1])
    if n == 110:
        return (
            ratio(
                total(lambda i: max(h[i] - c[i - 1], 0)), total(lambda i: max(c[i - 1] - lo[i], 0))
            )
            * 100
        )
    if n == 118:
        return ratio(total(lambda i: h[i] - o[i]), total(lambda i: o[i] - lo[i])) * 100
    if n == 126:
        return (c[t] + h[t] + lo[t]) / 3
    if n == 129:
        return total(lambda i: abs(c[i] - c[i - 1]) if c[i] < c[i - 1] else 0)
    if n == 150:
        return (c[t] + h[t] + lo[t]) / 3 * v[t]
    if n in {161, 175}:
        return total(lambda i: max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))) / w
    if n == 167:
        return total(lambda i: c[i] - c[i - 1] if c[i] > c[i - 1] else 0)
    if n == 168:
        return ratio(-v[t], avg(v, t, w))
    if n == 187:
        return total(lambda i: 0 if o[i] <= o[i - 1] else max(h[i] - o[i], o[i] - o[i - 1]))
    if n == 189:
        return total(lambda i: abs(c[i] - avg(c, i, w))) / w
    if n in {21, 116, 147}:
        y = [avg(c, i, w) if n != 116 else c[i] for i in range(t - w + 1, t + 1)]
        mean_y = math.fsum(y) / w
        mean_x = (w + 1) / 2
        return math.fsum((i + 1 - mean_x) * (v - mean_y) for i, v in enumerate(y)) / math.fsum(
            (i + 1 - mean_x) ** 2 for i in range(w)
        )
    if n == 40:
        return 100 * ratio(
            total(lambda i: v[i] if c[i] > c[i - 1] else 0),
            total(lambda i: v[i] if c[i] <= c[i - 1] else 0),
        )
    if n in {49, 50, 51}:

        def direction(i):
            return (
                Decimal(str(h[i]))
                + Decimal(str(lo[i]))
                - Decimal(str(h[i - 1]))
                - Decimal(str(lo[i - 1]))
            )

        up = total(
            lambda i: max(abs(h[i] - h[i - 1]), abs(lo[i] - lo[i - 1])) if direction(i) > 0 else 0
        )
        down = total(
            lambda i: max(abs(h[i] - h[i - 1]), abs(lo[i] - lo[i - 1])) if direction(i) < 0 else 0
        )
        return ratio(down if n == 49 else up - down if n == 50 else up, up + down)
    if n == 52:
        return 100 * ratio(
            total(lambda i: max(h[i] - (h[i - 1] + lo[i - 1] + c[i - 1]) / 3, 0)),
            total(lambda i: max((h[i - 1] + lo[i - 1] + c[i - 1]) / 3 - lo[i], 0)),
        )
    if n in {69, 93}:
        down = total(lambda i: max(o[i] - lo[i], o[i] - o[i - 1]) if o[i] < o[i - 1] else 0)
        if n == 93:
            return down
        up = total(lambda i: max(h[i] - o[i], o[i] - o[i - 1]) if o[i] > o[i - 1] else 0)
        return (up - down) / up if up > down else 0 if up == down else (up - down) / down
    if n == 76:
        values = [ratio(abs(c[i] / c[i - 1] - 1), v[i]) for i in range(t - w + 1, t + 1)]
        if not all(math.isfinite(a) for a in values):
            return math.nan
        return ratio(statistics.stdev(values), statistics.mean(values))
    if n == 86:
        change = Decimal(str(c[t - 2 * w])) - 2 * Decimal(str(c[t - w])) + Decimal(str(c[t]))
        return -1 if change > Decimal("0.25") * w else 1 if change < 0 else c[t - 1] - c[t]
    if n in {103, 133, 177}:

        def age(a, choose):
            part = a[t - w + 1 : t + 1]
            extreme = choose(part)
            return next(distance for distance in range(w) if a[t - distance] == extreme)

        if n == 103:
            return (w - age(lo, min)) / w * 100
        if n == 177:
            return (w - age(h, max)) / w * 100
        return (age(lo, min) - age(h, max)) / w * 100
    if n == 112:
        up = total(lambda i: c[i] - c[i - 1] if c[i] > c[i - 1] else 0)
        down = total(lambda i: c[i - 1] - c[i] if c[i] < c[i - 1] else 0)
        return 100 * ratio(up - down, up + down)
    if n == 127:
        return math.sqrt(
            total(
                lambda i: (100 * (c[i] - max(c[i - w + 1 : i + 1])) / max(c[i - w + 1 : i + 1]))
                ** 2
            )
            / w
        )
    if n == 128:
        typical = [(a + b + x) / 3 for a, b, x in zip(h, lo, c)]
        exact = [Decimal(str(a)) + Decimal(str(b)) + Decimal(str(x)) for a, b, x in zip(h, lo, c)]
        up = total(lambda i: typical[i] * v[i] if exact[i] > exact[i - 1] else 0)
        down = total(lambda i: typical[i] * v[i] if exact[i] < exact[i - 1] else 0)
        return 100 - 100 / (1 + up / down) if down else math.nan
    if n in {139, 191}:

        def correlation(x, y):
            # Independent scalar moments, no production rolling helper.
            xm, ym = statistics.mean(x), statistics.mean(y)
            numerator = math.fsum((a - xm) * (b - ym) for a, b in zip(x, y))
            denominator = math.sqrt(
                math.fsum((a - xm) ** 2 for a in x) * math.fsum((b - ym) ** 2 for b in y)
            )
            return ratio(numerator, denominator)

        if n == 139:
            return -correlation(o[t - w + 1 : t + 1], v[t - w + 1 : t + 1])
        return (
            correlation([avg(v, i, w) for i in range(t - 4, t + 1)], lo[t - 4 : t + 1])
            + (h[t] + lo[t]) / 2
            - c[t]
        )
    if n == 158:
        # Use the original two equal smoothing terms, not simplified production code.
        smoothed = c[0]
        for close in c[1 : t + 1]:
            smoothed = (2 * close + 13 * smoothed) / 15
        return ((h[t] - smoothed) - (lo[t] - smoothed)) / c[t]
    if n == 171:
        return ratio(-(lo[t] - c[t]) * o[t] ** 5, (c[t] - h[t]) * c[t] ** 5)
    raise AssertionError(n)


def test_exact_implemented_set_and_default_parameters():
    # Recursive formulas have a separate closed-geometric-weight oracle suite.
    assert {
        n for n, s in SPECS.items() if not s.family.startswith(("sma_", "compound_", "panel_"))
    } == set(DEFAULTS)
    for n, w in DEFAULTS.items():
        assert SPECS[n].window == w
        assert SPECS[n].panel == (n in {6, 185})


def test_alpha006_decimal_equal_weighted_prices_remain_tied():
    data = {
        s: pd.DataFrame(
            {
                "datetime": pd.date_range("2025-01-01", periods=5),
                "open": [10.0] * 4 + [last],
                "high": [12.0] * 4 + [11.83],
            }
        )
        for s, last in {"flat": 10.03, "up": 10.04, "down": 10.02}.items()
    }
    result = FactorEngine().compute_matrix(data, get_factor("gtja191_006")())
    assert result.iloc[-1].to_dict() == pytest.approx({"flat": -2 / 3, "up": -1, "down": -1 / 3})


@pytest.mark.parametrize(
    "number,window",
    [(n, w) for n in SERIES for w in ([None, 3, 7] if DEFAULTS[n] is not None else [None])],
)
def test_all_rows_independent_arithmetic_and_future_invariance(number, window):
    frame = sample()
    factor = configure_factor(f"gtja191_{number:03d}", {"window": window} if window else {})
    actual = factor.compute(frame)
    expected = [scalar(oracle_arrays(frame), number, i, window) for i in range(len(frame))]
    np.testing.assert_allclose(actual, expected, rtol=2e-10, atol=1e-10, equal_nan=True)
    pd.testing.assert_series_equal(actual.iloc[:65], factor.compute(frame.iloc[:65]))


@pytest.mark.parametrize("number", SERIES)
def test_declared_missing_invalid_fields_break_window_and_recover(number):
    factor = get_factor(f"gtja191_{number:03d}")()
    for field in factor.inputs:
        with pytest.raises(ValueError, match="缺少"):
            factor.compute(sample().drop(columns=field))
        for invalid in (np.nan, np.inf, -1.0):
            frame = sample(120)
            frame.loc[45, field] = invalid
            actual = factor.compute(frame)
            assert actual.iloc[45 : 45 + factor.spec.warmup].isna().all()
            assert np.isfinite(actual.iloc[-1])


@pytest.mark.parametrize("number", SERIES)
def test_constant_flat_zero_volume_and_short_inputs(number):
    factor = get_factor(f"gtja191_{number:03d}")()
    frame = sample(90)
    frame[["open", "close", "high", "low"]] = 10.0
    frame["volume"] = 0.0
    actual = factor.compute(frame)
    assert not np.isinf(actual).any()
    assert factor.compute(frame.iloc[:0]).empty
    assert factor.compute(frame.iloc[: max(0, factor.spec.warmup - 1)]).isna().all()
    if number in {2, 11, 60, 80, 110, 118, 168, 40, 49, 50, 51, 52, 76, 112, 128, 139, 171, 191}:
        assert actual.isna().all()
    else:
        expected = scalar(oracle_arrays(frame), number, len(frame) - 1)
        assert actual.iloc[-1] == pytest.approx(expected)


@pytest.mark.parametrize("filename", list(FILES))
def test_all_supported_series_real_frozen_rows(filename):
    raw = frozen(filename.rsplit("-", 1)[0] + "-NONE.json")
    frame = qualify_factor_fields(frozen(filename), raw)
    arrays = oracle_arrays(frame)
    for number in SERIES:
        actual = get_factor(f"gtja191_{number:03d}")().compute(frame)
        expected = [scalar(arrays, number, i) for i in range(len(frame))]
        np.testing.assert_allclose(
            actual, expected, rtol=2e-9, atol=2e-7, equal_nan=True, err_msg=f"{filename}:{number}"
        )


@pytest.mark.parametrize("number", [6, 185])
def test_whole_pool_rank_hand_oracle_ties_missing_and_append(number):
    data = {str(i): sample(20) for i in range(5)}
    for i, frame in enumerate(data.values()):
        frame["open"] += (i - 2) * 0.015 * np.sin(np.arange(20) * i)
        frame["high"] += i * 0.02
    data["2"].loc[12, "open"] = np.nan
    factor = get_factor(f"gtja191_{number:03d}")()
    actual = FactorEngine().compute_matrix(data, factor)
    for t in range(20):
        vals = {}
        for symbol, frame in data.items():
            if number == 6:
                if t < 4 or frame.open.iloc[t - 4 : t + 1].isna().any():
                    continue
                now = 0.85 * frame.open.iloc[t] + 0.15 * frame.high.iloc[t]
                prev = 0.85 * frame.open.iloc[t - 4] + 0.15 * frame.high.iloc[t - 4]
                vals[symbol] = 1 if now > prev else -1 if now < prev else 0
            elif pd.notna(frame.open.iloc[t]):
                vals[symbol] = -((1 - frame.open.iloc[t] / frame.close.iloc[t]) ** 2)
        for symbol in data:
            if symbol not in vals:
                assert np.isnan(actual.iloc[t][symbol])
                continue
            ordinal = (
                sum(v < vals[symbol] for v in vals.values())
                + (sum(v == vals[symbol] for v in vals.values()) + 1) / 2
            )
            assert actual.iloc[t][symbol] == pytest.approx(
                ordinal / len(vals) * (-1 if number == 6 else 1)
            )
    prefix = FactorEngine().compute_matrix({s: f.iloc[:15] for s, f in data.items()}, factor)
    pd.testing.assert_frame_equal(actual.iloc[:15], prefix)
    with pytest.raises(ValueError, match="股票池"):
        factor.compute(data["0"])


def test_parameter_validation_identity_metadata_and_no_mutation():
    for bad in (0, -1, True, 3.2, 601):
        with pytest.raises(ValueError):
            configure_factor("gtja191_014", {"window": bad})
    for name, params in [
        ("gtja191_126", {"window": 3}),
        ("gtja191_014", {"oops": 3}),
        ("gtja191_046", {"window": 76}),
        ("gtja191_097", {"window": 1}),
    ]:
        with pytest.raises(ValueError):
            configure_factor(name, params)
    with pytest.raises(ValueError, match="重复"):
        configured_selection(["gtja191_014", "gtja191_106"], {"gtja191_106": {"window": 5}})
    with pytest.raises(ValueError, match="重复"):
        configured_selection(["gtja191_065", "alpha158_ma5"], {"alpha158_ma5": {"window": 6}})
    assert get_factor("gtja191_014")().spec.window == 5
    for n in DEFAULTS:
        definition = describe_factor(get_factor(f"gtja191_{n:03d}"))
        assert definition["library"] == "gtja191"
        assert definition["available"] == (n not in {6, 185})
        assert definition["evaluation_available"]
        assert definition["implementation_source_available"]
        assert len(definition["formula_sha256"]) == 64


@pytest.mark.parametrize("number", [6, 185])
@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_panel_real_frozen_three_stock_oracle(number, adjust):
    data = {
        symbol: frozen(f"{prefix}-DAILY-{adjust}.json")
        for symbol, prefix in [
            ("SZ:000001", "0-000001"),
            ("SZ:300750", "0-300750"),
            ("SH:600036", "1-600036"),
        ]
    }
    actual = FactorEngine().compute_matrix(data, get_factor(f"gtja191_{number:03d}")())
    records = {s: dict(zip(f.datetime, f.to_dict("records"))) for s, f in data.items()}
    dates = list(actual.index)
    for t, date in enumerate(dates):
        available = {}
        for symbol, rows in records.items():
            if date not in rows:
                continue
            row = rows[date]
            if number == 6:
                if t < 4 or any(d not in rows for d in dates[t - 4 : t + 1]):
                    continue
                prior = rows[dates[t - 4]]
                difference = 0.85 * (row["open"] - prior["open"]) + 0.15 * (
                    row["high"] - prior["high"]
                )
                available[symbol] = 1 if difference > 0 else -1 if difference < 0 else 0
            else:
                available[symbol] = -((1 - row["open"] / row["close"]) ** 2)
        for symbol in data:
            if symbol not in available or len(available) < 2:
                assert np.isnan(actual.loc[date, symbol])
                continue
            value = available[symbol]
            rank = (
                sum(v < value for v in available.values())
                + (sum(v == value for v in available.values()) + 1) / 2
            ) / len(available)
            assert actual.loc[date, symbol] == pytest.approx(rank * (-1 if number == 6 else 1))
