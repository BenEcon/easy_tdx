"""Scale-aware float64 cross-sectional diagnostics, not economic materiality tests.

Ranks use bounded-diameter groups (not transitive isclose chaining). A factor has
no fixed absolute floor, so a genuinely dispersed 1e-100 factor stays usable.
Price-ratio returns have a unit arithmetic scale from ``future / current - 1``.
These engineering tolerances are disclosed, not a proof of propagated error.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from numpy.typing import NDArray

STATISTICS_VERSION = "factor-cross-section-numerics-v2"
RELATIVE_TOLERANCE = float(32 * np.finfo(np.float64).eps)
NUMERIC_POLICY = {
    "version": STATISTICS_VERSION,
    "relative_tolerance": float(RELATIVE_TOLERANCE),
    "factor_absolute_scale": 0.0,
    "return_absolute_scale": 1.0,
    "tie_method": "sorted_anchor_bounded_diameter_average_rank",
    "pearson": "scaled_centered_unit_vectors",
    "preprocess": "coalesced_scaled_mad_sample_zscore",
    "spread": "below_return_arithmetic_resolution_is_zero_not_missing",
}


def indistinguishable(left: float, right: float, *, floor: float = 0.0) -> bool:
    # Compare scaled differences without overflow at opposite large values.
    scale = max(abs(left), abs(right), floor)
    return scale == 0 or abs(left / scale - right / scale) <= RELATIVE_TOLERANCE


def mean(values: NDArray[np.float64]) -> float:
    scale = float(np.max(np.abs(values)))
    return 0.0 if scale == 0 else math.fsum(float(v / scale) for v in values) / len(values) * scale


def coalesced(values: pd.Series, *, floor: float = 0.0) -> pd.Series:
    """Temporary rank/standardization values only. Never mutate saved raw inputs."""
    out = values.to_numpy(dtype=float, copy=True)
    out[~np.isfinite(out)] = np.nan
    positions = np.flatnonzero(np.isfinite(out))
    positions = positions[np.argsort(out[positions], kind="stable")]
    start = 0
    while start < len(positions):
        end = start + 1
        anchor = float(out[positions[start]])
        while end < len(positions) and indistinguishable(
            anchor, float(out[positions[end]]), floor=floor
        ):
            end += 1
        group = positions[start:end]
        out[group] = mean(out[group])
        start = end
    return pd.Series(out, index=values.index, name=values.name)


def distinct_count(values: pd.Series, *, floor: float = 0.0) -> int:
    return int(coalesced(values, floor=floor).nunique())


def _centered(values: NDArray[np.float64]) -> NDArray[np.float64]:
    # Subtract an observed pivot before scaling. Dividing a large common offset
    # first loses the low bits of genuinely resolvable differences (Sterbenz).
    pivot = np.sort(values)[len(values) // 2]
    with np.errstate(over="ignore"):
        shifted = values - pivot
    if not np.isfinite(shifted).all():
        shifted = values / float(np.max(np.abs(values)))
    scale = float(np.max(np.abs(shifted)))
    normalized = shifted / scale if scale else shifted
    return np.asarray(normalized - math.fsum(normalized) / len(normalized), dtype=np.float64)


def _unit_centered(values: NDArray[np.float64]) -> NDArray[np.float64] | None:
    centered = _centered(values)
    # Scaling twice avoids underflow for small but resolvable centered values.
    width = float(np.max(np.abs(centered)))
    if width == 0:
        return None
    centered /= width
    return centered / math.sqrt(math.fsum(float(v * v) for v in centered))


def stable_correlation(
    x: pd.Series,
    y: pd.Series,
    *,
    rank: bool = False,
    x_floor: float = 0.0,
    y_floor: float = 0.0,
) -> float | None:
    pair = pd.concat([x, y], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pair) < 5:
        return None
    left = coalesced(pair.iloc[:, 0], floor=x_floor)
    right = coalesced(pair.iloc[:, 1], floor=y_floor)
    if left.nunique() < 2 or right.nunique() < 2:
        return None
    # Average ranks for ties. Pearson retains the original numerical observations.
    a = left.rank(method="average") if rank else pair.iloc[:, 0]
    b = right.rank(method="average") if rank else pair.iloc[:, 1]
    av, bv = _unit_centered(a.to_numpy(dtype=float)), _unit_centered(b.to_numpy(dtype=float))
    if av is None or bv is None:
        return None
    return float(np.clip(math.fsum(float(v) for v in av * bv), -1, 1))


def mad_zscore(values: pd.Series) -> pd.Series:
    """Same-date sample z-score; do not amplify a numerically constant section."""
    clean = coalesced(values)
    valid = clean.dropna()
    if len(valid) < 2 or valid.nunique() < 2:
        return pd.Series(np.nan, index=values.index)

    def median_of(data: NDArray[np.float64]) -> float:
        ordered = np.sort(data)
        mid = len(ordered) // 2
        return float(ordered[mid]) if len(ordered) % 2 else mean(ordered[mid - 1 : mid + 1])

    # Find the raw median/MAD before scaling: one huge outlier must not underflow
    # the genuinely dispersed tiny majority into zero before winsorization.
    median = median_of(valid.to_numpy())
    with np.errstate(over="ignore", invalid="ignore"):
        mad = median_of(np.abs(valid.to_numpy() - median))
        if np.isfinite(mad) and not indistinguishable(mad, 0.0, floor=abs(median)):
            radius = 3 * 1.4826 * mad
            clean = clean.clip(median - radius, median + radius)
    valid = clean.dropna()
    centered = pd.Series(np.nan, index=values.index)
    centered.loc[valid.index] = _centered(valid.to_numpy())
    width = float(centered.abs().max())
    if width == 0:
        return pd.Series(np.nan, index=values.index)
    centered /= width
    std = math.sqrt(math.fsum(float(v * v) for v in centered.dropna()) / (len(valid) - 1))
    return centered / std
