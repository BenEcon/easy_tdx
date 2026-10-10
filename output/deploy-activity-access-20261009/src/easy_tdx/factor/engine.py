# src/easy_tdx/factor/engine.py
"""因子计算引擎 — 单股计算与截面批量计算。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.factor.base import FACTORY_REGISTRY, Factor


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
            result[factor.name] = factor.compute(df)

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
