"""组合管理数据结构。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class PortfolioState:
    """组合状态快照。"""

    date: int
    weights: dict[str, float]
    holdings: dict[str, float]
    cash: float
    total_value: float
    positions_count: int


@dataclass
class RebalanceResult:
    """再平衡结果。"""

    rebalance_dates: list[int]
    states: list[PortfolioState]
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    performance: dict[str, float]
