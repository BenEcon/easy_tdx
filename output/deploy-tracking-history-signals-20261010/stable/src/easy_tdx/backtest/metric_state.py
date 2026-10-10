"""Explicit meaning of non-finite metrics across Python, JSON and saved results."""

from __future__ import annotations

import math

CONTRACT = "performance-metrics-v1"


def metric_states(
    metrics: dict[str, float], reasons: dict[str, str] | None = None
) -> dict[str, dict[str, str]]:
    """JSON stores non-finite numbers as null; retain their meaning separately."""
    reasons = reasons or {}
    result = {}
    for key, value in metrics.items():
        state = (
            "finite"
            if math.isfinite(value)
            else "unavailable"
            if math.isnan(value)
            else "positive_infinity"
            if value > 0
            else "negative_infinity"
        )
        result[key] = {
            "state": state,
            "reason": reasons.get(key, "" if state == "finite" else "计算条件不足或数值超出范围"),
        }
    return result


def ranking_key(value: float) -> tuple[bool, float]:
    """Only finite returns are eligible for a best result; invalid rows sort last."""
    return math.isfinite(value), value if math.isfinite(value) else 0.0
