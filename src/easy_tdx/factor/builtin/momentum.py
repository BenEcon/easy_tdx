"""动量类因子。"""

from __future__ import annotations

import pandas as pd

from easy_tdx.factor.base import Factor, register_factor


@register_factor
class Momentum20D(Factor):
    name = "momentum_20d"
    category = "momentum"
    description = "20 日动量（20 日收益率）"
    inputs = ("close",)
    window = 20

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change(self.window, fill_method=None)


@register_factor
class Momentum60D(Factor):
    name = "momentum_60d"
    category = "momentum"
    description = "60 日动量（60 日收益率）"
    inputs = ("close",)
    window = 60

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change(self.window, fill_method=None)


@register_factor
class Reversal5D(Factor):
    name = "reversal_5d"
    category = "momentum"
    description = "5 日反转因子（负 5 日收益率）"
    inputs = ("close",)
    window = 5

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return -df["close"].pct_change(self.window, fill_method=None)
