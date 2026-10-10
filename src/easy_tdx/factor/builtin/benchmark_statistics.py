"""Bounded independent-index statistics; no fetching, filling or proxy prices."""

from collections import deque
from decimal import Decimal, localcontext
from fractions import Fraction

import numpy as np
import pandas as pd

from easy_tdx.computation import computation_checkpoint


def filtered_beta(close: pd.Series, benchmark: pd.Series, samples: int) -> pd.Series:
    """OLS with intercept on the last N selected down observations, not N bars.

    Invalid observations break the sample history. A non-down valid bar holds
    the estimate from the same last N samples, never inventing a new sample.
    Recenter each window using 80-digit returns; no absolute variance cutoff.
    """
    result = np.full(len(close), np.nan)
    history: deque[tuple[Decimal, Decimal]] = deque(maxlen=samples)
    previous: tuple[Decimal, Decimal] | None = None
    with localcontext() as ctx:
        ctx.prec = 80
        for i, (c, b) in enumerate(zip(close, benchmark)):
            if i % 16 == 0:
                computation_checkpoint()
            if not np.isfinite(c) or not np.isfinite(b) or min(c, b) <= 0:
                history.clear()
                previous = None
                continue
            current = Decimal(str(c)), Decimal(str(b))
            if previous is not None and current[1] < previous[1]:
                history.append((current[1] / previous[1] - 1, current[0] / previous[0] - 1))
            previous = current
            if len(history) != samples:
                continue
            xmean = sum((x for x, _ in history), Decimal(0)) / samples
            ymean = sum((y for _, y in history), Decimal(0)) / samples
            denominator = sum(((x - xmean) * (x - xmean) for x, _ in history), Decimal(0))
            if denominator:
                value = (
                    sum(((x - xmean) * (y - ymean) for x, y in history), Decimal(0)) / denominator
                )
                result[i] = float(value)
    return pd.Series(result, index=close.index)


def price_moment_ratio(close: pd.Series, benchmark: pd.Series, window: int) -> pd.Series:
    """Literal 181: excess return MINUS index-price deviation squared.

    Exact rational sums preserve a mathematically zero signed-cubic denominator
    and do not leave a large-outlier residue in subsequent rolling windows.
    """
    result = np.full(len(close), np.nan)
    prices: deque[tuple[Fraction, Fraction]] = deque(maxlen=window + 1)
    terms: deque[tuple[Fraction, Fraction]] = deque(maxlen=window)
    for i, (c, b) in enumerate(zip(close, benchmark)):
        if i % 16 == 0:
            computation_checkpoint()
        if not np.isfinite(c) or not np.isfinite(b) or min(c, b) <= 0:
            prices.clear()
            terms.clear()
            continue
        prices.append((Fraction(str(c)), Fraction(str(b))))
        if len(prices) < window + 1:
            continue
        observations = list(prices)
        returns = [
            observations[j][0] / observations[j - 1][0] - 1 for j in range(1, len(observations))
        ]
        excess = returns[-1] - sum(returns, Fraction(0)) / window
        deviation = (
            observations[-1][1] - sum((x[1] for x in observations[1:]), Fraction(0)) / window
        )
        terms.append((excess - deviation * deviation, deviation * deviation * deviation))
        if len(terms) < window:
            continue
        denominator = sum(d for _, d in terms)
        if denominator:
            try:
                result[i] = float(sum(n for n, _ in terms) / denominator)
            except OverflowError:
                pass  # Unrepresentable output remains missing, not clipped.
    return pd.Series(result, index=close.index)
