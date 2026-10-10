"""Per-request factor instances; never mutate registered defaults or user config."""

from __future__ import annotations

from typing import Any

from easy_tdx.factor.base import FACTORY_REGISTRY, Factor


def configure_factor(name: str, parameters: dict[str, Any] | None = None) -> Factor:
    from easy_tdx.factor.builtin.alpha101 import Alpha101Factor
    from easy_tdx.factor.builtin.alpha158 import Alpha158Factor
    from easy_tdx.factor.builtin.gtja191 import GTJAFactor

    cls = FACTORY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"未知因子：{name}")
    parameters = {} if parameters is None else parameters
    if not isinstance(parameters, dict):
        raise ValueError("因子参数必须是字典")
    if not parameters:
        return cls()
    if issubclass(cls, Alpha101Factor):
        return cls(**parameters)
    if issubclass(cls, GTJAFactor):
        if cls.spec.windows:
            if any(type(value) is not int for value in parameters.values()):
                raise ValueError(f"{name} 仅支持声明的整数参数")
            return cls(**parameters)
        if set(parameters) != {"window"} or type(parameters["window"]) is not int:
            raise ValueError(f"{name} 仅支持声明的整数 window 参数")
        return cls(window=parameters["window"])
    if issubclass(cls, Alpha158Factor) and cls.spec.window is not None:
        if set(parameters) != {"window"} or type(parameters["window"]) is not int:
            raise ValueError(f"{name} 仅支持整数 window 参数，不接受未声明的参数")
        return cls(window=parameters["window"])
    from easy_tdx.factor.builtin_parameters import resolve
    from easy_tdx.factor.catalog import builtin_defaults

    defaults = builtin_defaults(name)
    if defaults is not None:
        instance = cls()
        for key, value in resolve(defaults, parameters).items():
            setattr(instance, key, value)
        return instance
    raise ValueError(f"{name} 目前没有可编辑参数；未忽略传入配置")


def configured_selection(
    names: list[str], parameters: dict[str, dict[str, Any]] | None = None
) -> list[Factor]:
    from easy_tdx.factor.builtin.alpha101 import Alpha101Factor, definition_metadata
    from easy_tdx.factor.builtin.alpha158 import Alpha158Factor
    from easy_tdx.factor.builtin.gtja191 import GTJAFactor
    from easy_tdx.factor.catalog import builtin_defaults, canonical_factor_name

    parameters = parameters or {}
    if set(parameters) - set(names):
        raise ValueError("参数含未选中的因子；未静默忽略")
    factors = [configure_factor(name, parameters.get(name)) for name in names]
    identities: list[tuple[Any, ...]] = []
    for factor in factors:
        canonical = canonical_factor_name(factor.name)
        defaults = builtin_defaults(factor.name)
        if isinstance(factor, Alpha101Factor):
            metadata = definition_metadata(type(factor), factor)
            mapping = metadata.get("parameter_aliases", {})
            resolved = {mapping.get(k, k): v for k, v in metadata["resolved_parameters"].items()}
            identities.append((metadata["parameter_family"], tuple(sorted(resolved.items()))))
        elif isinstance(factor, GTJAFactor):
            family = (
                "price_mean_ratio"
                if factor.spec.family == "mean_ratio"
                else f"gtja191:{factor.spec.family}"
            )
            identities.append((family, tuple(sorted(factor.spec.resolved_parameters.items()))))
        elif isinstance(factor, Alpha158Factor) and factor.spec.family == "MA":
            identities.append(("price_mean_ratio", (("window", factor.spec.window),)))
        elif isinstance(factor, Alpha158Factor):
            identities.append(("alpha158", factor.spec.family, factor.spec.window))
        elif defaults is not None:
            family = "momentum" if canonical in {"momentum_20d", "momentum_60d"} else canonical
            identities.append(
                (family, tuple((key, getattr(factor, key)) for key in sorted(defaults)))
            )
        else:
            identities.append((canonical,))
    if len(set(identities)) != len(identities):
        raise ValueError("存在实际参数相同的重复因子；不同默认标识不能重复同一公式")
    return factors
