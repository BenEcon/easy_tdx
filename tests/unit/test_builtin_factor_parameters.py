"""Independent scalar/NumPy checks of every parameterized legacy kernel."""

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import get_factor
from easy_tdx.factor.builtin_parameters import TEMPLATES
from easy_tdx.factor.catalog import builtin_defaults, describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from tests.unit.test_factor_data import ROOT, frozen


def sample(n=150):
    x = np.arange(n, dtype=float)
    close = 20 + x / 20 + np.sin(x * 0.7)
    return pd.DataFrame(
        {
            "close": close,
            "high": close + 0.7,
            "low": close - 0.4,
            "vol": 100 + x * 3 + np.cos(x),
            "amount": (100 + x * 3 + np.cos(x)) * close,
        },
        index=pd.date_range("2025-01-01", periods=n),
    )


def smoothing(values, alpha):
    # Independent recurrence, only finite sample input in the numerical oracle.
    out = np.empty(len(values))
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def oracle(frame, name, p):
    c, h, lo, v, a = (frame[k].to_numpy() for k in ["close", "high", "low", "vol", "amount"])
    result = np.full(len(c), np.nan)
    w = p.get("window", p.get("long", 0))
    ret = np.r_[np.nan, c[1:] / c[:-1] - 1]
    if name in {"momentum_20d", "momentum_60d", "reversal_5d"}:
        result[w:] = (c[w:] / c[:-w] - 1) * (-1 if name == "reversal_5d" else 1)
        return result
    if name == "rsi_14":
        delta = np.diff(c)
        up = smoothing(np.maximum(delta, 0), 1 / w)
        total = smoothing(np.abs(delta), 1 / w)
        result[1:] = (np.round(up / total * 100, 3) - 50) / 50
        return result
    if name == "macd_hist_signal":
        dif = smoothing(c, 2 / (p["short"] + 1)) - smoothing(c, 2 / (p["long"] + 1))
        hist = np.round(2 * (dif - smoothing(dif, 2 / (p["signal"] + 1))), 3)
        for i in range(p["scale_window"] - 1, len(c)):
            denom = np.mean(np.abs(hist[i - p["scale_window"] + 1 : i + 1]))
            result[i] = hist[i] / denom if denom else np.nan
        return result
    tr = np.r_[
        np.nan, np.maximum.reduce([h[1:] - lo[1:], abs(h[1:] - c[:-1]), abs(lo[1:] - c[:-1])])
    ]
    obv = np.cumsum(np.r_[0, np.sign(np.diff(c))] * v)
    for i in range(w - 1, len(c)):
        sl = slice(i - w + 1, i + 1)
        prices, returns = c[sl], ret[sl]
        if name == "volatility_20d":
            result[i] = np.std(returns, ddof=1)
        elif name == "sharpe_20d":
            result[i] = np.mean(returns) / np.std(returns, ddof=1)
        elif name == "win_rate_20d":
            result[i] = np.mean(returns > 0) if np.isfinite(returns).all() else np.nan
        elif name == "atr_14d":
            result[i] = np.mean(tr[sl])
        elif name == "max_drawdown_20d":
            result[i] = min(prices / np.maximum.accumulate(prices) - 1)
        elif name == "amount_relative_20":
            result[i] = a[i] / np.mean(a[sl])
        elif name == "vol_surge":
            result[i] = v[i] / np.mean(v[sl])
        elif name == "amount_ma_ratio":
            result[i] = np.mean(a[i - p["short"] + 1 : i + 1]) / np.mean(a[sl])
        elif name == "obv_trend":
            result[i] = np.linalg.lstsq(np.c_[np.arange(w), np.ones(w)], obv[sl], rcond=None)[0][0]
        elif name == "boll_position":
            mid, std = np.mean(prices), np.std(prices)
            upper, lower = np.round(
                [mid + p["std_multiplier"] * std, mid - p["std_multiplier"] * std], 3
            )
            result[i] = (
                np.clip((c[i] - lower) / (upper - lower), 0, 1) if upper != lower else np.nan
            )
        else:
            raise AssertionError(name)
    return result


def custom(name):
    defaults = builtin_defaults(name)
    if name == "macd_hist_signal":
        return {"short": 3, "long": 11, "signal": 4, "scale_window": 13}
    if name == "amount_ma_ratio":
        return {"short": 3, "long": 13}
    return {
        **defaults,
        "window": 13,
        **({"std_multiplier": 1.7} if name == "boll_position" else {}),
    }


@pytest.mark.parametrize("name", list(TEMPLATES))
@pytest.mark.parametrize("use_custom", [False, True])
def test_every_builtin_actual_kernel_matches_independent_oracle_and_is_causal(name, use_custom):
    p = custom(name) if use_custom else builtin_defaults(name)
    frame = sample()
    factor = configure_factor(name, p)
    result = factor.compute(frame)
    np.testing.assert_allclose(result, oracle(frame, name, p), atol=2e-9, rtol=2e-9, equal_nan=True)
    pd.testing.assert_series_equal(result.iloc[:80], factor.compute(frame.iloc[:80]))
    assert result.index.equals(frame.index)
    meta = describe_factor(get_factor(name), p)
    assert meta["resolved_parameters"] == p
    assert result.first_valid_index() == frame.index[meta["warmup_bars"] - 1]
    assert all(getattr(get_factor(name), k) == v for k, v in builtin_defaults(name).items())
    if not use_custom:
        pd.testing.assert_series_equal(result, configure_factor(name).compute(frame))
        assert meta == describe_factor(get_factor(name))


@pytest.mark.parametrize(
    "value", [None, True, "13", 13.0, 0, 1, 601, 10**400, float("nan"), float("inf"), {}, []]
)
def test_invalid_builtin_window_has_controlled_error(value):
    with pytest.raises(ValueError):
        configure_factor("momentum_20d", {"window": value})


@pytest.mark.parametrize("value", [None, True, "2", 0, 11, 10**400, float("nan"), float("inf")])
def test_invalid_multiplier_has_controlled_error(value):
    with pytest.raises(ValueError):
        configure_factor("boll_position", {"std_multiplier": value})


def test_partial_parameters_validation_aliases_and_equivalent_momentum():
    factor = configure_factor("macd_hist_signal", {"signal": 3})
    assert (factor.short, factor.long, factor.signal, factor.scale_window) == (12, 26, 3, 20)
    for name, p in [
        ("momentum_20d", {"short": 3}),
        ("macd_hist_signal", {"short": 26}),
        ("amount_ma_ratio", {"long": 5}),
    ]:
        with pytest.raises(ValueError):
            configure_factor(name, p)
    with pytest.raises(ValueError, match="重复"):
        configured_selection(["momentum_20d", "momentum_60d"], {"momentum_20d": {"window": 60}})
    old = describe_factor(get_factor("turnover_rate"), {"window": 13})
    new = describe_factor(get_factor("amount_relative_20"), {"window": 13})
    assert old["formula_sha256"] == new["formula_sha256"]
    assert (
        new["formula_sha256"] != describe_factor(get_factor("amount_relative_20"))["formula_sha256"]
    )
    pd.testing.assert_series_equal(
        configure_factor("turnover_rate", {"window": 13}).compute(sample()),
        configure_factor("amount_relative_20", {"window": 13}).compute(sample()),
    )


def test_concurrent_instances_do_not_change_registered_class():
    with ThreadPoolExecutor(2) as executor:
        results = list(
            executor.map(
                lambda w: configure_factor("momentum_20d", {"window": w}).compute(sample()), [5, 13]
            )
        )
    assert results[0].first_valid_index() == sample().index[5]
    assert results[1].first_valid_index() == sample().index[13]
    assert get_factor("momentum_20d").window == 20


def test_missing_prices_are_not_forward_filled_or_partial_drawdown():
    frame = sample()
    frame.loc[frame.index[20], "close"] = np.nan
    for name in ["momentum_20d", "reversal_5d"]:
        result = configure_factor(name, {"window": 5}).compute(frame)
        assert np.isnan(result.iloc[20]) and np.isnan(result.iloc[25])
    for name in ["volatility_20d", "sharpe_20d", "win_rate_20d"]:
        result = configure_factor(name, {"window": 5}).compute(frame)
        assert result.iloc[20:26].isna().all()
        assert np.isfinite(result.iloc[26])
    result = configure_factor("max_drawdown_20d", {"window": 5}).compute(frame)
    assert result.iloc[20:25].isna().all() and np.isfinite(result.iloc[25])
    assert configure_factor("atr_14d").compute(frame.iloc[:0]).empty


@pytest.mark.parametrize("path", sorted(ROOT.glob("*.json")), ids=lambda p: p.stem)
@pytest.mark.parametrize("name", list(TEMPLATES))
def test_custom_parameters_on_real_frozen_stocks_periods_and_adjustments(path, name):
    frame = frozen(path.name)
    factor = configure_factor(name, custom(name))
    actual = factor.compute(frame)
    np.testing.assert_allclose(
        actual, oracle(frame, name, custom(name)), atol=2e-7, rtol=2e-8, equal_nan=True
    )
    pd.testing.assert_series_equal(actual.iloc[:100], factor.compute(frame.iloc[:100]))
