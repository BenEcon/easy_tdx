"""Dataclass → DataFrame 转换工具。"""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass, replace
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# K 线时间戳语义：通达信用 bar 开始时间，Tushare/同花顺用 bar 结束时间。
# bar_time="end" 时给分钟级 bar 的时刻加上一个周期时长，以对齐 Tushare。
_BAR_TIME_START = "start"
_BAR_TIME_END = "end"

# A 股 / 扩展行情 KlineCategory → 每根 bar 的分钟数（分钟级；日线及以上不在此表）。
# category: 0=MIN_5 1=MIN_15 2=MIN_30 3=MIN_60 7=MIN_1 8=MIN_3。
_CATEGORY_MINUTES: dict[int, int] = {0: 5, 1: 15, 2: 30, 3: 60, 7: 1, 8: 3}


_VALID_BAR_TIMES = (_BAR_TIME_START, _BAR_TIME_END)


def _check_bar_time(bar_time: str) -> None:
    """校验 bar_time 取值，非法值立即抛错（fail-fast），避免静默按 "end" 处理。"""
    if bar_time not in _VALID_BAR_TIMES:
        raise ValueError(
            f"bar_time 必须是 {_BAR_TIME_START!r} 或 {_BAR_TIME_END!r}，得到: {bar_time!r}"
        )


def _category_to_minutes(category: int) -> int | None:
    """分钟级 KlineCategory → 每根 bar 的分钟数；日线及以上返回 None。"""
    return _CATEGORY_MINUTES.get(int(category))


def _period_to_minutes(period: int, times: int = 1) -> int | None:
    """MAC 协议 Period → 每根 bar 的分钟数。

    MINS / SECONDS 配合 times 倍数；日线及以上 / 秒级（按分钟粒度对齐无意义）返回 None。
    """
    # 与 symbol_bar.py 的 is_intraday 判定保持一致
    _MAC_INTRADAY_MINUTES: dict[int, int] = {
        0: 5,  # MIN_5
        1: 15,  # MIN_15
        2: 30,  # MIN_30
        3: 60,  # MIN_60
        7: 1,  # MIN_1
        8: 5,  # MINS（×times）
    }
    base = _MAC_INTRADAY_MINUTES.get(int(period))
    if base is None:
        # 4=DAILY 5=WEEKLY 6=MONTHLY 9=DAYS 10=QUARTERLY 11=YEARLY 13=SECONDS 均不偏移
        return None
    if int(period) == 8:  # MINS：多分钟，乘以倍数
        return base * max(int(times), 1)
    return base


def _to_df(data: Any) -> pd.DataFrame:
    """将 list[dataclass] 或单个 dataclass 转为 DataFrame。

    自动丢弃以 ``_`` 开头的内部字段（如 ``_raw``）。
    仅处理 year/month/day（无 hour/minute）→ date 的合并；
    SecurityBar 的完整 datetime 合并由调用方按周期决定。
    """
    if isinstance(data, list):
        if not data:
            return pd.DataFrame()
        rows = []
        for item in data:
            d = _clean_dict(item)
            rows.append(d)
        return pd.DataFrame(rows)
    if is_dataclass(data) and not isinstance(data, type):
        return pd.DataFrame([_clean_dict(data)])
    raise TypeError(f"不支持转换为 DataFrame 的类型: {type(data)}")


def _clean_dict(item: Any) -> dict[str, Any]:
    d = asdict(item)
    d = {k: v for k, v in d.items() if not k.startswith("_")}
    return _merge_datetime_fields(d)


def _merge_datetime_fields(d: dict[str, Any]) -> dict[str, Any]:
    """将仅含 year/month/day（无 hour/minute）的模型合并为 date 列。"""
    if all(k in d for k in ("year", "month", "day")) and not all(
        k in d for k in ("hour", "minute")
    ):
        dt = pd.Timestamp(year=d["year"], month=d["month"], day=d["day"])
        result: dict[str, Any] = {"date": dt}
        result.update({k: v for k, v in d.items() if k not in {"year", "month", "day"}})
        return result
    return d


def _align_minutes_df(df: pd.DataFrame, delta_minutes: int) -> pd.DataFrame:
    """对含 hour/minute 列的 DataFrame 做分钟级偏移（向量化，自动跨小时/跨日）。

    用于 A 股 / 扩展行情路径：在 _merge_bar_datetime 拼字符串之前修正 hour/minute。
    """
    total = df["hour"] * 60 + df["minute"] + delta_minutes
    df = df.copy()
    df["hour"] = (total // 60) % 24
    df["minute"] = total % 60
    return df


def _align_datetime_df(df: pd.DataFrame, delta_minutes: int) -> pd.DataFrame:
    """对含 datetime 列的 DataFrame 做分钟级偏移（MAC 路径用）。"""
    if "datetime" not in df.columns:
        return df
    df = df.copy()
    df["datetime"] = df["datetime"] + pd.Timedelta(minutes=delta_minutes)
    return df


def _apply_bar_time_align_df(
    df: pd.DataFrame,
    *,
    is_intraday: bool,
    delta_minutes: int | None,
    bar_time: str,
    has_time_columns: bool,
) -> pd.DataFrame:
    """对 K 线 DataFrame 应用 bar 时间对齐。

    Args:
        is_intraday: 是否分钟级周期（False 时恒不偏移）。
        delta_minutes: 每根 bar 的分钟数（None 或分钟级判定为 False 时不偏移）。
        bar_time: "start"（默认，通达信原始）或 "end"（右端点，对齐 Tushare）。
        has_time_columns: True=DataFrame 仍是分散的 hour/minute 列（A 股路径，
            在 _merge_bar_datetime 之前调用）；False=已是 datetime 列（MAC 路径）。
    """
    if bar_time == _BAR_TIME_START:
        return df
    _check_bar_time(bar_time)
    if not is_intraday or delta_minutes is None or delta_minutes <= 0:
        return df
    if df.empty:
        return df
    if has_time_columns:
        if "hour" not in df.columns or "minute" not in df.columns:
            return df
        return _align_minutes_df(df, delta_minutes)
    return _align_datetime_df(df, delta_minutes)


def _apply_bar_time_align_bars(
    bars: list[Any],
    *,
    is_intraday: bool,
    delta_minutes: int | None,
    bar_time: str,
) -> list[Any]:
    """对 K 线 dataclass 列表应用 bar 时间对齐（扩展行情 ex client 用，返回 dataclass）。

    用 dataclasses.replace 重建（保持 dataclass 不可变语义），跨小时自动进位；
    收盘 bar 不会跨日，故不处理跨日。
    """
    if bar_time == _BAR_TIME_START:
        return bars
    _check_bar_time(bar_time)
    if not is_intraday or delta_minutes is None or delta_minutes <= 0:
        return bars
    result: list[Any] = []
    for b in bars:
        total = b.hour * 60 + b.minute + delta_minutes
        result.append(replace(b, hour=(total // 60) % 24, minute=total % 60))
    return result


def _merge_bar_datetime(df: pd.DataFrame, daily_plus: bool) -> pd.DataFrame:
    """根据 K 线周期将 SecurityBar 的分散字段合并为 date 或 datetime。

    Args:
        daily_plus: True 表示日线及以上周期（DAY/WEEK/MONTH/YEAR），只保留 date；
                    False 表示分钟线（MIN_1/5/15/30/60），保留完整 datetime。
    """
    if df.empty or "year" not in df.columns:
        return df
    date_str = (
        df["year"].astype(str)
        + "-"
        + df["month"].astype(str).str.zfill(2)
        + "-"
        + df["day"].astype(str).str.zfill(2)
    )
    if daily_plus:
        df.insert(0, "date", pd.to_datetime(date_str))
    else:
        full_str = (
            date_str
            + " "
            + df["hour"].astype(str).str.zfill(2)
            + ":"
            + df["minute"].astype(str).str.zfill(2)
        )
        df.insert(0, "datetime", pd.to_datetime(full_str))
    df.drop(columns=["year", "month", "day", "hour", "minute"], inplace=True)
    return df


def _merge_txn_datetime(df: pd.DataFrame, date_int: int) -> pd.DataFrame:
    """将逐笔成交的 date + hour:minute 合并为 datetime 列。"""
    if df.empty or "hour" not in df.columns:
        return df
    year = date_int // 10000
    month = (date_int // 100) % 100
    day = date_int % 100
    base = pd.Timestamp(year=year, month=month, day=day)
    offsets = pd.to_timedelta(df["hour"] * 3600 + df["minute"] * 60, unit="s")
    df.insert(0, "datetime", base + offsets)
    df.drop(columns=["hour", "minute"], inplace=True)
    return df


def _add_minute_datetime(df: pd.DataFrame, date_int: int) -> pd.DataFrame:
    """为分时 DataFrame 添加 datetime 列（从 bar 索引计算时间）。

    A 股分时 240 条：0-119 = 9:30~11:29（上午），120-239 = 13:00~14:59（下午）。
    """
    if df.empty:
        return df
    year = date_int // 10000
    month = (date_int // 100) % 100
    day = date_int % 100
    base = pd.Timestamp(year=year, month=month, day=day)
    n = len(df)
    morning = list(range(9 * 60 + 30, 9 * 60 + 30 + 120))
    afternoon = list(range(13 * 60, 13 * 60 + 120))
    all_minutes = (morning + afternoon)[:n]
    offsets = pd.to_timedelta(all_minutes, unit="m")
    df.insert(0, "datetime", base + offsets)
    return df
