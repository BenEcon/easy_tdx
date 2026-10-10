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

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ret = df["close"].pct_change()
        return ret.rolling(20).std()


@register_factor
class ATR14D(Factor):
    name = "atr_14d"
    category = "volatility"
    description = "14 日平均真实波幅（ATR）"
    inputs = ("high", "low", "close")

    def compute(self, df: pd.DataFrame) -> pd.Series:
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

        return pd.Series(tr, index=df.index).rolling(14).mean()


@register_factor
class TurnoverRate(Factor):
    name = "turnover_rate"
    category = "volatility"
    description = "换手率代理（当日成交额 / 20 日均成交额）"
    inputs = ("amount",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        amt = df["amount"]
        ma20 = amt.rolling(20).mean()
        return amt / ma20.replace(0, np.nan)
