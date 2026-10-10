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
    short = 12
    long = 26
    signal = 9
    scale_window = 20

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"].to_numpy(dtype=np.float64)
        _, _, hist = MyTT.MACD(close, SHORT=self.short, LONG=self.long, M=self.signal)
        hist_series = pd.Series(hist, index=df.index)
        rolling_std = hist_series.abs().rolling(self.scale_window).mean().replace(0, np.nan)
        return hist_series / rolling_std


@register_factor
class RSI14(Factor):
    name = "rsi_14"
    category = "technical"
    description = "RSI(14) 归一化到 [-1, 1]（0 = 中性）"
    inputs = ("close",)
    window = 14

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"].to_numpy(dtype=np.float64)
        rsi = MyTT.RSI(close, N=self.window)
        return (pd.Series(rsi, index=df.index) - 50) / 50


@register_factor
class BollPosition(Factor):
    name = "boll_position"
    category = "technical"
    description = "价格在布林带中的相对位置（0=下轨，0.5=中轨，1=上轨）"
    inputs = ("close",)
    window = 20
    std_multiplier = 2.0

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"].to_numpy(dtype=np.float64)
        upper, mid, lower = MyTT.BOLL(close, N=self.window, P=self.std_multiplier)
        upper = pd.Series(upper, index=df.index)
        lower = pd.Series(lower, index=df.index)
        close_s = pd.Series(close, index=df.index)
        bandwidth = (upper - lower).replace(0, np.nan)
        position = (close_s - lower) / bandwidth
        return position.clip(0, 1)
