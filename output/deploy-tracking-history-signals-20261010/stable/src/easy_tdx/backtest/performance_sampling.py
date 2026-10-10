"""Explicit cash-equity return sampling, independent of signal/price resolution.

Annualization is an observed-period estimate (252/52/12/4/1), not an
actual-calendar CAGR or a promise about future returns. Minute returns are
sampled only at 15:00 exchange close; missing closes are never forward-filled.
"""

from __future__ import annotations

from datetime import timedelta
from numbers import Integral
from typing import Any

import numpy as np
import pandas as pd

CONTRACT = "performance-sampling-v5"
FREQUENCIES = {"DAY": 252, "WEEK": 52, "MONTH": 12, "SEASON": 4, "YEAR": 1}
MINUTES = {"MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60", "MIN_120", "INTRADAY"}


def resolve_category(frame: pd.DataFrame, category: str | None = None) -> tuple[str, str]:
    category = category or frame.attrs.get("performance_category")
    metadata = frame.attrs.get("snapshot_metadata", {})
    recorded = metadata.get("category")
    if category is not None and recorded is not None and category.upper() != recorded:
        raise ValueError("绩效周期与冻结行情周期不一致")
    value = category or recorded
    if value is None:
        # Legacy daily callers remain supported, but never collapse intraday
        # timestamps into daily returns. Do not infer weekly/monthly from gaps.
        column = frame.get("datetime", frame.get("date"))
        if column is not None and pd.api.types.is_datetime64_any_dtype(column):
            dates = pd.DatetimeIndex(column)
            if dates.normalize().has_duplicates:
                return "INTRADAY", "inferred_intraday"
        return "DAY", "legacy_daily_default"
    value = str(value).upper()
    if value not in FREQUENCIES and value not in MINUTES:
        raise ValueError(f"不支持的绩效周期：{value}")
    return value, "explicit" if category is not None else "snapshot"


def performance_frame(frame: pd.DataFrame, category: str) -> pd.DataFrame:
    """Bind a validated request period without inventing feed provenance."""
    resolve_category(frame, category)
    result = frame.copy(deep=False)
    result.attrs = dict(frame.attrs)
    result.attrs["performance_category"] = category
    return result


def input_sampling_basis(frame: pd.DataFrame) -> dict[str, Any]:
    """Common sampling schedule for an optimization, not candidate equity proof."""
    category, origin = resolve_category(frame)
    curve = pd.DataFrame(
        {
            "datetime": frame.get("datetime", frame.get("date")),
            "total": frame.get("close", pd.Series(dtype=float)),
        }
    )
    _, basis = sample_equity(curve, category=category, category_source=origin, source=frame)
    basis["scope"] = "input_sampling_schedule"
    return basis


def _dates(column: pd.Series) -> pd.DatetimeIndex:
    if all(isinstance(value, Integral) and not isinstance(value, bool) for value in column):
        return pd.DatetimeIndex(pd.to_datetime(column.astype(str), format="%Y%m%d"))
    return pd.DatetimeIndex(pd.to_datetime(column))


def sample_equity(
    equity: pd.DataFrame,
    *,
    category: str,
    category_source: str,
    source: pd.DataFrame | None = None,
) -> tuple[np.ndarray[Any, np.dtype[np.float64]], dict[str, Any]]:
    """Return measured equity samples plus serializable, result-bound evidence."""
    sample_category = "DAY" if category in MINUTES else category
    basis: dict[str, Any] = {
        "contract_version": CONTRACT,
        "input_category": category,
        "category_source": category_source,
        "sample_category": sample_category,
        "annual_periods": FREQUENCIES[sample_category],
        "annualization_method": "observed_period_compounding",
        "risk_free_method": "annual_rate_divided_by_periods",
        "input_bars": len(equity),
        "sample_count": 0,
        "return_count": 0,
        "sample_start": None,
        "sample_end": None,
        "excluded_bars": 0,
        "warnings": [],
        "unavailable_reason": None,
        "drawdown_duration_unit": "bars",
        "holding_duration_unit": "calendar_days",
        "closed_period_samples": [],
    }
    values = equity["total"].to_numpy(dtype=float)
    observed_mask = np.ones(len(values), dtype=bool)
    if "closed_period" in equity:
        flags = equity["closed_period"]
        if not all(isinstance(value, bool | np.bool_) for value in flags):
            raise ValueError("休市估值标记必须为布尔值")
        observed_mask = ~flags.to_numpy(dtype=bool)
    dates: pd.DatetimeIndex | None = None
    try:
        dates = _dates(equity["datetime"])
    except (KeyError, TypeError, ValueError, OverflowError):
        if category_source != "legacy_daily_default":
            basis["unavailable_reason"] = "缺少有效时间，无法核验绩效采样周期"
    if dates is not None and (
        dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing
    ):
        basis["unavailable_reason"] = "净值时间缺失、重复或乱序，未排序后冒充有效样本"
    if category in MINUTES:
        if dates is None or basis["unavailable_reason"]:
            values = values[:0]
        else:
            ends = dates
            if source is not None and "period_end" in source and len(source) == len(equity):
                ends = _dates(source["period_end"])
            elif source is not None:
                label = source.attrs.get("snapshot_metadata", {}).get("bar_time", "end")
                if label == "start" and category != "INTRADAY":
                    ends = ends + pd.Timedelta(minutes=int(category[4:]))
            if ends.tz is not None:
                ends = ends.tz_convert("Asia/Shanghai")
            mask = (
                (ends.hour == 15)
                & (ends.minute == 0)
                & (ends.second == 0)
                & (ends.nanosecond == 0)
                & (ends.microsecond == 0)
            )
            values = values[mask]
            observed_mask = observed_mask[mask]
            dates = ends[mask]
            basis["excluded_bars"] = int(len(equity) - len(values))
            basis["warnings"].append(
                "分钟年化与风险指标仅使用 15:00 收盘净值；首个收盘前和末个收盘后的收益仅计入总收益"
            )
    if dates is not None and len(dates):
        if dates.tz is not None:
            dates = dates.tz_convert("Asia/Shanghai").tz_localize(None)
        basis["sample_start"], basis["sample_end"] = dates[0].isoformat(), dates[-1].isoformat()
        days = dates.tz_localize(None).normalize() if dates.tz is not None else dates.normalize()
        if sample_category == "DAY" and days.has_duplicates:
            basis["unavailable_reason"] = "日收益采样包含同一天多根净值，未按日线年化"
        elif sample_category != "DAY":
            from easy_tdx.backtest.sampling_calendar import expand_closed_periods
            from easy_tdx.web.trading_calendar import VERSION

            freq = {"WEEK": "W-SUN", "MONTH": "M", "SEASON": "Q", "YEAR": "Y"}[sample_category]
            if not basis["unavailable_reason"]:
                try:
                    dates, values, carried = expand_closed_periods(dates, values, freq)
                    basis["closed_period_samples"] = carried
                    if carried:
                        basis["calendar_version"] = VERSION
                        basis["warnings"].append(
                            f"含 {len(carried)} 个经日历核验的整周期休市估值，"
                            "沿用前值以保留周期长度；"
                            "不补造行情，不改变交易和完整净值"
                        )
                except ValueError as exc:
                    basis["unavailable_reason"] = str(exc)
        elif category_source != "legacy_daily_default":
            from easy_tdx.web.trading_calendar import VERSION, is_session, missing_sessions

            basis["calendar_version"] = VERSION
            observed = {stamp.date() for stamp in days}
            missing = missing_sessions(days[0].date(), days[-1].date(), observed)
            basis["missing_sessions"] = missing
            if missing:
                basis["unavailable_reason"] = "收盘净值缺少交易日，未补零或把多日收益按一天年化"
            elif any(is_session(day) is False for day in observed):
                basis["unavailable_reason"] = "日收益样本包含非交易日，未按交易日年化"
            else:
                day, end = days[0].date(), days[-1].date()
                while day <= end:
                    if is_session(day) is None:
                        basis["unavailable_reason"] = "交易日历未覆盖样本年份，不能核验日收益连续性"
                        break
                    day += timedelta(days=1)
    basis["sample_count"] = len(values)
    basis["observed_sample_count"] = int(observed_mask.sum()) if len(values) else 0
    basis["return_count"] = max(0, len(values) - 1)
    if len(values) < 3 or basis["observed_sample_count"] < 3:
        basis["unavailable_reason"] = (
            basis["unavailable_reason"]
            or "有效收盘观测不足 3 个（至少 2 个观测收益），休市沿用不增加观测数"
        )
    elif not np.isfinite(values).all() or np.any(values <= 0):
        basis["unavailable_reason"] = "净值非有限或不为正，无法计算可比的复利与风险指标"
    if len(values) - 1 < basis["annual_periods"]:
        basis["warnings"].append("不足一年采样期；年化值仅为观察期外推，不代表已取得全年收益")
    return values, basis
