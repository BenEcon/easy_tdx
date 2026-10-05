"""内置策略注册表。

提供策略的发现、参数自描述和实例化机制，供 Web API 表单动态渲染、
CLI 枚举和回测路由使用。

设计要点：
- 每个策略通过类属性 ``params`` 声明参数 schema（list[Param]）。
- ``@register_strategy`` 装饰器读取 ``params`` 与元信息登记到全局 registry。
- 策略类继承 :class:`ParametrizedStrategy`，``__init__`` 接受 kwargs 并
  做类型/范围校验，校验通过后存入 ``self.params`` 供 ``init()`` 使用。
- 不修改基类 :class:`~easy_tdx.backtest.strategy.Strategy` 的无参 ``__init__``
  契约——``ParametrizedStrategy`` 是单独的 mixin 子类。

示例::

    from easy_tdx.MyTT import MA, crossover
    from easy_tdx.backtest.strategies import ParametrizedStrategy, Param, register_strategy

    @register_strategy(name="ma_cross", label="双均线交叉", description="...")
    class MaCrossStrategy(ParametrizedStrategy):
        params = [
            Param("fast", int, default=5, min_value=1, max_value=60, label="快线周期"),
            Param("slow", int, default=20, min_value=5, max_value=250, label="慢线周期"),
        ]

        def init(self) -> None:
            self.ma_fast = self.I(MA, self.data.close, self.p["fast"])
            self.ma_slow = self.I(MA, self.data.close, self.p["slow"])
            self.cross = crossover(self.ma_fast, self.ma_slow)

        def next(self) -> None:
            if self.cross[self._bar_index]:
                self.buy()
            elif self.position["size"] > 0:
                self.sell()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from easy_tdx.backtest.strategy import Strategy

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "Param",
    "ParametrizedStrategy",
    "RegisteredStrategy",
    "StrategyRegistry",
    "get_registry",
    "register_strategy",
    "resolve",
]

# ── 参数 schema ───────────────────────────────────────────────────────────────


ParamType = Literal["int", "float", "bool", "str"]


def _type_name(tp: type) -> ParamType:
    """把 Python 类型映射到 schema 类型字符串。"""
    if tp is int:
        return "int"
    if tp is float:
        return "float"
    if tp is bool:
        return "bool"
    return "str"


@dataclass(frozen=True)
class Param:
    """单个策略参数的 schema 描述。

    Attributes:
        name: 参数名（与 ``__init__`` 关键字一致，存入 ``self.params`` 的键）。
        type: 参数类型（int/float/bool/str）。
        default: 默认值。
        min_value: 数值型下限（含），None 表示不限。
        max_value: 数值型上限（含），None 表示不限。
        choices: 字符串型可选值；非空时限制取值集合。
        label: 前端展示用的中文标签。
        description: 参数说明（可选）。
    """

    name: str
    type: type
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    choices: tuple[str, ...] | None = None
    label: str = ""
    description: str = ""

    def to_schema(self) -> dict[str, Any]:
        """序列化为 JSON 兼容的 schema 字典（供前端表单渲染）。"""
        schema: dict[str, Any] = {
            "name": self.name,
            "type": _type_name(self.type),
            "default": self.default,
            "label": self.label or self.name,
        }
        if self.min_value is not None:
            schema["min_value"] = self.min_value
        if self.max_value is not None:
            schema["max_value"] = self.max_value
        if self.choices:
            schema["choices"] = list(self.choices)
        if self.description:
            schema["description"] = self.description
        return schema

    def validate(self, value: Any, *, skip_bounds: bool = False) -> Any:
        """校验并强制转换取值，不合法抛 ValueError。

        NaN/Inf 的 float 输入会被拒绝（NaN 绕过所有比较，Inf 仅在有界时被拦，
        显式 isfinite 检查堵住两者）。int(inf)/int(nan) 会抛 OverflowError/
        ValueError，一并捕获。

        Returns:
            转换后的值（类型与 ``self.type`` 一致）。
        """
        import math

        try:
            if self.type is bool:
                # bool 必须先于 int 判断（bool 是 int 子类）
                if isinstance(value, bool):
                    converted: Any = value
                else:
                    converted = str(value).strip().lower() in {"1", "true", "yes", "on"}
            elif self.type is int:
                # 先拒绝 float 的 NaN/Inf（int(inf) 会抛 OverflowError 不在 ValueError 内）
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"参数 '{self.name}' 不接受 NaN/Inf")
                converted = int(value)
            elif self.type is float:
                converted = float(value)
                # float 的 NaN/Inf 必须显式拦：NaN 比较恒 False 会绕过边界检查
                if not math.isfinite(converted):
                    raise ValueError(f"参数 '{self.name}' 不接受 NaN/Inf")
            else:
                converted = str(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"参数 '{self.name}' 期望 {self.type.__name__}，得到 {value!r}"
            ) from exc

        # skip_bounds=True 时跳过范围/取值集合检查（供寻优器探索超范围值），
        # 仍保留类型转换 + NaN/Inf 拦截。跨参数语义约束在
        # ParametrizedStrategy.__init__ 里另行校验，同样不受 skip_bounds 影响。
        if not skip_bounds:
            if self.choices is not None and self.type is str and converted not in self.choices:
                raise ValueError(
                    f"参数 '{self.name}' 取值 {converted!r} 不在可选范围 {list(self.choices)} 内"
                )
            if (
                self.type in (int, float)
                and self.min_value is not None
                and converted < self.min_value
            ):
                raise ValueError(f"参数 '{self.name}'={converted} 小于下限 {self.min_value}")
            if (
                self.type in (int, float)
                and self.max_value is not None
                and converted > self.max_value
            ):
                raise ValueError(f"参数 '{self.name}'={converted} 大于上限 {self.max_value}")
        return converted


# ── 可参数化策略基类 ───────────────────────────────────────────────────────────


class ParametrizedStrategy(Strategy):
    """支持 kwargs 注入与校验的策略基类。

    子类声明类属性 ``params: ClassVar[list[Param]]``（参数 schema），
    ``__init__`` 接受同名关键字参数（缺省取 ``Param.default``），校验后存入
    实例属性 ``self.p`` 字典（已解析的参数值）。

    策略代码中用 ``self.p["fast"]`` 访问参数值；注册表用 ``cls.params``
    读取 schema。两者类型不同（list vs dict），通过 ClassVar 隔离。
    """

    # 类属性：参数 schema（子类覆盖）。ClassVar 表明这是类级配置而非实例字段。
    params: ClassVar[list[Param]] = []
    # 类属性：跨参数语义约束 (a, b) 列表，要求 a < b（如 ("fast", "slow")）。
    # 与单参数边界不同，这是语义级校验：skip_bounds（寻优探索超范围值）也不
    # 跳过——否则网格寻优会把"快线30慢线20"这类倒挂组合跑完还可能当选最优
    # （issue #39）。
    param_constraints: ClassVar[list[tuple[str, str]]] = []
    # 实例属性：已校验的参数值字典（init/next 中通过 self.p[name] 访问）。
    p: dict[str, Any]

    def __init__(self, *, skip_bounds: bool = False, **kwargs: Any) -> None:
        """从 kwargs 构造策略参数。

        多余的未知参数抛 ValueError；缺失参数取默认值。
        skip_bounds=True 时跳过单参数范围检查（供寻优器探索超范围值），
        但跨参数语义约束（``param_constraints``）仍然生效。
        """
        super().__init__()
        declared = {param.name: param for param in self.params}
        unknown = set(kwargs) - set(declared)
        if unknown:
            raise ValueError(f"策略 {type(self).__name__} 收到未知参数: {sorted(unknown)}")

        resolved: dict[str, Any] = {}
        for name, param in declared.items():
            raw = kwargs.get(name, param.default)
            resolved[name] = param.validate(raw, skip_bounds=skip_bounds)

        labels = {param.name: param.label or param.name for param in self.params}
        for smaller, larger in self.param_constraints:
            a, b = resolved[smaller], resolved[larger]
            if not a < b:
                raise ValueError(
                    f"参数 '{labels[smaller]}'({smaller})={a} 必须小于 "
                    f"'{labels[larger]}'({larger})={b}，周期/阈值倒挂在语义上无效"
                )

        self.p = resolved


# ── 注册表 ─────────────────────────────────────────────────────────────────────


@dataclass
class RegisteredStrategy:
    """注册表条目。"""

    name: str
    label: str
    description: str
    strategy_cls: type[ParametrizedStrategy]
    params: list[Param] = field(default_factory=list)

    def to_schema(self) -> dict[str, Any]:
        """序列化为 JSON 兼容的策略描述（供前端策略下拉框 + 参数表单）。"""
        # 延迟导入避免 presets ↔ registry 循环依赖
        from easy_tdx.backtest.strategies.presets import get_preset

        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "params": [p.to_schema() for p in self.params],
            "preset_grid": get_preset(self.name),
        }

    def build(
        self,
        params: dict[str, Any] | None = None,
        *,
        skip_bounds: bool = False,
    ) -> ParametrizedStrategy:
        """用给定参数构造策略实例，缺失参数取默认值。

        skip_bounds=True 时跳过单参数范围检查（供寻优器探索超范围值），
        跨参数语义约束（``param_constraints``）不受影响仍然生效。
        """
        return self.strategy_cls(**(params or {}), skip_bounds=skip_bounds)


class StrategyRegistry:
    """内置策略注册表（全局单例）。"""

    def __init__(self) -> None:
        self._strategies: dict[str, RegisteredStrategy] = {}

    def register(
        self,
        strategy_cls: type[ParametrizedStrategy],
        *,
        name: str,
        label: str = "",
        description: str = "",
    ) -> type[ParametrizedStrategy]:
        """登记一个策略类。重复 name 抛 ValueError。"""
        if name in self._strategies:
            raise ValueError(f"策略名 '{name}' 已注册")
        params = list(getattr(strategy_cls, "params", []))
        self._strategies[name] = RegisteredStrategy(
            name=name,
            label=label or name,
            description=description,
            strategy_cls=strategy_cls,
            params=params,
        )
        return strategy_cls

    def get(self, name: str) -> RegisteredStrategy:
        """按 name 取策略，不存在抛 KeyError。"""
        try:
            return self._strategies[name]
        except KeyError:
            raise KeyError(f"未知策略 '{name}'，可选: {sorted(self._strategies)}") from None

    def all(self) -> list[RegisteredStrategy]:
        """返回所有已注册策略（按注册顺序）。"""
        return list(self._strategies.values())

    def names(self) -> list[str]:
        """返回所有策略名。"""
        return sorted(self._strategies)


# ── 全局单例与便捷接口 ─────────────────────────────────────────────────────────

_REGISTRY = StrategyRegistry()


def get_registry() -> StrategyRegistry:
    """获取全局策略注册表单例。"""
    return _REGISTRY


def register_strategy(
    *,
    name: str,
    label: str = "",
    description: str = "",
) -> Callable[[type[ParametrizedStrategy]], type[ParametrizedStrategy]]:
    """类装饰器：把 ParametrizedStrategy 子类登记到全局注册表。"""

    def decorator(cls: type[ParametrizedStrategy]) -> type[ParametrizedStrategy]:
        _REGISTRY.register(cls, name=name, label=label, description=description)
        return cls

    return decorator


def resolve(name: str) -> RegisteredStrategy:
    """便捷函数：按 name 解析策略。"""
    return _REGISTRY.get(name)
