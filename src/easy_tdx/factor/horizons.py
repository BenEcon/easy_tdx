"""Explicit bounded horizon selection, shared by new requests and frozen records."""

from __future__ import annotations

HORIZON_VERSION = "factor-multi-horizon-v1"


def normalize_horizons(horizon: int, horizons: list[int] | None) -> list[int]:
    if horizons is None:
        return [horizon]
    if (
        not isinstance(horizons, list)
        or not 1 <= len(horizons) <= 4
        or any(type(h) is not int or h not in (1, 5, 10, 20) for h in horizons)
        or len(set(horizons)) != len(horizons)
        or type(horizon) is not int
        or horizon not in horizons
    ):
        raise ValueError("远期窗口须为不重复的 1／5／10／20，且包含主窗口；未增删窗口")
    return sorted(horizons)
