"""Explicit, versioned interpretations of incomplete GTJA report expressions.

No external implementation is copied. All windows are per-symbol trailing
observations; never cross-sectional row extrema. See the catalog limitations.
"""

from collections import deque
from decimal import Decimal, localcontext

import numpy as np
import pandas as pd

from easy_tdx.computation import computation_checkpoint


def _publish(value: Decimal) -> float:
    converted = float(value)
    return converted if np.isfinite(converted) and (converted != 0 or value == 0) else np.nan


def return_deviation(close: pd.Series, smooth: int, mean: int, denominator: int) -> pd.Series:
    """146: preserve current deviation multiplier; missing denominator SMA m=1."""
    out = np.full(len(close), np.nan)
    deviations: deque[Decimal] = deque(maxlen=mean)
    previous: Decimal | None = None
    state: Decimal | None = None
    scale: Decimal | None = None
    count = scale_count = 0
    with localcontext() as ctx:
        ctx.prec = 80
        for i, value in enumerate(close.to_numpy(dtype=float)):
            computation_checkpoint()
            if not np.isfinite(value) or value <= 0:
                previous = state = scale = None
                count = scale_count = 0
                deviations.clear()
                continue
            price = Decimal(str(value))
            if previous is not None:
                ret = (price - previous) / previous
                state = ret if state is None else (2 * ret + (smooth - 2) * state) / smooth
                count += 1
                if count >= smooth:
                    deviation = ret - state
                    deviations.append(deviation)
                    scale = (
                        state**2
                        if scale is None
                        else (state**2 + (denominator - 1) * scale) / denominator
                    )
                    scale_count += 1
                    if len(deviations) == mean and scale_count >= denominator and scale:
                        out[i] = _publish(sum(deviations, Decimal(0)) / mean * deviation / scale)
            previous = price
    return pd.Series(out, index=close.index)


def cumulative_extrema(close: pd.Series, window: int) -> pd.Series:
    """165/183: MAX(prefix sums) - MIN(prefix sums)/sample STD, not R/S."""
    out = np.full(len(close), np.nan)
    prices: deque[Decimal] = deque(maxlen=window)
    deviations: deque[Decimal] = deque(maxlen=window)
    with localcontext() as ctx:
        ctx.prec = 80
        for i, value in enumerate(close.to_numpy(dtype=float)):
            computation_checkpoint()
            if not np.isfinite(value) or value <= 0:
                prices.clear()
                deviations.clear()
                continue
            price = Decimal(str(value))
            prices.append(price)
            if len(prices) != window:
                continue
            mean = sum(prices, Decimal(0)) / window
            deviations.append(price - mean)
            if len(deviations) != window:
                continue
            variance = sum(((p - mean) ** 2 for p in prices), Decimal(0)) / (window - 1)
            if not variance:
                continue
            cumulative = Decimal(0)
            prefixes = []
            for deviation in deviations:
                cumulative += deviation
                prefixes.append(cumulative)
            out[i] = _publish(max(prefixes) - min(prefixes) / variance.sqrt())
    return pd.Series(out, index=close.index)


def centered_return_ratio(close: pd.Series, window: int) -> pd.Series:
    """166: reference interpretation inserts MEAN in incomplete denominator.

    Numerator stays linear, not cubed; this is not the conventional skewness.
    Decimal windows avoid overflow of squared ratios and loss of tiny returns.
    """
    out = np.full(len(close), np.nan)
    ratios: deque[Decimal] = deque(maxlen=window)
    terms: deque[tuple[Decimal, Decimal]] = deque(maxlen=window)
    previous: Decimal | None = None
    with localcontext() as ctx:
        ctx.prec = 80
        coefficient = -Decimal(window) * Decimal(window - 1).sqrt() / (window - 2)
        for i, value in enumerate(close.to_numpy(dtype=float)):
            computation_checkpoint()
            if not np.isfinite(value) or value <= 0:
                previous = None
                ratios.clear()
                terms.clear()
                continue
            price = Decimal(str(value))
            if previous is not None:
                ratio = price / previous
                ratios.append(ratio)
                if len(ratios) == window:
                    mean = sum(ratios, Decimal(0)) / window
                    terms.append((ratio - mean, mean**2))
                    if len(terms) == window:
                        numerator = sum((t[0] for t in terms), Decimal(0))
                        denominator = sum((t[1] for t in terms), Decimal(0))
                        if denominator:
                            out[i] = _publish(
                                coefficient * numerator / (denominator * denominator.sqrt())
                            )
            previous = price
    return pd.Series(out, index=close.index)
