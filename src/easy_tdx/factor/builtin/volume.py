"""成交量类因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.factor.base import Factor, register_factor


@register_factor
class OBVTrend(Factor):
    name = "obv_trend"
    category = "volume"
    description = "OBV 的 20 日线性回归斜率"
    inputs = ("close", "vol")
    window = 20

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = pd.to_numeric(df["close"], errors="coerce").to_numpy(
            dtype=np.float64, na_value=np.nan
        )
        vol = pd.to_numeric(df["vol"], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
        valid = np.isfinite(close) & (close > 0) & np.isfinite(vol) & (vol >= 0)
        result = np.full(len(df), np.nan, dtype=np.float64)
        window = self.window
        if window < 2:
            raise ValueError("OBV 斜率窗口至少为 2 根")
        # OLS on a locally rebased OBV path is exactly a weighted average of
        # its w-1 increments: weight(j) = 6*j*(w-j)/(w*(w*w-1)). An arbitrary
        # cumulative offset cancels. Avoid retaining a huge historical cumsum
        # that can swallow later increments or overflow. Weights sum to one.
        j = np.arange(1, window, dtype=np.float64)
        weights = 6 * j * (window - j) / (window * (window * window - 1))
        direction = (close[1:] > close[:-1]).astype(float) - (close[1:] < close[:-1])
        for end in range(window - 1, len(df)):
            start = end - window + 1
            if valid[start : end + 1].all():
                result[end] = weights @ (direction[start:end] * vol[start + 1 : end + 1])
        return pd.Series(result, index=df.index)


@register_factor
class VolSurge(Factor):
    name = "vol_surge"
    category = "volume"
    description = "量比（当日成交量 / 20 日平均成交量）"
    inputs = ("vol",)
    window = 20

    def compute(self, df: pd.DataFrame) -> pd.Series:
        vol = df["vol"]
        ma20 = vol.rolling(self.window).mean()
        return vol / ma20.replace(0, np.nan)


@register_factor
class AmountMARatio(Factor):
    name = "amount_ma_ratio"
    category = "volume"
    description = "成交额 MA5 / MA20 比值"
    inputs = ("amount",)
    short = 5
    long = 20

    def compute(self, df: pd.DataFrame) -> pd.Series:
        amt = df["amount"]
        ma5 = amt.rolling(self.short).mean()
        ma20 = amt.rolling(self.long).mean()
        return ma5 / ma20.replace(0, np.nan)
