# src/easy_tdx/factor/base.py
"""因子基类与全局注册表。"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Factor(ABC):
    """因子基类 — 所有因子的抽象契约。

    子类必须定义:
        name: str        — 唯一标识，如 "momentum_20d"
        category: str    — 分类：momentum / value / quality / volatility / technical / chanlun
        description: str — 人类可读描述
        inputs: tuple[str, ...] — 需要的列名，如 ("close", "vol")

    并实现 compute(df) -> pd.Series。
    """

    name: str
    category: str
    description: str
    inputs: tuple[str, ...]

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """接收 OHLCV DataFrame，返回因子值序列（与 df 等长）。"""
        ...

    def __init__(self) -> None:
        for attr in ("name", "category", "description", "inputs"):
            if not hasattr(self, attr):
                raise TypeError(f"Factor 子类 {type(self).__name__} 必须定义类属性 '{attr}'")


FACTORY_REGISTRY: dict[str, type[Factor]] = {}


def register_factor(cls: type[Factor]) -> type[Factor]:
    """类装饰器，将 Factor 子类注册到全局表。

    Raises:
        ValueError: 如果 name 已被注册。
    """
    if cls.name in FACTORY_REGISTRY:
        raise ValueError(f"因子 '{cls.name}' 已注册（类: {FACTORY_REGISTRY[cls.name].__name__}）")
    FACTORY_REGISTRY[cls.name] = cls
    return cls
