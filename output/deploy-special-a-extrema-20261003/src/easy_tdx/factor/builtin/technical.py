"""技术指标因子 — 桥接 MyTT 指标库。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx import MyTT
from easy_tdx.factor.base import Factor, register_factor


@register_factor
class MACDHistSignal(Factor):
    name = "macd_hist_signal"
    category = "technical"
    description = "MACD 柱状线信号（正值=多头区域，负值=空头区域）"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"].to_numpy(dtype=np.float64)
        _, _, hist = MyTT.MACD(close, SHORT=12, LONG=26, M=9)
        hist_series = pd.Series(hist)
        rolling_std = hist_series.abs().rolling(20).mean().replace(0, np.nan)
        return (hist_series / rolling_std).fillna(0)


@register_factor
class RSI14(Factor):
    name = "rsi_14"
    category = "technical"
    description = "RSI(14) 归一化到 [-1, 1]（0 = 中性）"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"].to_numpy(dtype=np.float64)
        rsi = MyTT.RSI(close, N=14)
        return (pd.Series(rsi) - 50) / 50


@register_factor
class BollPosition(Factor):
    name = "boll_position"
    category = "technical"
    description = "价格在布林带中的相对位置（0=下轨，0.5=中轨，1=上轨）"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"].to_numpy(dtype=np.float64)
        upper, mid, lower = MyTT.BOLL(close, N=20, P=2)
        upper = pd.Series(upper)
        lower = pd.Series(lower)
        close_s = pd.Series(close)
        bandwidth = (upper - lower).replace(0, np.nan)
        position = (close_s - lower) / bandwidth
        return position.clip(0, 1)
