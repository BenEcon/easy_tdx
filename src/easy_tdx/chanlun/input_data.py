"""Validate without dropping/reordering rows used by chart and factor indices."""
from math import isfinite
from numbers import Number

import pandas as pd


class ChanlunInputError(ValueError):
    """Rejected market data, distinguishable from internal calculation failures."""


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Canonicalise date/numeric types; chronology is checked after append merging.

    Missing/invalid rows must never be silently skipped: doing so disconnects
    raw indices from prices, confirmation dates and downstream factor positions.
    """
    frame = df.copy()
    if len(frame) == 0:
        return frame
    if not frame.columns.is_unique:
        raise ChanlunInputError('K 线列名不可重复')
    date_column = 'datetime' if 'datetime' in frame else 'date'
    required = [date_column, 'open', 'close', 'high', 'low']
    missing = [column for column in required if column not in frame]
    if missing:
        raise ChanlunInputError(f"K 线缺少必要列：{', '.join(missing)}")
    dates = []
    for i, value in enumerate(frame[date_column]):
        try:
            if isinstance(value, Number):
                raise ValueError('numeric timestamp')
            date = pd.Timestamp(value)
            if pd.isna(date) or date.tzinfo is not None:
                raise ValueError('missing date or ambiguous timezone')
        except (TypeError, ValueError, OverflowError) as exc:
            raise ChanlunInputError(
                f'第 {i + 1} 根 K 线时间无效，请使用不附带时区的交易所本地时间'
            ) from exc
        dates.append(date)
    frame['datetime'] = dates
    if 'vol' not in frame:
        frame['vol'] = 0.0
    for column in ('open', 'close', 'high', 'low', 'vol'):
        values = pd.to_numeric(frame[column], errors='coerce')
        for i, value in enumerate(values):
            if pd.isna(value) or not isfinite(float(value)):
                raise ChanlunInputError(f'第 {i + 1} 根 K 线 {column} 必须是有限数值')
        frame[column] = values.astype(float)
    if (frame['high'] < frame['low']).any():
        raise ChanlunInputError('K 线最高价不得低于最低价')
    if (frame['vol'] < 0).any():
        raise ChanlunInputError('K 线成交量不得为负数')
    return frame


def require_chronological(frame: pd.DataFrame) -> None:
    if not frame.empty:
        dates = frame['datetime']
        if dates.duplicated().any() or not dates.is_monotonic_increasing:
            raise ChanlunInputError('K 线时间必须严格递增，不可重复；请先整理行情顺序')
