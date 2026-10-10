"""Local Alpha101 compound kernels; see Alpha101-reference-notice.md.

Exact decimal-input rationals are retained until cross-sectional ranking.
No future fill, no epsilon denominator, no invented single-security ranks.
"""

from __future__ import annotations

from collections import deque
from fractions import Fraction
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from easy_tdx.computation import computation_checkpoint
from easy_tdx.factor.panel import FactorPanel

if TYPE_CHECKING:
    from easy_tdx.factor.builtin.alpha101 import Spec

Value = Fraction | None


def compute_conditional_trough(frame: pd.DataFrame, spec: Spec) -> pd.Series:
    from easy_tdx.factor.builtin.alpha101 import clean

    data = clean(frame, spec)
    p = spec.resolved_parameters
    values: list[Value] = [Fraction(str(v)) if pd.notna(v) else None for v in data.close]
    totals = rolling_sum(values, p["mean"])
    complete = data.close.notna().astype(int).rolling(spec.warmup).sum().eq(spec.warmup)
    lows = data.close.rolling(p["trough"]).min()
    threshold = Fraction(str(spec.threshold))
    out = np.full(len(data), np.nan)
    for i in range(spec.warmup - 1, len(data)):
        computation_checkpoint()
        if not complete.iloc[i]:
            continue
        current, previous = totals[i], totals[i - p["lag"]]
        close, delayed, short = values[i], values[i - p["lag"]], values[i - p["price_lag"]]
        assert current is not None and previous is not None
        assert close is not None and delayed is not None and short is not None
        change = (current - previous) / (p["mean"] * delayed)
        value = Fraction(str(lows.iloc[i])) - close if change <= threshold else short - close
        try:
            out[i] = float(value)
        except OverflowError:
            pass
    return pd.Series(out, index=data.index).where(np.isfinite(out))


def rolling_sum(values: list[Value], window: int) -> list[Value]:
    total = Fraction(0)
    missing = 0
    history: deque[Value] = deque()
    out: list[Value] = []
    for value in values:
        computation_checkpoint()
        history.append(value)
        if value is None:
            missing += 1
        else:
            total += value
        if len(history) > window:
            old = history.popleft()
            if old is None:
                missing -= 1
            else:
                total -= old
        out.append(total if len(history) == window and missing == 0 else None)
    return out


def sample_variance(values: list[Value], window: int) -> list[Value]:
    totals = rolling_sum(values, window)
    squares = rolling_sum([v * v if v is not None else None for v in values], window)
    return [
        (s - t * t / window) / (window - 1) if s is not None and t is not None else None
        for s, t in zip(squares, totals)
    ]


def exact_rank(values: NDArray[np.object_]) -> NDArray[np.object_]:
    out = np.full(values.shape, None, dtype=object)
    for i, row in enumerate(values):
        computation_checkpoint()
        ordered = sorted(v for v in row if v is not None)
        count = len(ordered)
        if count < 2:
            continue
        ranks = {}
        start = 0
        while start < count:
            end = start + 1
            while end < count and ordered[end] == ordered[start]:
                end += 1
            ranks[ordered[start]] = Fraction(start + 1 + end, 2 * count)
            start = end
        for j, value in enumerate(row):
            if value is not None:
                out[i, j] = ranks[value]
    return out


def exact_scale(values: NDArray[np.object_]) -> NDArray[np.object_]:
    """L1 normalization per component, never silently refill missing members."""
    out = np.full(values.shape, None, dtype=object)
    for i, row in enumerate(values):
        computation_checkpoint()
        present = [v for v in row if v is not None]
        total = sum((abs(v) for v in present), Fraction(0))
        if len(present) < 2 or not total:
            continue
        for j, value in enumerate(row):
            if value is not None:
                out[i, j] = value / total
    return out


def compute_scaled_panel(panel: FactorPanel, spec: Spec) -> pd.DataFrame:
    from easy_tdx.factor.builtin.alpha101 import clean, correlation

    p, n = spec.resolved_parameters, spec.number
    shape = panel.observed.shape
    first, second, extra = (np.full(shape, None, dtype=object) for _ in range(3))
    complete = np.zeros(shape, dtype=bool)
    for j, symbol in enumerate(panel.observed.columns):
        computation_checkpoint()
        f = clean(pd.DataFrame({key: panel.fields[key][symbol] for key in spec.inputs}), spec)
        valid = f.notna().all(axis=1)
        complete[:, j] = valid.astype(int).rolling(spec.warmup).sum().eq(spec.warmup)
        c = f.close.where(valid)
        if n == 32:
            corr = correlation(f.vwap.where(valid), c.shift(p["lag"]), p["corr"])
            sums = rolling_sum([Fraction(str(v)) if pd.notna(v) else None for v in c], p["mean"])
            for i in range(spec.warmup - 1, len(c)):
                computation_checkpoint()
                if not complete[i, j]:
                    continue
                summed = sums[i]
                assert summed is not None
                first[i, j] = summed / p["mean"] - Fraction(str(c.iloc[i]))
                if pd.notna(corr.iloc[i]):
                    second[i, j] = Fraction(str(corr.iloc[i]))
            continue
        positions = c.rolling(p["peak"]).apply(np.argmax, raw=True)
        for i in range(p["peak"] - 1, len(c)):
            computation_checkpoint()
            if pd.notna(positions.iloc[i]):
                second[i, j] = Fraction(int(positions.iloc[i]))
            if not complete[i, j]:
                continue
            close = Fraction(str(c.iloc[i]))
            if n == 57:
                extra[i, j] = Fraction(str(f.vwap.iloc[i])) - close
            else:
                high, low, volume = (
                    Fraction(str(f[key].iloc[i])) for key in ("high", "low", "volume")
                )
                if high != low:
                    first[i, j] = (2 * close - low - high) * volume / (high - low)
    if n == 32:
        a, b = exact_scale(first), exact_scale(second)
    elif n == 60:
        a, b = exact_scale(exact_rank(first)), exact_scale(exact_rank(second))
    else:
        a, b = extra, exact_rank(second)
    result = np.full(shape, np.nan)
    for i, j in np.ndindex(shape):
        computation_checkpoint()
        if not complete[i, j] or a[i, j] is None:
            continue
        if n == 57:
            if i + 1 < p["decay"]:
                continue
            history = b[i + 1 - p["decay"] : i + 1, j]
            if any(v is None for v in history):
                continue
            weighted = sum((k * v for k, v in enumerate(history, 1)), Fraction(0))
            value = a[i, j] * (p["decay"] * (p["decay"] + 1) // 2) / weighted
        elif b[i, j] is None:
            continue
        else:
            value = a[i, j] + 20 * b[i, j] if n == 32 else b[i, j] - 2 * a[i, j]
        try:
            result[i, j] = float(value)
        except OverflowError:
            pass
    return pd.DataFrame(result, index=panel.observed.index, columns=panel.observed.columns).where(
        np.isfinite(result)
    )


def compute_compound_panel(panel: FactorPanel, spec: Spec) -> pd.DataFrame:
    from easy_tdx.factor.builtin.alpha101 import clean

    if spec.number in {32, 57, 60}:
        return compute_scaled_panel(panel, spec)
    p = spec.resolved_parameters
    n = spec.number
    shape = panel.observed.shape
    first, second, extra = (np.full(shape, None, dtype=object) for _ in range(3))
    for j, symbol in enumerate(panel.observed.columns):
        computation_checkpoint()
        frame = clean(pd.DataFrame({key: panel.fields[key][symbol] for key in spec.inputs}), spec)
        valid = frame.notna().all(axis=1)
        complete = valid.astype(int).rolling(spec.warmup).sum().eq(spec.warmup).to_numpy()
        values: dict[str, list[Value]] = {
            key: [Fraction(str(v)) if ok else None for v, ok in zip(frame[key], valid)]
            for key in spec.inputs
        }
        c = values["close"]
        returns: list[Value] = [None]
        returns.extend(
            [b / a - 1 if a is not None and b is not None else None for a, b in zip(c, c[1:])]
        )
        if n == 5:
            total = rolling_sum(values["vwap"], p["mean"])
            for i in range(spec.warmup - 1, len(c)):
                o, vwap, close, vwap_sum = values["open"][i], values["vwap"][i], c[i], total[i]
                if (
                    complete[i]
                    and o is not None
                    and vwap is not None
                    and close is not None
                    and vwap_sum is not None
                ):
                    first[i, j] = o - vwap_sum / p["mean"]
                    second[i, j] = close - vwap
        elif n == 52:
            short_sum = rolling_sum(returns, p["short"])
            long_sum = rolling_sum(returns, p["long"])
            lows = frame.low.rolling(p["trough"]).min()
            positions = frame.volume.rolling(p["volume_rank"]).rank(method="average", pct=True)
            for i in range(spec.warmup - 1, len(c)):
                short_value, long_value = short_sum[i], long_sum[i]
                if complete[i] and short_value is not None and long_value is not None:
                    first[i, j] = (long_value - short_value) / (p["long"] - p["short"])
                    delta = Fraction(str(lows.iloc[i - p["lag"]])) - Fraction(str(lows.iloc[i]))
                    position = Fraction(float(positions.iloc[i])).limit_denominator(
                        2 * p["volume_rank"]
                    )
                    extra[i, j] = delta * position
        elif n == 8:
            open_sum = rolling_sum(values["open"], p["sum"])
            return_sum = rolling_sum(returns, p["sum"])
            product = [
                a * b if a is not None and b is not None else None
                for a, b in zip(open_sum, return_sum)
            ]
            for i in range(spec.warmup - 1, len(c)):
                a, b = product[i], product[i - p["lag"]]
                if complete[i] and a is not None and b is not None:
                    first[i, j] = a - b
        elif n == 19:
            return_sum = rolling_sum(returns, p["returns"])
            for i in range(spec.warmup - 1, len(c)):
                a, b = c[i], c[i - p["lag"]]
                if complete[i] and a is not None and b is not None:
                    first[i, j] = return_sum[i]  # Adding 1 preserves ordering.
                    extra[i, j] = Fraction((a < b) - (a > b))
        elif n == 30:
            directions: list[Value] = [None]
            directions.extend(
                [
                    Fraction((b > a) - (b < a)) if a is not None and b is not None else None
                    for a, b in zip(c, c[1:])
                ]
            )
            summed = rolling_sum(directions, p["direction"])
            short = rolling_sum(values["volume"], p["short"])
            long = rolling_sum(values["volume"], p["long"])
            for i in range(spec.warmup - 1, len(c)):
                a, b = short[i], long[i]
                if complete[i]:
                    first[i, j] = summed[i]
                    if a is not None and b is not None and b > 0:
                        extra[i, j] = a / b
        elif n == 34:
            short_var = sample_variance(returns, p["short"])
            long_var = sample_variance(returns, p["long"])
            for i in range(spec.warmup - 1, len(c)):
                a, b, c1, c2 = short_var[i], long_var[i], c[i], c[i - p["lag"]]
                if complete[i]:
                    if a is not None and b is not None and b > 0:
                        first[i, j] = a / b  # sqrt is monotone on nonnegative values.
                    if c1 is not None and c2 is not None:
                        second[i, j] = c1 - c2
        else:
            raise ValueError("未实现的复合 Alpha101 编号")

    ranked = exact_rank(first)
    if n == 5:
        other = exact_rank(second)
        for i, j in np.ndindex(shape):
            if j == 0:
                computation_checkpoint()
            a, b = ranked[i, j], other[i, j]
            ranked[i, j] = -a * abs(b) if a is not None and b is not None else None
    elif n == 34:
        other = exact_rank(second)
        combined = np.full(shape, None, dtype=object)
        for i, j in np.ndindex(shape):
            if ranked[i, j] is not None and other[i, j] is not None:
                combined[i, j] = 2 - ranked[i, j] - other[i, j]
        ranked = exact_rank(combined)
    result = np.full(shape, np.nan)
    for i, j in np.ndindex(shape):
        if j == 0:
            computation_checkpoint()
        value = ranked[i, j]
        if value is None:
            continue
        if n == 8:
            value = -value
        elif n in {19, 30}:
            if extra[i, j] is None:
                continue
            value = extra[i, j] * (1 + value if n == 19 else 1 - value)
        elif n == 52:
            if extra[i, j] is None:
                continue
            value *= extra[i, j]
        try:
            result[i, j] = float(value)
        except OverflowError:
            pass
    return pd.DataFrame(result, index=panel.observed.index, columns=panel.observed.columns)


def compute_rank_correlation(frame: pd.DataFrame, spec: Spec) -> pd.Series:
    from easy_tdx.factor.builtin.alpha101 import clean, correlation

    data = clean(frame, spec)
    p = spec.resolved_parameters
    valid = data.notna().all(axis=1)
    data = data.where(valid, np.nan)
    ranks = data.rolling(p["rank"]).rank(method="average", pct=True)
    corr = correlation(ranks.volume, ranks.high, p["corr"])
    result = -corr.rolling(p["max"]).max()
    return result.where(valid.astype(int).rolling(spec.warmup).sum().eq(spec.warmup))
