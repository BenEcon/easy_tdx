"""波动率类因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.factor.base import Factor, register_factor


@register_factor
class Volatility20D(Factor):
    name = "volatility_20d"
    category = "volatility"
    description = "20 日波动率（20 日收益率标准差）"
    inputs = ("close",)
    window = 20

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ret = df["close"].pct_change(fill_method=None)
        return ret.rolling(self.window).std()


@register_factor
class ATR14D(Factor):
    name = "atr_14d"
    category = "volatility"
    description = "14 日平均真实波幅（ATR）"
    inputs = ("high", "low", "close")
    window = 14

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if df.empty:
            return pd.Series(index=df.index, dtype=float)
        high = df["high"].to_numpy(dtype=np.float64)
        low = df["low"].to_numpy(dtype=np.float64)
        close = df["close"].to_numpy(dtype=np.float64)

        tr = np.empty(len(df), dtype=np.float64)
        tr[0] = np.nan
        tr[1:] = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            ),
        )

        return pd.Series(tr, index=df.index).rolling(self.window).mean()


@register_factor
class AmountRelative20(Factor):
    name = "amount_relative_20"
    category = "volatility"
    description = "成交额相对均值（当期成交额 / 20 周期均成交额；非换手率）"
    inputs = ("amount",)
    window = 20

    def compute(self, df: pd.DataFrame) -> pd.Series:
        amt = df["amount"]
        ma20 = amt.rolling(self.window).mean()
        return amt / ma20.replace(0, np.nan)


@register_factor
class TurnoverRate(AmountRelative20):
    """Keep old saved configurations numerically identical; never repurpose the ID."""

    name = "turnover_rate"
    description = "成交额相对均值（旧标识兼容，非换手率）"
