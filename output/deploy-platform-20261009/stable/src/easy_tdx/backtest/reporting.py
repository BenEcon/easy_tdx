"""Lossless metric meaning in human-readable and strict machine-readable reports."""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Iterable
from typing import Any

from easy_tdx.backtest.metric_state import metric_states


def metric_text(value: Any, fmt: str = ".2f") -> str:
    if value is None or isinstance(value, bool):
        return "—"
    number = float(value)
    if math.isnan(number):
        return "—"
    if math.isinf(number):
        return "∞" if number > 0 else "−∞"
    return format(number, fmt)


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: clean_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [clean_json(item) for item in value]
    if hasattr(value, "item"):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def strict_json(value: Any) -> str:
    return json.dumps(clean_json(value), ensure_ascii=False, indent=2, allow_nan=False)


def metrics_csv(groups: Iterable[tuple[str, dict[str, float], dict[str, Any]]]) -> str:
    """One metric per row, with a state/reason instead of nonstandard NaN/Infinity."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["scope", "metric", "value", "state", "reason"])
    for scope, metrics, basis in groups:
        states = basis.get("metric_status") or metric_states(metrics)
        for key, value in metrics.items():
            state = states.get(key) or metric_states({key: value})[key]
            writer.writerow(
                [scope, key, value if math.isfinite(value) else "", state["state"], state["reason"]]
            )
    return buffer.getvalue()
