"""Shared summaries for full and boundary-purged factor diagnostics."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.factor.statistics import distinct_count


def number(value: Any) -> float | None:
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def summarize_rows(name: str, coverage: float, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Caller owns the rows; rolling IC is recalculated within this sample only."""
    ranked = pd.Series([row["rank_ic"] for row in rows], dtype=float)
    valid = ranked.dropna()
    rolling = ranked.rolling(20, min_periods=20).mean()
    for row, value in zip(rows, rolling, strict=True):
        row["rolling_rank_ic"] = number(value)
    std = valid.std() if len(valid) > 1 else np.nan
    layers = pd.DataFrame([row["layers"] for row in rows], dtype=float)
    spread = pd.Series([row["layer_spread"] for row in rows], dtype=float)
    return {
        "name": name,
        "coverage": coverage,
        "observations": len(valid),
        "ic_mean": number(pd.Series([row["ic"] for row in rows], dtype=float).mean()),
        "rank_ic_mean": number(valid.mean()),
        "rank_ic_ir": number(valid.mean() / std)
        if std > 0 and distinct_count(valid, floor=1.0) > 1
        else None,
        "positive_rate": number((valid > 0).mean()) if len(valid) else None,
        "layer_means": [number(value) for value in layers.mean()],
        "spread": number(spread.mean()),
        "layer_dates": int(spread.notna().sum()),
        "diagnostics": dict(Counter(row["reason"] for row in rows if row["reason"])),
        "daily": rows,
    }
