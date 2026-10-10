"""内置因子库 — 导入子模块触发注册。"""

from __future__ import annotations

from easy_tdx.factor.base import FACTORY_REGISTRY, Factor

# 导入所有子模块以触发 @register_factor 装饰器
from easy_tdx.factor.builtin import (  # noqa: F401
    chanlun,
    momentum,
    quality,
    technical,
    value,
    volatility,
    volume,
)


def list_factors() -> list[dict[str, str | tuple[str, ...]]]:
    """返回所有已注册因子的元数据。"""
    return [
        {
            "name": cls.name,
            "category": cls.category,
            "description": cls.description,
            "inputs": cls.inputs,
        }
        for cls in FACTORY_REGISTRY.values()
    ]


def get_factor(name: str) -> type[Factor]:
    """按名称获取因子类。

    Raises:
        ValueError: 因子不存在。
    """
    if name not in FACTORY_REGISTRY:
        raise ValueError(f"未知因子: {name!r}。可用因子: {sorted(FACTORY_REGISTRY.keys())}")
    return FACTORY_REGISTRY[name]
