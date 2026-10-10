"""Original, explicit panel contract; no external factor formulas are copied.

Rolling windows count rows of the union observation calendar. An absent stock
observation remains NaN, breaking a complete rolling window; never forward-fill
or roll across a different stock. This calendar is NOT a certified exchange
calendar or historical constituent database.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
import pandas as pd

from easy_tdx.computation import computation_checkpoint

PANEL_VERSION = "exact-observation-panel-v1"
MAX_PANEL_CELLS = 2_000_000


def observation_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if frame.columns.has_duplicates:
        raise ValueError("因子输入存在重复字段")
    key = "datetime" if "datetime" in frame else "date" if "date" in frame else None
    if key is not None:
        raw = frame[key]
        if pd.api.types.is_numeric_dtype(raw):
            # YYYYMMDD integers are dates, never nanoseconds after epoch.
            if raw.isna().any() or not raw.map(lambda x: int(x) == x).all():
                raise ValueError("数字日期必须为 YYYYMMDD 整数")
            dates = pd.to_datetime(raw.astype("int64").astype(str), format="%Y%m%d", errors="raise")
        else:
            dates = pd.to_datetime(raw, errors="raise")
        index = pd.DatetimeIndex(dates)
    elif isinstance(frame.index, pd.DatetimeIndex):
        index = frame.index.copy()
    else:
        raise ValueError("整池计算需要明确 datetime/date，不能用行号对齐")
    if index.tz is not None:
        index = index.tz_convert("Asia/Shanghai").tz_localize(None)
    if index.hasnans or index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("因子观测时间缺失、重复或未递增")
    return index


@dataclass(frozen=True)
class FactorPanel:
    fields: Mapping[str, pd.DataFrame]
    observed: pd.DataFrame

    @classmethod
    def build(cls, data: dict[str, pd.DataFrame], inputs: tuple[str, ...]) -> FactorPanel:
        if not data or any(not isinstance(s, str) or not s.strip() for s in data):
            raise ValueError("整池计算需要非空、明确的标的标识")
        if any(frame.empty for frame in data.values()):
            raise ValueError("股票池含无行情标的，未静默缩小股票池")
        if len(set(inputs)) != len(inputs):
            raise ValueError("因子声明重复输入字段")
        for key in ("actual_adjust", "category"):
            contracts = [
                frame.attrs.get("snapshot_metadata", {}).get(key) for frame in data.values()
            ]
            declared = [value for value in contracts if value is not None]
            if declared and (len(declared) != len(contracts) or len(set(declared)) != 1):
                raise ValueError(f"股票池 {key} 元数据缺失或不一致，不能混用复权或周期")
        indices = {}
        for symbol, frame in data.items():
            computation_checkpoint()
            if "vwap" in inputs and frame.attrs.get("snapshot_metadata", {}).get(
                "actual_adjust"
            ) not in (None, "NONE"):
                raise ValueError(f"{symbol} VWAP 当前仅支持不复权；未静默转换复权方式")
            indices[symbol] = observation_index(frame)
            missing = set(inputs) - set(frame.columns)
            if missing:
                raise ValueError(f"{symbol} 缺少字段：{', '.join(sorted(missing))}")
            for field in inputs:
                reason = frame.attrs.get("factor_input_errors", {}).get(field)
                if reason:
                    raise ValueError(f"{symbol} {reason}")
        dates = pd.DatetimeIndex(sorted(set().union(*(set(i) for i in indices.values()))))
        if len(dates) * len(data) * (len(inputs) + 1) > MAX_PANEL_CELLS:
            raise ValueError("整池因子计算超出 200 万输入单元上限；未截断标的或日期")
        observed = pd.DataFrame(False, index=dates, columns=list(data))
        for symbol, index in indices.items():
            observed.loc[index, symbol] = True
        fields = {}
        for field in inputs:
            computation_checkpoint()
            parts = {}
            for symbol, frame in data.items():
                numeric = pd.to_numeric(frame[field], errors="raise").to_numpy(
                    dtype=float, na_value=np.nan
                )
                parts[symbol] = pd.Series(numeric, index=indices[symbol])
            fields[field] = (
                pd.concat(parts, axis=1).reindex(dates).replace([np.inf, -np.inf], np.nan)
            )
        return cls(MappingProxyType(fields), observed)

    def validate_result(self, result: pd.DataFrame, name: str) -> pd.DataFrame:
        if (
            not isinstance(result, pd.DataFrame)
            or not result.index.equals(self.observed.index)
            or not result.columns.equals(self.observed.columns)
        ):
            raise ValueError(f"{name} 整池输出日期或标的轴不一致，不能静默重排、截断或扩充")
        return (
            result.apply(pd.to_numeric, errors="raise")
            .astype(float)
            .replace([np.inf, -np.inf], np.nan)
            .where(self.observed)
        )


def cross_section_rank(values: pd.DataFrame, *, min_count: int = 2) -> pd.DataFrame:
    """Average tied ordinal rank / finite count, within each timestamp; (0, 1].

    This is an explicit operator convention, not a claim that all published
    Alpha libraries have the same tie or singleton convention.
    """
    if type(min_count) is not int or min_count < 2:
        raise ValueError("截面排名至少需要 2 个有效标的")
    computation_checkpoint()
    finite = values.replace([np.inf, -np.inf], np.nan)
    result = finite.rank(axis=1, method="average", pct=True, na_option="keep")
    return result.where(finite.count(axis=1).ge(min_count), axis=0)


def delay(values: pd.DataFrame, bars: int = 1) -> pd.DataFrame:
    """Past observations only; a negative lag would leak future information."""
    if type(bars) is not int or bars < 0:
        raise ValueError("滞后窗口必须为非负整数，不能读取未来")
    computation_checkpoint()
    return values.shift(bars)


def rolling_mean(values: pd.DataFrame, bars: int) -> pd.DataFrame:
    """Complete union-calendar window per stock, without missing-value fill."""
    if type(bars) is not int or bars < 1:
        raise ValueError("滚动窗口必须为正整数")
    computation_checkpoint()
    return values.replace([np.inf, -np.inf], np.nan).rolling(bars, min_periods=bars).mean()
