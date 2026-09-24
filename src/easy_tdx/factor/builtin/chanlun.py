"""缠论因子 — 桥接 ChanlunAnalyser。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.factor.base import Factor, register_factor


@register_factor
class ChanlunBiDir(Factor):
    name = "chanlun_bi_dir"
    category = "chanlun"
    description = "最近确认笔方向（+1=向上，-1=向下，0=未确认），不回填历史"
    inputs = ("open", "high", "low", "close", "vol", "amount")

    def compute(self, df: pd.DataFrame) -> pd.Series:
        result = pd.Series(0.0, index=df.index, dtype=np.float64)

        try:
            from easy_tdx.chanlun.analyser import ChanlunAnalyser

            analyser = ChanlunAnalyser(frequency="DAILY")
            chanlun_result = analyser.process_klines(df)
            bis = chanlun_result.bis

            if not bis:
                return result

            for bi in bis:
                direction = 1.0 if bi.direction == "up" else -1.0
                known = bi.confirmed_index
                if known is not None and 0 <= known < len(df):
                    result.iloc[known:] = direction

        except Exception:
            pass

        return result


@register_factor
class ChanlunMMD(Factor):
    name = "chanlun_mmd"
    category = "chanlun"
    description = "确认时刻的结构买卖点（正=买，负=卖，0=无）；重合点优先三类"
    inputs = ("open", "high", "low", "close", "vol", "amount")

    _MMD_MAP: dict[str, float] = {
        "1buy": 1.0,
        "2buy": 2.0,
        "3buy": 3.0,
        "l3buy": 3.0,
        "1sell": -1.0,
        "2sell": -2.0,
        "3sell": -3.0,
        "s3sell": -3.0,
    }

    def compute(self, df: pd.DataFrame) -> pd.Series:
        result = pd.Series(0.0, index=df.index, dtype=np.float64)

        try:
            from easy_tdx.chanlun.analyser import ChanlunAnalyser

            analyser = ChanlunAnalyser(frequency="DAILY")
            chanlun_result = analyser.process_klines(df)
            mmds = chanlun_result.mmds

            if not mmds:
                return result

            for mmd in mmds:
                mmd_type = mmd.mmd_type.value
                mmd_index = mmd.confirmed_index
                value = self._MMD_MAP.get(mmd_type, 0.0)
                if mmd_index is not None and 0 <= mmd_index < len(df):
                    if abs(value) > abs(result.iloc[mmd_index]):
                        result.iloc[mmd_index] = value

        except Exception:
            pass

        return result
