# src/easy_tdx/factor/engine.py
"""因子计算引擎 — 单股计算与截面批量计算。"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from easy_tdx.computation import computation_checkpoint
from easy_tdx.factor.base import FACTORY_REGISTRY, Factor, PanelFactor
from easy_tdx.factor.panel import FactorPanel, observation_index


def _resolve_factor(f: str | Factor) -> Factor:
    """将因子名或实例解析为 Factor 实例。"""
    if isinstance(f, Factor):
        return f
    name = f.strip()
    if name not in FACTORY_REGISTRY:
        raise ValueError(f"未知因子: {name!r}。可用因子: {sorted(FACTORY_REGISTRY.keys())}")
    return FACTORY_REGISTRY[name]()


def _datetime_to_int(dt_val: object) -> int:
    """将 datetime 值转为 YYYYMMDD 整数。"""
    if hasattr(dt_val, "strftime"):
        strftime = getattr(dt_val, "strftime")
        return int(strftime("%Y%m%d"))
    if isinstance(dt_val, int | float):
        return int(dt_val)
    return 0


_ALL_DATES: object = object()


class FactorEngine:
    """批量因子计算引擎。"""

    def compute_matrix(
        self,
        data: dict[str, pd.DataFrame],
        factor: str | Factor,
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> pd.DataFrame:
        """Shared research executor for ordinary and whole-universe factors."""
        resolved = _resolve_factor(factor)
        if isinstance(resolved, PanelFactor) and len(data) < 2:
            raise ValueError("整池截面因子至少需要 2 个明确标的，不能使用单股替代")
        panel = FactorPanel.build(data, resolved.inputs)
        computation_checkpoint()
        if isinstance(resolved, PanelFactor):
            # Keep independent validation axes even if custom code mutates its
            # input panel. Neither caller-owned prices nor result axes may move.
            working = FactorPanel(
                {key: frame.copy(deep=True) for key, frame in panel.fields.items()},
                panel.observed.copy(deep=True),
            )
            result = resolved.compute_panel(working)
            computation_checkpoint()
        else:
            parts = {}
            for position, (symbol, frame) in enumerate(data.items(), 1):
                computation_checkpoint()
                values = resolved.compute(frame.copy(deep=True))
                if not isinstance(values, pd.Series) or not values.index.equals(frame.index):
                    raise ValueError(f"{resolved.name} 输出索引与 {symbol} 输入不一致")
                parts[symbol] = pd.Series(values.to_numpy(), index=observation_index(frame))
                if progress:
                    progress(position, len(data))
            result = pd.concat(parts, axis=1).reindex(panel.observed.index)
        result = panel.validate_result(result, resolved.name)
        if isinstance(resolved, PanelFactor) and progress:
            progress(len(data), len(data))
        computation_checkpoint()
        return result

    def compute_single(
        self,
        df: pd.DataFrame,
        factors: list[str | Factor],
    ) -> pd.DataFrame:
        """单股票多因子计算。"""
        if not factors:
            return df.copy()

        result = df.copy()
        for f in factors:
            factor = _resolve_factor(f)
            missing = set(factor.inputs) - set(df.columns)
            if missing:
                raise ValueError(f"{factor.name} 缺少字段：{', '.join(sorted(missing))}")
            values = factor.compute(df)
            if not isinstance(values, pd.Series) or not values.index.equals(df.index):
                raise ValueError(f"{factor.name} 输出索引与输入不一致，不能静默对齐或截断")
            result[factor.name] = values

        return result

    def compute_cross_section(
        self,
        data: dict[str, pd.DataFrame],
        factors: list[str | Factor],
        date: int | None = _ALL_DATES,  # type: ignore[assignment]
    ) -> pd.DataFrame:
        """多股票截面因子计算。

        Args:
            date: int 精确匹配日期；None 仅最新一行；默认(不传)全部日期。
        """
        if not data:
            return pd.DataFrame()

        if any(isinstance(_resolve_factor(f), PanelFactor) for f in factors):
            return self._compute_panel_cross_section(data, factors, date)

        filter_latest = date is None
        all_frames: list[pd.DataFrame] = []

        for code, df in data.items():
            if df.empty:
                continue

            computed = self.compute_single(df, factors)
            computed["_date_int"] = computed["datetime"].apply(_datetime_to_int)

            if date is not None and date is not _ALL_DATES:
                computed = computed[computed["_date_int"] == date]
            elif filter_latest:
                computed = computed.iloc[[-1]]

            factor_names = [_resolve_factor(f).name for f in factors]
            keep_cols = ["_date_int"] + factor_names
            sub = computed[keep_cols].copy()
            sub["_code"] = code
            all_frames.append(sub)

        if not all_frames:
            return pd.DataFrame()

        combined = pd.concat(all_frames, ignore_index=True)
        combined = combined.rename(columns={"_date_int": "date", "_code": "code"})

        col_order = ["date", "code"] + [_resolve_factor(f).name for f in factors]
        combined = combined[col_order].sort_values(["date", "code"]).reset_index(drop=True)

        return combined

    def _compute_panel_cross_section(
        self, data: dict[str, pd.DataFrame], factors: list[str | Factor], date: object
    ) -> pd.DataFrame:
        """Preserve the long result API; include exact timestamp for minute bars.

        Latest means the SAME latest timestamp of the explicit universe, not a
        synthetic cross-section stitched from each stock's last available day.
        """
        results = {}
        for factor in factors:
            resolved = _resolve_factor(factor)
            if resolved.name in results:
                raise ValueError("整池计算含重复因子标识，不能静默覆盖结果")
            results[resolved.name] = self.compute_matrix(data, resolved)
        first = next(iter(results.values()))
        index = pd.MultiIndex.from_product([first.index, first.columns], names=["datetime", "code"])
        long = pd.DataFrame(
            {name: values.to_numpy().reshape(-1) for name, values in results.items()}, index=index
        ).reset_index()
        long.insert(0, "date", long["datetime"].apply(_datetime_to_int))
        if date is None:
            long = long[long["datetime"] == first.index[-1]]
        elif date is not _ALL_DATES:
            long = long[long["date"] == date]
        return long.sort_values(["datetime", "code"]).reset_index(drop=True)

    def compute_forward_returns(
        self,
        data: dict[str, pd.DataFrame],
        period: int = 5,
    ) -> pd.DataFrame:
        """计算远期收益率。"""
        if not data:
            return pd.DataFrame()

        col_name = f"forward_{period}d"
        all_frames: list[pd.DataFrame] = []

        for code, df in data.items():
            if df.empty or len(df) < period + 1:
                continue

            close = df["close"].to_numpy()
            forward = np.full(len(close), np.nan)
            forward[: len(close) - period] = close[period:] / close[: len(close) - period] - 1

            dates = df["datetime"].apply(_datetime_to_int)

            sub = pd.DataFrame(
                {
                    "date": dates,
                    "code": code,
                    col_name: forward,
                }
            )
            all_frames.append(sub)

        if not all_frames:
            return pd.DataFrame(columns=["date", "code", col_name])

        combined = pd.concat(all_frames, ignore_index=True)
        combined = combined.sort_values(["date", "code"]).reset_index(drop=True)
        return combined
