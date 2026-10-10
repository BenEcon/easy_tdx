"""Closed-bar valuation availability and causal common-period sampling.

Original price/trade labels are never rewritten. A carried weekly valuation at
a month end is an as-of estimate, not a claim to have that day's market price.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.backtest.performance_sampling import MINUTES, _dates
from easy_tdx.backtest.types import BacktestResult
from easy_tdx.computation import computation_checkpoint
from easy_tdx.web.trading_calendar import VERSION, is_session, last_session

CONTRACT = "closed-valuation-v2"
PERIODS = {"WEEK": "W-SUN", "MONTH": "M", "SEASON": "Q", "YEAR": "Y"}
ORDER = {"DAY": 0, "WEEK": 1, "MONTH": 2, "SEASON": 3, "YEAR": 4}


def local_dates(column: pd.Series) -> pd.DatetimeIndex:
    dates = _dates(column)
    if dates.tz is not None:
        dates = dates.tz_convert("Asia/Shanghai").tz_localize(None)
    if dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError("组合成员净值时间缺失、重复或乱序")
    return dates


def period_close(stamp: pd.Timestamp, category: str) -> pd.Timestamp | None:
    """None is a verified period with no sessions; unknown coverage is an error."""
    if category == "DAY" or category in MINUTES:
        start = end = stamp.date()
    else:
        period = stamp.to_period(PERIODS[category])
        start, end = period.start_time.date(), period.end_time.date()
    if is_session(start) is None or is_session(end) is None:
        raise ValueError("交易日历未覆盖估值周期，不能确认收盘时点")
    session = last_session(start, end)
    return pd.Timestamp(session) + pd.Timedelta(hours=15) if session else None


def observations(result: BacktestResult, *, normalize_legacy: bool = False) -> pd.DataFrame:
    """Return available closed observations, preserving each original source label."""
    curve = result.equity_curve
    if curve.empty:
        return pd.DataFrame(columns=["datetime", "total", "source_time"])
    dates = local_dates(curve["datetime"])
    basis = result.config.get("performance_basis", {})
    category = basis.get("input_category", "DAY")
    legacy = basis.get("category_source", "legacy_daily_default") == "legacy_daily_default"
    label = result.config.get("bar_time", "end")
    if label not in {"start", "end"}:
        raise ValueError("未知 K 线时间标签，无法确认估值可用时点")
    ends: list[pd.Timestamp] = []
    for i, stamp in enumerate(dates):
        if i % 64 == 0:
            computation_checkpoint()
        if legacy and not normalize_legacy:
            end = stamp
        elif category in MINUTES:
            if category == "INTRADAY" and label == "start":
                raise ValueError("未声明分钟长度，无法将起点标签换算为收盘估值")
            end = stamp + pd.Timedelta(minutes=int(category[4:])) if label == "start" else stamp
        elif category == "DAY":
            end = stamp.normalize() + pd.Timedelta(hours=15)
        else:
            end = period_close(stamp, category)
            if end is None:
                raise ValueError("无交易日的周期出现净值，不能确认估值时点")
        ends.append(end)
    available = pd.DatetimeIndex(ends)
    if "period_end" in curve:
        recorded = local_dates(curve["period_end"])
        if not recorded.equals(available):
            raise ValueError("记录的 period_end 与声明周期收盘时点不一致")
    if available.has_duplicates or not available.is_monotonic_increasing:
        raise ValueError("组合成员收盘估值时间重复或乱序")
    closed = np.ones(len(curve), dtype=bool)
    if "is_closed" in curve:
        if not all(isinstance(value, bool | np.bool_) for value in curve.is_closed):
            raise ValueError("收盘标记必须为布尔值")
        closed = curve.is_closed.to_numpy(dtype=bool)
    return (
        pd.DataFrame({"datetime": available, "total": curve.total.to_numpy(), "source_time": dates})
        .loc[closed]
        .reset_index(drop=True)
    )


def expected_close(target: pd.Timestamp, category: str) -> pd.Timestamp:
    """Latest completed native period at target, skipping verified closed weeks."""
    cursor = target
    while True:
        computation_checkpoint()
        end = period_close(cursor, category)
        if end is not None and end <= target:
            return end
        if category in PERIODS:
            cursor = cursor.to_period(PERIODS[category]).start_time - pd.Timedelta(days=1)
        else:
            cursor -= pd.Timedelta(days=1)


def common_samples(
    results: dict[str, BacktestResult], allocations: dict[str, float]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Sample on the coarsest completed period; never drop an invalid interval.

    Every target and every member has an audit record. Missing expected native
    closes produce NaN, so annualization cannot silently compress missing periods.
    """
    categories = {
        key: result.config.get("performance_basis", {}).get("input_category", "DAY")
        for key, result in results.items()
    }
    category = max(
        ("DAY" if value in MINUTES else value for value in categories.values()),
        key=ORDER.__getitem__,
    )
    frames = {key: observations(result, normalize_legacy=True) for key, result in results.items()}
    evidence: dict[str, Any] = {
        "valuation_contract": CONTRACT,
        "calendar_version": VERSION,
        "sample_category": category,
        "member_categories": categories,
        "valuation_policy": "latest_closed_native_period_at_common_close",
        "valuation_samples": [],
        "excluded_targets": [],
        "closed_period_samples": [],
        "unavailable_reason": None,
    }
    empty = pd.DataFrame(columns=["datetime", "total", "closed_period"])
    if any(frame.empty for frame in frames.values()):
        evidence["unavailable_reason"] = "存在没有已收盘净值的成员，无法建立共同采样"
        return empty, evidence
    start = max(frame.datetime.iloc[0] for frame in frames.values())
    stop = max(frame.datetime.iloc[-1] for frame in frames.values())
    if category == "DAY":
        candidates = pd.date_range(start.normalize(), stop.normalize(), freq="D")
    else:
        candidates = pd.period_range(start, stop, freq=PERIODS[category]).to_timestamp()
    rows: list[dict[str, Any]] = []
    cash_only = sum(value for key, value in allocations.items() if key not in results)
    for stamp in candidates:
        computation_checkpoint()
        target = period_close(stamp, category)
        closed_period = target is None and category != "DAY"
        if closed_period:
            # A calendar-period observation, not a market close. Every member
            # still independently proves its latest completed native period.
            target = stamp.to_period(PERIODS[category]).end_time.normalize() + pd.Timedelta(
                hours=15
            )
        if target is None or target < start or target > stop:
            continue
        outside = [
            key
            for key, frame in frames.items()
            if expected_close(target, categories[key]) > frame.datetime.iloc[-1]
        ]
        if outside:
            evidence["excluded_targets"].append(
                {
                    "datetime": target.isoformat(),
                    "members": outside,
                    "reason": "超出成员已观测原生周期范围，不外推尾部绩效",
                }
            )
            continue
        total = float(cash_only)
        members = []
        valid = True
        for key, frame in frames.items():
            native = categories[key]
            expected = expected_close(target, native)
            position = frame.datetime.searchsorted(target, side="right") - 1
            actual = frame.iloc[position] if position >= 0 else None
            available = actual.datetime if actual is not None else None
            reason = None
            if actual is None or available != expected:
                reason = "缺少该时点应有的已收盘估值；不以更早数据或未来数据替代"
            elif not np.isfinite(actual.total) or actual.total <= 0:
                reason = "成员净值非有限或不为正"
            members.append(
                {
                    "member": key,
                    "category": native,
                    "expected_time": expected.isoformat(),
                    "valuation_time": available.isoformat() if available is not None else None,
                    "source_time": actual.source_time.isoformat() if actual is not None else None,
                    "asof_age_seconds": (target - available).total_seconds()
                    if available is not None
                    else None,
                    "reason": reason,
                }
            )
            if reason:
                valid = False
            else:
                assert actual is not None
                total += float(actual.total)
        rows.append(
            {
                "datetime": target,
                "total": total if valid else float("nan"),
                "closed_period": closed_period,
            }
        )
        evidence["valuation_samples"].append(
            {
                "datetime": target.isoformat(),
                "valid": valid,
                "members": members,
                "closed_period": closed_period,
            }
        )
        if closed_period:
            evidence["closed_period_samples"].append(
                {
                    "period": str(stamp.to_period(PERIODS[category])),
                    "datetime": target.isoformat(),
                    "valuation": total if valid else None,
                    "reason": "交易所整周期休市，各成员沿用最近应完成原生周期；非新增行情",
                }
            )
    if any(not row["valid"] for row in evidence["valuation_samples"]):
        evidence["unavailable_reason"] = "共同采样存在缺失或无效成员估值，未跳过缺口计算年化"
    if not rows:
        evidence["unavailable_reason"] = "成员周期不同且没有共同已收盘采样时点"
    return pd.DataFrame(rows, columns=["datetime", "total", "closed_period"]), evidence
