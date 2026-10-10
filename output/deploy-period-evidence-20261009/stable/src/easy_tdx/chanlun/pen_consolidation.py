"""Rolling three-pen overlap observations, independent of structural centres."""

from typing import Any

from easy_tdx.chanlun.anchors import extreme_date
from easy_tdx.chanlun.types import BI


def recent_pen_consolidations(bis: list[BI], limit: int = 4) -> list[dict[str, Any]]:
    """Keep repeated price ranges: each adjacent triple is a separate observation.

    Include the live last pen, but label its window provisional. This does not
    promote an overlap to a structural centre or feed any trading signal.
    """
    windows = []
    for i in range(2, len(bis)):
        triple = bis[i - 2 : i + 1]
        if any(a.direction == b.direction for a, b in zip(triple, triple[1:])):
            continue
        if any(a.end != b.start for a, b in zip(triple, triple[1:])):
            continue
        lower = max(pen.low for pen in triple)
        upper = min(pen.high for pen in triple)
        if lower >= upper:  # A point contact is not a rectangular overlap.
            continue
        windows.append(
            {
                "pen_indices": [pen.index for pen in triple],
                "start_date": extreme_date(triple[0].start).isoformat(sep=" "),
                "end_date": extreme_date(triple[-1].end).isoformat(sep=" "),
                "lower": lower,
                "upper": upper,
                "confirmed": all(pen.confirmed_index is not None for pen in triple),
                "source": "rolling_three_pen_overlap",
                "eligible_for_trading": False,
            }
        )
    return windows[-max(0, limit) :] if limit > 0 else []
