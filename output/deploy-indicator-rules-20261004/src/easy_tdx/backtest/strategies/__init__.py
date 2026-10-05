"""内置策略包：注册表 + 预置策略。

导入本包即触发所有内置策略的注册。调用方通过 :func:`get_registry` 发现策略::

    from easy_tdx.backtest.strategies import get_registry

    for entry in get_registry().all():
        print(entry.name, entry.label, [p.to_schema() for p in entry.params])
"""

from easy_tdx.backtest.strategies.registry import (  # noqa: F401
    Param,
    ParametrizedStrategy,
    RegisteredStrategy,
    StrategyRegistry,
    get_registry,
    register_strategy,
    resolve,
)

__all__ = [
    "Param",
    "ParametrizedStrategy",
    "RegisteredStrategy",
    "StrategyRegistry",
    "get_registry",
    "register_strategy",
    "resolve",
]


def _load_builtin() -> None:
    """导入内置策略模块以触发注册（惰性，避免循环导入）。"""
    from easy_tdx.backtest.strategies import builtin  # noqa: F401

    # 触发 REF 符号的导入校验（builtin 顶部已导入，这里仅保留语义占位）
    del builtin


# 模块导入时即加载内置策略，确保 get_registry() 调用前策略已注册
_load_builtin()
