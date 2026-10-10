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

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        vol = df["vol"]
        direction = np.sign(close.diff()).fillna(0).values
        obv = pd.Series((direction * vol).cumsum(), index=df.index)

        result = pd.Series(np.nan, index=df.index, dtype=np.float64)
        window = 20
        x = np.arange(window, dtype=np.float64)
        x_mean = x.mean()
        x_ss = np.sum((x - x_mean) ** 2)

        for i in range(window - 1, len(obv)):
            y = obv.iloc[i - window + 1 : i + 1].values.astype(np.float64)
            y_mean = y.mean()
            slope = np.sum((x - x_mean) * (y - y_mean)) / x_ss
            result.iloc[i] = slope

        return result


@register_factor
class VolSurge(Factor):
    name = "vol_surge"
    category = "volume"
    description = "量比（当日成交量 / 20 日平均成交量）"
    inputs = ("vol",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        vol = df["vol"]
        ma20 = vol.rolling(20).mean()
        return vol / ma20.replace(0, np.nan)


@register_factor
class AmountMARatio(Factor):
    name = "amount_ma_ratio"
    category = "volume"
    description = "成交额 MA5 / MA20 比值"
    inputs = ("amount",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        amt = df["amount"]
        ma5 = amt.rolling(5).mean()
        ma20 = amt.rolling(20).mean()
        return ma5 / ma20.replace(0, np.nan)
