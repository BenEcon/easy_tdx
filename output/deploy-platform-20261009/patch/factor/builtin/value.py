"""价值类因子（需要财务数据扩展，当前为占位实现）。"""

from __future__ import annotations

import pandas as pd

from easy_tdx.factor.base import Factor, register_factor


@register_factor
class PERatio(Factor):
    name = "pe_ratio"
    category = "value"
    description = "市盈率（需要财务数据扩展，当前不可用）"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(float("nan"), index=df.index)


@register_factor
class PBRatio(Factor):
    name = "pb_ratio"
    category = "value"
    description = "市净率（需要财务数据扩展，当前不可用）"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(float("nan"), index=df.index)
