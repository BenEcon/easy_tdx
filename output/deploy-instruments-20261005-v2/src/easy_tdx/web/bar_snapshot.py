"""Explicit data provenance and conservative completion boundaries for A-share bars."""
from calendar import monthrange
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

def mark_indicator_closed_bars(frame: pd.DataFrame, category: str,
                               now: datetime | None = None) -> pd.DataFrame:
    """Preserve chart rows but never finalize indicators from an open candle.

    Use the existing conservative start-label boundary until the provider's
    timestamp convention is explicitly available. No early close is inferred.
    """
    result = frame.copy()
    now = now or datetime.now(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
    dates = result['datetime'] if 'datetime' in result else result['date']
    existing = result['is_closed'] if 'is_closed' in result else [True] * len(result)
    result['is_closed'] = [bool(closed) and period_end(pd.Timestamp(stamp).to_pydatetime(), category) <= now
                           for stamp, closed in zip(dates, existing)]
    return result


def period_end(stamp: datetime, category: str, bar_time: str = 'start') -> datetime:
    if category.startswith('MIN_'):
        return stamp if bar_time == 'end' else stamp + timedelta(minutes=int(category[4:]))
    day = stamp.replace(hour=15, minute=0, second=0, microsecond=0)
    if category == 'WEEK':
        return day + timedelta(days=4 - day.weekday())
    if category in ('MONTH', 'YEAR', 'SEASON'):
        month = 12 if category == 'YEAR' else ((day.month - 1) // 3 + 1) * 3 if category == 'SEASON' else day.month
        return day.replace(month=month, day=monthrange(day.year, month)[1])
    return day


def annotate_snapshot(records: list[dict], category: str, *, source: str,
                      requested_adjust: str, actual_adjust: str,
                      bar_time: str = 'start', now: datetime | None = None) -> dict:
    now = now or datetime.now(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
    rows = []
    for record in records:
        stamp = pd.Timestamp(record.get('datetime', record.get('date'))).to_pydatetime()
        end = period_end(stamp, category, bar_time)
        rows.append({**record, 'period_end': end.isoformat(sep=' '), 'is_closed': end <= now})
    return {'data': rows, 'count': len(rows), 'metadata': {
        'source': source, 'requested_adjust': requested_adjust, 'actual_adjust': actual_adjust,
        'observed_at': now.isoformat(sep=' '), 'timezone': 'Asia/Shanghai',
        'category': category, 'bar_time': bar_time,
        'completion_policy': 'calendar_boundary_conservative',
        'completion_note': '按周期边界保守判断；周月节假日提前收盘未核验，虚线表示尚未确认收盘。',
        'volume_policy': '上游成交量；未独立核验成交量复权口径',
        'historical_data_vintage': False,
    }}
