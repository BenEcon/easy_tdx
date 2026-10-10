# src/easy_tdx/factor/__init__.py
"""因子研究模块。"""

from __future__ import annotations

from easy_tdx.factor.analysis import FactorAnalyzer, FactorReport
from easy_tdx.factor.base import FACTORY_REGISTRY, Factor, register_factor

# 导入 builtin 触发自动注册
from easy_tdx.factor.builtin import get_factor, list_factors  # noqa: F401
from easy_tdx.factor.engine import FactorEngine
from easy_tdx.factor.transform import (
    fill_missing,
    orthogonalize,
    preprocess,
    rank_normalize,
    winsorize,
    zscore,
)

__all__ = [
    "Factor",
    "register_factor",
    "FACTORY_REGISTRY",
    "FactorEngine",
    "FactorAnalyzer",
    "FactorReport",
    "list_factors",
    "get_factor",
    "fill_missing",
    "orthogonalize",
    "preprocess",
    "rank_normalize",
    "winsorize",
    "zscore",
]
