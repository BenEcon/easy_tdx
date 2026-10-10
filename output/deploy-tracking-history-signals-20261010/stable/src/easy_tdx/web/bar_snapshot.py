"""Explicit data provenance and conservative completion boundaries for A-share bars."""

import hashlib
import json
import math
from calendar import monthrange
from datetime import datetime, timedelta
from typing import Any, Literal, TypedDict
from zoneinfo import ZoneInfo

import pandas as pd

from easy_tdx.web.trading_calendar import (
    COVERAGE_LABEL,
    HOLIDAY_RANGES,
    VERSION,
    is_session,
    last_session,
    missing_sessions,
)


class QualityReport(TypedDict):
    """Stable quality fields shared by all consumers; absent bars are not filled."""

    status: Literal["ok", "warning", "error"]
    errors: list[str]
    warnings: list[str]
    invalid_bar_indices: list[int]
    missing_session_count: int
    missing_sessions: list[str]
    missing_bar_count: int
    missing_bar_samples: list[str]
    calendar_unverified_years: list[int]
    suspension_status: Literal["not_verified"]


def mark_indicator_closed_bars(
    frame: pd.DataFrame, category: str, now: datetime | None = None, *, bar_time: str | None = None
) -> pd.DataFrame:
    """Preserve chart rows but never finalize indicators from an open candle.

    Respect provenance when present, retain the old start-label default only
    for caller-supplied frames without a timestamp convention.
    """
    result = frame.copy()
    now = now or datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    dates = result["datetime"] if "datetime" in result else result["date"]
    existing = result["is_closed"] if "is_closed" in result else [True] * len(result)
    label = bar_time or frame.attrs.get("snapshot_metadata", {}).get("bar_time", "start")
    result["is_closed"] = [
        bool(closed) and period_end(pd.Timestamp(stamp).to_pydatetime(), category, label) <= now
        for stamp, closed in zip(dates, existing)
    ]
    return result


def period_end(stamp: datetime, category: str, bar_time: str = "start") -> datetime:
    category = category.upper()
    if category.startswith("MIN_"):
        return stamp if bar_time == "end" else stamp + timedelta(minutes=int(category[4:]))
    day = stamp.replace(hour=15, minute=0, second=0, microsecond=0)
    if category == "WEEK":
        monday = day - timedelta(days=day.weekday())
        friday = monday + timedelta(days=4)
        session = last_session(monday.date(), friday.date())
        return datetime.combine(session, day.time()) if session else friday
    if category in ("MONTH", "YEAR", "SEASON"):
        month = (
            12
            if category == "YEAR"
            else ((day.month - 1) // 3 + 1) * 3
            if category == "SEASON"
            else day.month
        )
        end = day.replace(month=month, day=monthrange(day.year, month)[1])
        first_month = 1 if category == "YEAR" else month - 2 if category == "SEASON" else month
        session = last_session(day.replace(month=first_month, day=1).date(), end.date())
        return datetime.combine(session, day.time()) if session else end
    return day


def quality_report(
    records: list[dict[str, Any]], category: str, bar_time: str = "start"
) -> QualityReport:
    """Do not fill missing bars or infer suspension from absent data."""
    raw_dates = [r.get("datetime", r.get("date")) for r in records]
    if any(isinstance(d, int | float) for d in raw_dates):
        raise ValueError("行情时间不得使用无单位数字")
    try:
        dates = [pd.Timestamp(d) for d in raw_dates]
    except (ValueError, TypeError) as exc:
        raise ValueError("行情存在无法解析的时间") from exc
    if any(pd.isna(d) or d.tzinfo is not None for d in dates):
        raise ValueError("行情时间必须为有效的交易所本地时间，不得混入时区或空时间")
    errors, warnings = [], []
    if any(a >= b for a, b in zip(dates, dates[1:])):
        errors.append("行情时间重复或非严格递增；未自动排序或覆盖重复数据")
    if any("is_closed" in r and not isinstance(r["is_closed"], bool) for r in records):
        errors.append("收盘标记必须为布尔值，不接受字符串或空值")
    closed_flags = [r.get("is_closed", True) for r in records]
    if any(a is False and b is True for a, b in zip(closed_flags, closed_flags[1:])):
        errors.append("历史区间包含未收盘标记断层，不能删除后拼成连续行情")
    invalid = []
    missing_columns: set[str] = set()
    for i, r in enumerate(records):
        if not all(k in r for k in ("open", "high", "low", "close")):
            missing_columns.update(k for k in ("open", "high", "low", "close") if k not in r)
            continue
        try:
            o, h, low, c = [float(r[k]) for k in ("open", "high", "low", "close")]
            v = float(r.get("vol", 0))
            amount = float(r.get("amount", 0))
            if (
                not all(math.isfinite(n) for n in (o, h, low, c, v, amount))
                or min(o, h, low, c) <= 0
                or min(v, amount) < 0
                or not low <= min(o, c) <= max(o, c) <= h
            ):
                invalid.append(i)
        except (TypeError, ValueError):
            invalid.append(i)
    if invalid:
        errors.append(f"{len(invalid)} 根 OHLC / 成交数据不合法")
    if missing_columns:
        errors.append("行情缺少价格字段：" + "、".join(sorted(missing_columns)))
    missing = []
    if dates and not errors and category == "DAY":
        missing = missing_sessions(dates[0].date(), dates[-1].date(), {d.date() for d in dates})
        if missing:
            warnings.append(f"{len(missing)} 个交易日无行情；可能为停牌或数据缺失，未补造 K 线")
    minute_count = 0
    minute_samples: list[str] = []
    if dates and not errors and category.startswith("MIN_"):
        step = int(category[4:])
        observed = set(dates)
        day = dates[0].normalize()
        # Only audit known calendar dates inside the observed interval. Lunch,
        # overnight and holidays are never interpreted as missing candles.
        while day <= dates[-1].normalize():
            if is_session(day.date()) is True:
                for hour, minute in ((9, 30), (13, 0)):
                    origin = day + pd.Timedelta(hours=hour, minutes=minute)
                    for offset in range(
                        step if bar_time == "end" else 0, 121 if bar_time == "end" else 120, step
                    ):
                        stamp = origin + pd.Timedelta(minutes=offset)
                        if dates[0] <= stamp <= dates[-1] and stamp not in observed:
                            minute_count += 1
                            if len(minute_samples) < 100:
                                minute_samples.append(str(stamp))
            day += pd.Timedelta(days=1)
        if minute_count:
            warnings.append(
                f"{minute_count} 个分钟周期无行情；已排除午休及休市，"
                "停牌或数据缺失待核验，未补造 K 线"
            )
    unknown = (
        [year for year in range(min(dates).year, max(dates).year + 1) if year not in HOLIDAY_RANGES]
        if dates
        else []
    )
    if unknown:
        warnings.append("部分年份无已核验交易日历，收盘边界采用保守日历口径")
    return {
        "status": "error" if errors else "warning" if warnings else "ok",
        "errors": errors,
        "warnings": warnings,
        "invalid_bar_indices": invalid,
        "missing_session_count": len(missing),
        "missing_sessions": missing[:100],
        "missing_bar_count": minute_count,
        "missing_bar_samples": minute_samples,
        "calendar_unverified_years": unknown,
        "suspension_status": "not_verified",
    }


def annotate_snapshot(
    records: list[dict[str, Any]],
    category: str,
    *,
    source: str,
    requested_adjust: str,
    actual_adjust: str,
    bar_time: str = "start",
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    category = category.upper()
    quality = quality_report(records, category, bar_time)
    rows = []
    for record in records:
        stamp = pd.Timestamp(record.get("datetime", record.get("date"))).to_pydatetime()
        end = period_end(stamp, category, bar_time)
        rows.append(
            {
                **record,
                "period_end": end.isoformat(sep=" "),
                "is_closed": bool(record.get("is_closed", True)) and end <= now,
            }
        )
    return {
        "data": rows,
        "count": len(rows),
        "metadata": {
            "source": source,
            "requested_adjust": requested_adjust,
            "actual_adjust": actual_adjust,
            "observed_at": now.isoformat(sep=" "),
            "timezone": "Asia/Shanghai",
            "category": category,
            "bar_time": bar_time,
            "completion_policy": "exchange_calendar_with_explicit_fallback",
            "completion_note": (
                f"已核验日历年份：{COVERAGE_LABEL}；周月边界按交易所休市安排。"
                "未覆盖年份保守判断，未收盘柱不作确认依据。"
            ),
            "calendar_version": VERSION,
            "calendar_covered_years": sorted(HOLIDAY_RANGES),
            "quality": quality,
            "last_bar_at": str(records[-1].get("datetime", records[-1].get("date")))
            if records
            else None,
            "last_closed_at": next(
                (r["period_end"] for r in reversed(rows) if r["is_closed"]), None
            ),
            "data_fingerprint": hashlib.sha256(
                json.dumps(records, sort_keys=True, default=str, ensure_ascii=False).encode()
            ).hexdigest(),
            "adjustment_verified": requested_adjust == actual_adjust
            and actual_adjust in {"NONE", "QFQ", "HFQ"},
            "volume_policy": "上游成交量；未独立核验成交量复权口径",
            "historical_data_vintage": False,
        },
    }
