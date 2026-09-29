"""One raw-candle anchor for charts, structural ranges and MACD evidence."""
from __future__ import annotations

from datetime import datetime

from easy_tdx.chanlun.types import FX, FXType, Kline


def extreme_bar(point: FX) -> Kline | None:
    """Last matching directional extreme inside the central merged candle.

    Preserve the chart/proof tolerance and last-equal-extreme convention. The
    merged candle's final raw index/date is only a fallback when source candles
    are absent or none matches. This is a spatial anchor, not confirmation time.
    """
    field = 'high' if point.fx_type == FXType.DING else 'low'
    tolerance = max(1e-8, abs(point.val) * 1e-9)
    return next((bar for bar in reversed(point.k.klines)
                 if abs(getattr(bar, field) - point.val) <= tolerance), None)


def extreme_index(point: FX) -> int:
    bar = extreme_bar(point)
    return bar.index if bar is not None else point.k.k_index


def extreme_date(point: FX) -> datetime:
    bar = extreme_bar(point)
    return bar.date if bar is not None else point.k.date
