"""Exact bar identity shared by signals, matching and portfolio accounting.

Daily integer dates remain supported. A date-only query is not an intraday
timestamp: if more than one distinct bar time exists that day, never guess.
"""

from __future__ import annotations

import datetime as dt
from numbers import Integral
from typing import Any, TypeAlias

import numpy as np
import pandas as pd

from easy_tdx.computation import computation_checkpoint

SignalTime: TypeAlias = int | pd.Timestamp
BAR_TIME_CONTRACT = "exact-bar-time-v1"


def _key(value: Any) -> Any:
    if isinstance(value, pd.Timestamp | np.datetime64 | dt.datetime | dt.date):
        return pd.Timestamp(value)
    if isinstance(value, Integral):
        return int(value)
    return value


def _day(stamp: pd.Timestamp) -> int:
    return int(stamp.year * 10000 + stamp.month * 100 + stamp.day)


def time_key(value: Any) -> Any:
    """Hash instants by exact nanoseconds, avoiding timezone/fold hash variance."""
    key = _key(value)
    if isinstance(key, pd.Timestamp) and not pd.isna(key):
        return ("aware" if key.tz is not None else "naive", key.value)
    return key


def signal_times(column: pd.Series) -> list[SignalTime]:
    """Full timestamps (including tz/ns), retaining legacy midnight-day ints."""
    values = [_key(value) for value in column]
    if not values:
        return []
    if all(isinstance(value, pd.Timestamp) and not pd.isna(value) for value in values):
        if all(value == value.normalize() for value in values):
            return [_day(value) for value in values]
        return values
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return values
    raise ValueError("回测时间必须为完整时间戳或整数日期，不能缺失或混用类型")


class BarTimeIndex:
    """Run-local exact timestamp → first positional row, plus unambiguous days."""

    def __init__(self, column: pd.Series) -> None:
        self.positions: dict[Any, int] = {}
        self.days: dict[int, int] = {}
        self.ambiguous_days: set[int] = set()
        for position, raw in enumerate(column):
            if position % 1024 == 0:
                computation_checkpoint()
            key = _key(raw)
            if pd.isna(key):
                continue
            self.positions.setdefault(time_key(key), position)
            if isinstance(key, pd.Timestamp):
                day = _day(key)
                previous = self.days.setdefault(day, position)
                if time_key(column.iloc[previous]) != time_key(key):
                    self.ambiguous_days.add(day)

    def get(self, value: Any) -> int | None:
        key = _key(value)
        position = self.positions.get(time_key(key))
        if position is not None:
            return position
        if isinstance(key, Integral):
            if key in self.ambiguous_days:
                raise ValueError("同一天有多根 K 线，日期不足以定位信号或成交，请保留完整时间")
            return self.days.get(int(key))
        # Integer daily frames accept midnight, never an arbitrary intraday time.
        if isinstance(key, pd.Timestamp) and not pd.isna(key) and key == key.normalize():
            return self.positions.get(_day(key))
        return None
