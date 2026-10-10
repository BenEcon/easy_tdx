"""Independent exact-rational branches and scalar/list formulas, report pp11–17.

Expected definitions/windows are transcribed here, not derived from Spec or the
production kernels. Smoothing oracle expands closed geometric weights.
"""

import math
import statistics
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor
from easy_tdx.factor.data import qualify_factor_fields
from tests.unit.test_factor_data import FILES, frozen
from tests.unit.test_gtja191 import sample
from tests.unit.test_gtja191_smoothing import rolling, shift, weighted

DEFAULTS = {
    4: dict(mean=8, fast=2, volume_mean=20),
    5: dict(rank=5, corr=5, peak=3),
    22: dict(mean=6, lag=3, smooth=12),
    23: dict(std=20, smooth=20),
    38: dict(mean=20, lag=2),
    55: dict(lag=1, window=20),
    70: dict(window=6),
    78: dict(mean=12, deviation=12),
    95: dict(window=20),
    98: dict(mean=100, lag=100, trough=100, change=3),
    132: dict(window=20),
    137: dict(lag=1),
    144: dict(window=20),
    172: dict(direction=14, smooth=6),
    186: dict(direction=14, smooth=6, lag=6),
}
INPUTS = {
    4: ("close", "volume"),
    5: ("high", "volume"),
    **{n: ("close",) for n in (22, 23, 98)},
    38: ("high",),
    **{n: ("open", "close", "high", "low") for n in (55, 137)},
    **{n: ("amount",) for n in (70, 95, 132)},
    **{n: ("close", "high", "low") for n in (78, 172, 186)},
    144: ("close", "amount"),
}


def custom(n, size=3):
    return {k: size for k in DEFAULTS[n]}


def warmup(n, p):
    if n == 4:
        return max(p.values())
    if n == 5:
        return p["rank"] + p["corr"] + p["peak"] - 2
    if n == 22:
        return p["mean"] + p["lag"] + p["smooth"] - 1
    if n == 23:
        return p["std"] + p["smooth"] - 1
    if n == 38:
        return max(p["mean"], p["lag"] + 1)
    if n == 55:
        return p["lag"] + p["window"]
    if n == 78:
        return p["mean"] + p["deviation"] - 1
    if n == 98:
        return max(p["mean"] + p["lag"], p["trough"], p["change"] + 1)
    if n == 137:
        return p["lag"] + 1
    if n == 144:
        return p["window"] + 1
    if n in (172, 186):
        return p["direction"] + p["smooth"] + p.get("lag", 0)
    return p["window"]


def data(size=320):
    frame = sample(size)
    frame["amount"] = frame.volume * (frame.high + frame.low) / 2
    return frame


def independent(frame, n, p):
    arrays = {k: frame[k].tolist() for k in INPUTS[n]}
    valid = [
        all(
            math.isfinite(a[i]) and (a[i] >= 0 if k in {"volume", "amount"} else a[i] > 0)
            for k, a in arrays.items()
        )
        for i in range(len(frame))
    ]
    for i in range(len(frame)):
        row = {k: a[i] for k, a in arrays.items()}
        valid[i] &= row.get("low", 0) <= row.get("high", math.inf)
        for key in ("open", "close"):
            if key in row:
                valid[i] &= row.get("low", 0) <= row[key] <= row.get("high", math.inf)
    arrays = {k: [x if valid[i] else math.nan for i, x in enumerate(a)] for k, a in arrays.items()}
    c, h, l, o, v, amount = (  # noqa: E741
        arrays.get(k) for k in ("close", "high", "low", "open", "volume", "amount")
    )

    def apply(fn, *args):
        out = []
        for row in zip(*args):
            try:
                value = fn(*row) if all(math.isfinite(x) for x in row) else math.nan
                out.append(float(value) if math.isfinite(value) else math.nan)
            except (ZeroDivisionError, OverflowError):
                out.append(math.nan)
        return out

    def mean(a, w):
        return rolling(a, w, statistics.fmean)

    def diff(a, lag=1):
        return apply(lambda x, y: x - y, a, shift(a, lag))

    def rational(a):
        return [Fraction(str(x)) for x in a]

    span = warmup(n, p)
    if n in (4, 38, 98):
        result = [math.nan] * len(frame)
        for i in range(span - 1, len(frame)):
            if not all(valid[i - span + 1 : i + 1]):
                continue
            # Only use complete trailing dependencies; earlier gaps are irrelevant.
            start = i - span + 1
            x = rational((h if n == 38 else c)[start : i + 1])
            average = sum(x[-p["mean"] :]) / p["mean"]
            if n == 4:
                delta = sum(x[-p["fast"] :]) / p["fast"] - average
                variance = sum((z - average) ** 2 for z in x[-p["mean"] :]) / (p["mean"] - 1)
                vols = rational(v[i - p["volume_mean"] + 1 : i + 1])
                result[i] = (
                    (-1 if delta > 0 else 1)
                    if delta**2 > variance
                    else (int(vols[-1] >= sum(vols) / len(vols)) * 2 - 1 if sum(vols) else math.nan)
                )
            elif n == 38:
                result[i] = float(x[-p["lag"] - 1] - x[-1]) if x[-1] > average else 0
            else:
                old_average = sum(x[-p["lag"] - p["mean"] : -p["lag"]]) / p["mean"]
                low_growth = (average - old_average) / x[-p["lag"] - 1] <= Fraction(1, 20)
                result[i] = float(
                    min(x[-p["trough"] :]) - x[-1] if low_growth else x[-p["change"] - 1] - x[-1]
                )
    elif n == 5:

        def rank(a):
            return rolling(
                a,
                p["rank"],
                lambda x: (sum(z < x[-1] for z in x) + (sum(z == x[-1] for z in x) + 1) / 2)
                / len(x),
            )

        a, b = rank(v), rank(h)
        corr = []
        for i in range(len(frame)):
            x, y = a[max(0, i - p["corr"] + 1) : i + 1], b[max(0, i - p["corr"] + 1) : i + 1]
            corr.append(
                statistics.correlation(x, y)
                if len(x) == p["corr"]
                and all(math.isfinite(z) for z in x + y)
                and len(set(x)) > 1
                and len(set(y)) > 1
                else math.nan
            )
        result = apply(lambda z: -z, rolling(corr, p["peak"], max))
    elif n == 22:
        average = mean(c, p["mean"])
        raw = apply(lambda x, y: (x - y) / y, c, average)
        result = weighted(diff(raw, p["lag"]), p["smooth"], 1)
    elif n == 23:
        std = rolling(c, p["std"], statistics.stdev)
        up = apply(lambda s, delta: s if delta > 0 else 0, std, diff(c))
        down = apply(lambda s, delta: s if delta <= 0 else 0, std, diff(c))
        result = apply(
            lambda u, d: 100 * u / (u + d),
            weighted(up, p["smooth"], 1),
            weighted(down, p["smooth"], 1),
        )
    elif n in (70, 95, 132):
        result = rolling(amount, p["window"], statistics.fmean if n == 132 else statistics.stdev)
    elif n == 78:
        typical = apply(lambda a, b, z: (a + b + z) / 3, h, l, c)
        average = mean(typical, p["mean"])
        denom = mean(apply(lambda x, y: abs(x - y), c, average), p["deviation"])
        result = apply(lambda t, m, d: (t - m) / (0.015 * d), typical, average, denom)
    elif n in (55, 137):

        def pressure(c, o, h, l, pc, po, pl):  # noqa: E741
            c, o, h, l, pc, po, pl = rational([c, o, h, l, pc, po, pl])  # noqa: E741
            distances = [abs(h - pc), abs(l - pc), abs(h - pl)]
            a, b, d = distances
            denom = (
                d
                if distances.count(max(distances)) > 1 or d == max(distances)
                else (a + b / 2 if a == max(distances) else b + a / 2)
            )
            denom += abs(pc - po) / 4
            return 16 * (c - pc + (c - o) / 2 + pc - po) * max(a, b) / denom

        raw = apply(
            pressure, c, o, h, l, shift(c, p["lag"]), shift(o, p["lag"]), shift(l, p["lag"])
        )
        result = rolling(raw, p["window"], math.fsum) if n == 55 else raw
    elif n == 144:
        raw = apply(lambda x, pc, a: abs(x / pc - 1) / a if x < pc else 0, c, shift(c, 1), amount)
        count = rolling(apply(lambda x, pc: float(x < pc), c, shift(c, 1)), p["window"], sum)
        result = apply(lambda s, k: s / k, rolling(raw, p["window"], math.fsum), count)
    elif n in (172, 186):
        hd = apply(lambda x, prev: float(Fraction(str(x)) - Fraction(str(prev))), h, shift(h, 1))
        ld = apply(lambda x, prev: float(Fraction(str(prev)) - Fraction(str(x))), l, shift(l, 1))
        up = apply(lambda x, y: x if x > 0 and x > y else 0, hd, ld)
        down = apply(lambda x, y: y if y > 0 and y > x else 0, hd, ld)
        tr = apply(
            lambda high, low, pc: max(high - low, abs(high - pc), abs(low - pc)), h, l, shift(c, 1)
        )
        total = rolling(tr, p["direction"], math.fsum)
        plus = apply(lambda x, t: 100 * x / t, rolling(up, p["direction"], math.fsum), total)
        minus = apply(lambda x, t: 100 * x / t, rolling(down, p["direction"], math.fsum), total)
        result = mean(apply(lambda x, y: 100 * abs(x - y) / (x + y), plus, minus), p["smooth"])
        if n == 186:
            result = apply(lambda x, y: (x + y) / 2, result, shift(result, p["lag"]))
    else:
        raise AssertionError(n)
    return [
        x if i >= span - 1 and all(valid[i - span + 1 : i + 1]) else math.nan
        for i, x in enumerate(result)
    ]


def assert_values(actual, expected):
    np.testing.assert_allclose(actual, expected, rtol=2e-9, atol=2e-10, equal_nan=True)


@pytest.mark.parametrize("n", sorted(DEFAULTS))
@pytest.mark.parametrize("size", [None, 3, 7])
def test_independent_conditional_values_and_prefix(n, size):
    p = DEFAULTS[n] if size is None else custom(n, size)
    frame = data()
    factor = configure_factor(f"gtja191_{n:03d}", p)
    result = factor.compute(frame)
    assert_values(result, independent(frame, n, p))
    assert result.iloc[: warmup(n, p) - 1].isna().all()
    assert result.iloc[warmup(n, p) - 1 :].notna().any()
    for end in (1, warmup(n, p) - 1, warmup(n, p), 260):
        assert_values(factor.compute(frame.iloc[:end]), result.iloc[:end])


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_conditional_inputs_gaps_recovery(n):
    frame, p = data(180), custom(n)
    factor = configure_factor(f"gtja191_{n:03d}", p)
    for key in INPUTS[n]:
        with pytest.raises(ValueError, match="缺少"):
            factor.compute(frame.drop(columns=key))
        for bad in (np.nan, np.inf, -1.0):
            modified = frame.copy()
            modified.loc[75, key] = bad
            result = factor.compute(modified)
            assert_values(result, independent(modified, n, p))
            assert result.iloc[75 : 75 + warmup(n, p)].isna().all()
            assert_values(result.iloc[76:], factor.compute(modified.iloc[76:]))


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_conditional_constant_zero_empty_short(n):
    frame, p = data(180), custom(n)
    frame[["open", "close", "high", "low"]] = 20.0
    factor = configure_factor(f"gtja191_{n:03d}", p)
    for value in (0.0, 100.0):
        frame[["volume", "amount"]] = value
        result = factor.compute(frame)
        assert_values(result, independent(frame, n, p))
        for end in (0, 1, warmup(n, p) - 1):
            assert factor.compute(frame.iloc[:end]).isna().all()
        if n in {5, 23, 55, 78, 137, 144, 172, 186} or (n == 4 and value == 0):
            assert result.isna().all()
        else:
            assert result.iloc[-1] == (1 if n == 4 else value if n == 132 else 0)


@pytest.mark.parametrize("filename", FILES)
def test_conditional_frozen_all_rows_and_parameters(filename):
    frame = qualify_factor_fields(
        frozen(filename), frozen(filename.replace("-QFQ", "-NONE").replace("-HFQ", "-NONE"))
    )
    for n in DEFAULTS:
        for p in (DEFAULTS[n], custom(n), custom(n, 7)):
            assert_values(
                configure_factor(f"gtja191_{n:03d}", p).compute(frame), independent(frame, n, p)
            )


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_conditional_metadata_partial_parameters(n):
    cls, frame = get_factor(f"gtja191_{n:03d}"), data()
    base = describe_factor(cls)
    assert base["resolved_parameters"] == DEFAULTS[n]
    assert tuple(cls.inputs) == INPUTS[n]
    for key, default in DEFAULTS[n].items():
        p = DEFAULTS[n] | {key: default + 1}
        factor = configure_factor(cls.name, {key: default + 1})
        metadata = describe_factor(cls, {key: default + 1})
        assert metadata["warmup_bars"] == warmup(n, p)
        assert metadata["formula_sha256"] != base["formula_sha256"]
        assert_values(factor.compute(frame), independent(frame, n, p))
        for bad in (0, 601, True, "3", 2.5):
            with pytest.raises(ValueError):
                configure_factor(cls.name, {key: bad})
    assert describe_factor(cls) == base


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_conditional_pool_isolation(n):
    frames = {}
    for k in range(3):
        frame = data(100).iloc[k:].copy()
        frame.index = pd.date_range("2025-01-01", periods=100)[k:]
        frame[["open", "close", "high", "low"]] *= k + 1
        frame[["volume", "amount"]] *= k + 2
        frames[str(k)] = frame.drop(frame.index[30 + k])
    factor = configure_factor(f"gtja191_{n:03d}", custom(n))
    matrix = FactorEngine().compute_matrix(frames, factor)
    for code, frame in frames.items():
        expected = pd.Series(independent(frame, n, custom(n)), index=frame.index)
        assert_values(matrix[code], expected.reindex(matrix.index))
    pd.testing.assert_frame_equal(
        matrix,
        FactorEngine()
        .compute_matrix(dict(reversed(list(frames.items()))), factor)
        .reindex(columns=matrix.columns),
    )


def test_conditional_exact_thresholds_ties_and_zero_denominators():
    frame = pd.DataFrame({"close": [100.0, 100.0, 101.0, 109.0]})
    factor = configure_factor("gtja191_098", dict(mean=2, lag=2, trough=3, change=1))
    assert factor.compute(frame).iloc[-1] == -9
    frame.loc[3, "close"] += 1e-9
    assert factor.compute(frame).iloc[-1] == pytest.approx(-8 - 1e-9)
    # Equality remains equality at decimal prices; HD == LD contributes neither.
    frame = pd.DataFrame({"high": [20.1] * 5})
    assert configure_factor("gtja191_038", dict(mean=3, lag=1)).compute(frame).iloc[-1] == 0
    frame = pd.DataFrame(
        {
            "close": [20.0] * 5,
            "high": [20.1, 20.2, 20.3, 20.4, 20.5],
            "low": [19.9, 19.8, 19.7, 19.6, 19.5],
        }
    )
    assert configure_factor("gtja191_172", dict(direction=1, smooth=1)).compute(frame).isna().all()
    # Original previous-body term is not halved; a == b chooses third denominator.
    frame = pd.DataFrame(
        {"open": [9.0, 10.0], "close": [10.0, 11.0], "high": [11.0, 12.0], "low": [8.0, 8.0]}
    )
    assert get_factor("gtja191_137")().compute(frame).iloc[-1] == pytest.approx(16 * 2.5 * 2 / 4.25)
    frame = pd.DataFrame({"close": [10.0, 9.0, 10.0, 8.0], "amount": [0.0, 100.0, 0.0, 200.0]})
    result = configure_factor("gtja191_144", dict(window=2)).compute(frame)
    assert result.iloc[-1] == pytest.approx(0.001)
    frame.loc[3, "amount"] = 0
    assert configure_factor("gtja191_144", dict(window=2)).compute(frame).iloc[-1:].isna().all()


@pytest.mark.asyncio
async def test_gtja_amount_qualification_is_not_a_price_volume_proxy(monkeypatch):
    from easy_tdx.web.routers import research

    frame = frozen("0-000001-DAILY-QFQ.json")
    calls = []

    async def fetch(*args):
        calls.append(args)
        return frozen("0-000001-DAILY-NONE.json")

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda x: x)
    result = await research._factor_fields(
        frame, ["gtja191_132"], None, None, "SZ", "000001", "DAILY", 160, "QFQ"
    )
    assert len(calls) == 1 and calls[0][-1] == "NONE"
    assert result.attrs["factor_data_contract"]["amount_unit"] == "CNY"
    pd.testing.assert_series_equal(result.amount, frame.amount)
    broken = frame.copy()
    broken.attrs["snapshot_metadata"] = {"source": "unknown"}
    result = await research._factor_fields(
        broken, ["gtja191_132", "gtja191_014"], None, None, "SZ", "000001", "DAILY", 160, "QFQ"
    )
    with pytest.raises(ValueError, match="量额核验"):
        get_factor("gtja191_132")().compute(result)
    assert get_factor("gtja191_014")().compute(result).notna().any()


@pytest.mark.parametrize("n", sorted(DEFAULTS))
def test_conditional_cancellation_no_partial_success(monkeypatch, n):
    from easy_tdx.computation import ComputationStopped
    from easy_tdx.factor.builtin import gtja191

    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ComputationStopped("cancelled")

    monkeypatch.setattr(gtja191, "computation_checkpoint", checkpoint)
    with pytest.raises(ComputationStopped):
        configure_factor(f"gtja191_{n:03d}", custom(n)).compute(data(100))


def test_conditional_price_branches_and_stale_outlier_std():
    p = dict(mean=3, fast=1, volume_mean=3)
    factor = configure_factor("gtja191_004", p)
    for close, volume, expected in [
        ([10.0, 10.0, 13.0], [0.0, 0.0, 0.0], -1),
        ([10.0, 10.0, 7.0], [10.0, 10.0, 10.0], 1),
        ([10.0, 10.0, 10.0], [10.0, 10.0, 10.0], 1),
        ([10.0, 10.0, 10.0], [10.0, 10.0, 1.0], -1),
    ]:
        assert factor.compute(pd.DataFrame(dict(close=close, volume=volume))).iloc[-1] == expected
    for n in (70, 95):
        frame = pd.DataFrame({"amount": [1e25] + [100.0] * 15 + [101.0, 102.0, 103.0]})
        result = configure_factor(f"gtja191_{n:03d}", dict(window=3)).compute(frame)
        assert (result.iloc[3:16] == 0).all()
        assert result.iloc[-1] == pytest.approx(1)
    frame = data(80)
    frame.close = [1e25] + [100.0] * 39 + list(np.arange(100.0, 140.0))
    p = dict(std=3, smooth=3)
    assert_values(configure_factor("gtja191_023", p).compute(frame), independent(frame, 23, p))


@pytest.mark.parametrize(
    "case_id", ["300450-qfq-20261002", "600699-qfq-20260929", "601698-min30-qfq-20261002"]
)
def test_long_frozen_price_formulas_including_200_bar_warmup(case_id):
    from tests.market_matrix import entries, load_case

    entry = next(e for e in entries() if e["id"] == case_id)
    _, frame, _ = load_case(entry)
    assert len(frame) >= 250
    # These legacy long fixtures do not independently prove volume units.
    # Reuse prices only; never relabel vol or infer amount from them.
    for n in (22, 23, 38, 55, 78, 98, 137, 172, 186):
        actual = configure_factor(f"gtja191_{n:03d}", DEFAULTS[n]).compute(frame)
        assert_values(actual, independent(frame, n, DEFAULTS[n]))
        assert actual.iloc[: warmup(n, DEFAULTS[n]) - 1].isna().all()
        assert actual.iloc[250:].notna().any()
        assert_values(
            actual.iloc[:250],
            configure_factor(f"gtja191_{n:03d}", DEFAULTS[n]).compute(frame.iloc[:250]),
        )
