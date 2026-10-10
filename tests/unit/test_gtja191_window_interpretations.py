"""Independent re-windowed rational oracles for explicitly disclosed conventions."""

import math
from decimal import Decimal, localcontext
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from tests.unit.test_factor_data import frozen
from tests.unit.test_gtja191_vwap import sample

DEFAULTS = {
    146: dict(smooth=61, mean=20, denominator=60),
    165: dict(window=48),
    166: dict(window=20),
    183: dict(window=24),
}


def independent(frame, number, p):
    prices = [Fraction(str(v)) if math.isfinite(v) and v > 0 else None for v in frame.close]
    result = np.full(len(prices), np.nan)

    def decimal(v):
        return Decimal(v.numerator) / Decimal(v.denominator)

    def smooth(values, w, m):
        # Closed geometric weights, not the production running state.
        if len(values) < w:
            return None
        q = Fraction(w - m, w)
        return values[0] * q ** (len(values) - 1) + sum(
            Fraction(m, w) * value * q ** (len(values) - 1 - j)
            for j, value in enumerate(values[1:], 1)
        )

    with localcontext() as ctx:
        ctx.prec = 90
        if number == 146:
            # Compute each geometric-weight oracle once, with an independent
            # full history per stage, rather than repeatedly rebuilding prefixes.
            r, b, d = [], [], []
            previous = None
            for end, price in enumerate(prices):
                if price is None:
                    r, b, d, previous = [], [], [], None
                    continue
                if previous is not None:
                    r.append(price / previous - 1)
                    current = smooth(r, p["smooth"], 2)
                    if current is not None:
                        b.append(current)
                        d.append(r[-1] - current)
                        den = smooth([v * v for v in b], p["denominator"], 1)
                        if len(d) >= p["mean"] and den:
                            value = sum(d[-p["mean"] :]) / p["mean"] * d[-1] / den
                            f = float(value)
                            if math.isfinite(f) and (f != 0 or value == 0):
                                result[end] = f
                previous = price
            return result
        for end in range(len(prices)):
            if prices[end] is None:
                continue
            start = next((j + 1 for j in range(end - 1, -1, -1) if prices[j] is None), 0)
            c = prices[start : end + 1]
            if number in (165, 183):
                w = p["window"]
                if len(c) < 2 * w - 1:
                    continue
                deviations = [
                    c[j] - sum(c[j - w + 1 : j + 1]) / w for j in range(len(c) - w, len(c))
                ]
                prefixes = [sum(deviations[: j + 1]) for j in range(w)]
                mean = sum(c[-w:]) / w
                variance = sum((x - mean) ** 2 for x in c[-w:]) / (w - 1)
                if not variance:
                    continue
                value = decimal(max(prefixes)) - decimal(min(prefixes)) / decimal(variance).sqrt()
            else:
                w = p["window"]
                if len(c) < 2 * w:
                    continue
                ratios = [b / a for a, b in zip(c, c[1:])]
                means = [
                    sum(ratios[j - w + 1 : j + 1]) / w for j in range(len(ratios) - w, len(ratios))
                ]
                numerator = sum(x - y for x, y in zip(ratios[-w:], means))
                denominator = decimal(sum(x * x for x in means))
                value = (
                    -Decimal(w)
                    * Decimal(w - 1).sqrt()
                    * decimal(numerator)
                    / ((w - 2) * denominator * denominator.sqrt())
                )
            f = float(value)
            if math.isfinite(f) and (f != 0 or value == 0):
                result[end] = f
    return result


@pytest.mark.parametrize("number", DEFAULTS)
@pytest.mark.parametrize("size", [None, 3, 7])
def test_interpreted_default_custom_oracle_prefix(number, size):
    p = DEFAULTS[number] if size is None else {k: size for k in DEFAULTS[number]}
    frame = next(iter(sample(145).values()))
    factor = configure_factor(f"gtja191_{number:03}", p)
    actual = factor.compute(frame)
    np.testing.assert_allclose(
        actual, independent(frame, number, p), rtol=1e-10, atol=1e-12, equal_nan=True
    )
    assert actual.notna().any()
    assert actual.iloc[: factor.spec.warmup - 1].isna().all()
    assert pd.notna(actual.iloc[factor.spec.warmup - 1])
    pd.testing.assert_series_equal(actual.iloc[:130], factor.compute(frame.iloc[:130]))


@pytest.mark.parametrize("number", DEFAULTS)
def test_interpreted_missing_constant_extreme_and_cancel(number, monkeypatch):
    p = {k: 3 for k in DEFAULTS[number]}
    factor = configure_factor(f"gtja191_{number:03}", p)
    for values in (
        [8.0] * 30,
        [2.0, 3.0, 4.0, 0.0, 5.0, 6.0, 7.0, np.nan, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0],
        [1e200 * (1 + i % 7 * 0.1) for i in range(30)],
        [1e-200 * (1 + i % 7 * 0.1) for i in range(30)],
    ):
        frame = pd.DataFrame({"close": values})
        np.testing.assert_allclose(
            factor.compute(frame), independent(frame, number, p), rtol=1e-10, atol=0, equal_nan=True
        )
    frame = pd.DataFrame({"close": [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]})
    assert factor.compute(frame.iloc[:0]).empty
    assert factor.compute(frame.iloc[:2]).isna().all()

    class Cancelled(BaseException):
        pass

    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise Cancelled()

    monkeypatch.setattr(
        "easy_tdx.factor.builtin.window_interpretations.computation_checkpoint", cancel
    )
    with pytest.raises(Cancelled):
        factor.compute(frame)
    assert calls == 3


@pytest.mark.parametrize("number", DEFAULTS)
@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_interpreted_real_periods_adjustments(number, adjust):
    for name in [
        f"0-000001-DAILY-{adjust}.json",
        f"0-300750-DAILY-{adjust}.json",
        f"1-600036-DAILY-{adjust}.json",
        f"0-300750-MIN_30-{adjust}.json",
    ]:
        frame = frozen(name)
        p = DEFAULTS[number]
        actual = configure_factor(f"gtja191_{number:03}", p).compute(frame)
        np.testing.assert_allclose(
            actual, independent(frame, number, p), rtol=1e-9, atol=1e-12, equal_nan=True
        )
        assert actual.notna().any()


@pytest.mark.parametrize("number", DEFAULTS)
def test_interpreted_pool_identity_and_metadata(number):
    data = sample(40)
    symbols = list(data)
    data[symbols[1]] = data[symbols[1]].iloc[::2].copy()
    p = {k: 3 for k in DEFAULTS[number]}
    factor = configure_factor(f"gtja191_{number:03}", p)
    output = FactorEngine().compute_matrix(data, factor)
    for symbol, frame in data.items():
        oracle = pd.Series(independent(frame, number, p), index=frame.datetime).reindex(
            output.index
        )
        np.testing.assert_allclose(output[symbol], oracle, rtol=1e-10, atol=1e-12, equal_nan=True)
    meta = describe_factor(get_factor(f"gtja191_{number:03}"), p)
    assert "解释" in "".join(meta["limitations"]) or "省略" in "".join(meta["limitations"])
    assert meta["resolved_parameters"] == p
    assert meta["source_commit"] == "43ace2cc4b81d048864ec2e40c25728d5d464e05"


def test_interpreted_hand_examples_and_invalid_windows():
    # 165 w=2: deviations [1,2], prefixes [1,3], STD([3,7])=sqrt(8).
    actual = configure_factor("gtja191_165", {"window": 2}).compute(
        pd.DataFrame({"close": [1.0, 3.0, 7.0]})
    )
    assert actual.iloc[-1] == pytest.approx(3 - 1 / math.sqrt(8))
    # 166 w=3: Q=[2,2,2,2,3], last means=[2,2,7/3], numerator=2/3.
    actual = configure_factor("gtja191_166", {"window": 3}).compute(
        pd.DataFrame({"close": [1.0, 2.0, 4.0, 8.0, 16.0, 48.0]})
    )
    assert actual.iloc[-1] == pytest.approx(-3 * math.sqrt(2) * (2 / 3) / (121 / 9) ** 1.5)
    # 146 smooth=2 => B=R, hence numerator exactly 0 when denominator nonzero.
    actual = configure_factor("gtja191_146", dict(smooth=2, mean=1, denominator=1)).compute(
        pd.DataFrame({"close": [1.0, 2.0, 4.0]})
    )
    assert actual.iloc[-1] == 0
    for n, p in [
        (146, {"smooth": 1}),
        (166, {"window": 2}),
        (165, {"window": 1}),
        (183, {"window": 301}),
    ]:
        with pytest.raises(ValueError):
            configure_factor(f"gtja191_{n:03}", p)


@pytest.mark.parametrize("number", DEFAULTS)
def test_interpreted_declared_input_and_parameter_contract(number):
    factor = configure_factor(f"gtja191_{number:03}", {})
    frame = pd.DataFrame({"close": [10.0] * 10})
    with pytest.raises(ValueError, match="缺少"):
        factor.compute(frame.drop(columns="close"))
    for key in DEFAULTS[number]:
        for invalid in (True, 1.5, "3", None, 0, 601):
            with pytest.raises(ValueError):
                configure_factor(f"gtja191_{number:03}", {key: invalid})
    assert (
        describe_factor(get_factor(f"gtja191_{number:03}"))["resolved_parameters"]
        == DEFAULTS[number]
    )


def test_interpreted_equivalent_windows_are_not_duplicate_factors():
    with pytest.raises(ValueError, match="重复"):
        configured_selection(["gtja191_165", "gtja191_183"], {"gtja191_183": {"window": 48}})
    with pytest.raises(ValueError, match="600"):
        configure_factor("gtja191_146", {"smooth": 400, "denominator": 300})
