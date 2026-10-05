"""可插拔滑点模型。"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class SlippageModel(ABC):
    """滑点模型基类。

    所有滑点模型必须实现 compute() 方法，返回总滑点成本（金额）。
    """

    @abstractmethod
    def compute(
        self,
        price: float,
        size: float,
        volume: float,
        volatility: float,
        direction: str,
    ) -> float:
        """计算滑点成本。

        Args:
            price: 成交价格
            size: 订单数量（股）
            volume: 当日成交量（股），0 表示无数据
            volatility: 近期年化波动率，0 表示无数据
            direction: 交易方向 BUY / SELL

        Returns:
            总滑点成本（金额，非比率）
        """
        ...


class FixedSlippage(SlippageModel):
    """固定每股滑点（向后兼容）。"""

    def __init__(self, per_share: float = 0.01) -> None:
        self._per_share = per_share

    def compute(
        self,
        price: float,
        size: float,
        volume: float,
        volatility: float,
        direction: str,
    ) -> float:
        return size * self._per_share


class PercentSlippage(SlippageModel):
    """按成交金额百分比滑点。"""

    def __init__(self, rate: float = 0.001) -> None:
        self._rate = rate

    def compute(
        self,
        price: float,
        size: float,
        volume: float,
        volatility: float,
        direction: str,
    ) -> float:
        return price * size * self._rate


class SquareRootSlippage(SlippageModel):
    """方根市场冲击模型（Almgren-Chriss 简化版）。

    impact = σ × √(participation_rate) × price × size × impact_coeff

    当 volume=0 或 volatility=0 时退化为 PercentSlippage(rate=0.001)。
    """

    def __init__(self, impact_coeff: float = 0.1) -> None:
        self._impact_coeff = impact_coeff
        self._fallback = PercentSlippage(rate=0.001)

    def compute(
        self,
        price: float,
        size: float,
        volume: float,
        volatility: float,
        direction: str,
    ) -> float:
        if size <= 0:
            return 0.0
        if volume <= 0 or volatility <= 0:
            return self._fallback.compute(price, size, volume, volatility, direction)
        participation_rate = min(size / volume, 1.0)
        impact = volatility * np.sqrt(participation_rate) * price * size * self._impact_coeff
        return float(impact)


class VolumeSlippage(SlippageModel):
    """成交量比例滑点。

    cost = (base_bps / 10000) × (size / volume) × price × size

    当 volume=0 时退化为 PercentSlippage(rate=base_bps/10000)。
    """

    def __init__(self, base_bps: float = 10.0) -> None:
        self._base_bps = base_bps
        self._fallback = PercentSlippage(rate=base_bps / 10000.0)

    def compute(
        self,
        price: float,
        size: float,
        volume: float,
        volatility: float,
        direction: str,
    ) -> float:
        if size <= 0:
            return 0.0
        if volume <= 0:
            return self._fallback.compute(price, size, volume, volatility, direction)
        rate = self._base_bps / 10000.0
        participation = min(size / volume, 1.0)
        return rate * participation * price * size
