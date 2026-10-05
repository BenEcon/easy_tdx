"""质量类因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.factor.base import Factor, register_factor


@register_factor
class Sharpe20D(Factor):
    name = "sharpe_20d"
    category = "quality"
    description = "20 日夏普比率（收益率均值 / 收益率标准差）"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ret = df["close"].pct_change()
        rolling_mean = ret.rolling(20).mean()
        rolling_std = ret.rolling(20).std()
        return rolling_mean / rolling_std.replace(0, np.nan)


@register_factor
class MaxDrawdown20D(Factor):
    name = "max_drawdown_20d"
    category = "quality"
    description = "20 日滚动最大回撤（负值，0 = 无回撤）"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        result = pd.Series(np.nan, index=df.index, dtype=np.float64)

        for i in range(19, len(close)):
            window = close.iloc[i - 19 : i + 1]
            peak = window.cummax()
            dd = (window - peak) / peak
            result.iloc[i] = dd.min()

        return result


@register_factor
class WinRate20D(Factor):
    name = "win_rate_20d"
    category = "quality"
    description = "20 日内上涨天数占比（0-1）"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ret = df["close"].pct_change()
        up = (ret > 0).astype(float)
        return up.rolling(20).mean()
