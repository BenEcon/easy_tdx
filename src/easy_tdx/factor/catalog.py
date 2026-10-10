"""Auditable definitions for the existing registry, not a second factor engine."""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any

from easy_tdx.factor.base import Factor

CATALOG_VERSION = "easy-tdx-factor-catalog-v1"
ALIASES = {
    "turnover_rate": "amount_relative_20",
    **{
        f"alpha101_{a:03d}": f"gtja191_{g:03d}"
        for a, g in (
            (3, 105),
            (11, 7),
            (13, 99),
            (14, 136),
            (15, 32),
            (16, 83),
            (20, 107),
            (22, 104),
            (35, 117),
            (37, 184),
            (40, 42),
            (41, 13),
            (42, 120),
            (44, 62),
            (45, 113),
            (46, 86),
            (50, 16),
        )
    },
}
BAR_PERIODS = ["DAY", "WEEK", "MONTH", "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60"]

# Minimum input rows, not a claim of numerical convergence for seeded EWMs.
# Defaults retain old IDs; the separate schema resolves per-request parameters.
_DEFINITIONS: dict[str, tuple[str, str, int | None, dict[str, int | float]]] = {
    "momentum_20d": ("二十周期动量", "close / close.shift(20) - 1", 21, {"window": 20}),
    "momentum_60d": ("六十周期动量", "close / close.shift(60) - 1", 61, {"window": 60}),
    "reversal_5d": ("五周期反转", "-(close / close.shift(5) - 1)", 6, {"window": 5}),
    "volatility_20d": ("二十周期波动率", "std(close.pct_change(), 20, ddof=1)", 21, {"window": 20}),
    "atr_14d": (
        "十四周期平均真实波幅",
        "mean(max(high-low, abs(high-prev_close), abs(low-prev_close)), 14)",
        15,
        {"window": 14},
    ),
    "amount_relative_20": ("成交额相对均值", "amount / mean(amount, 20)", 20, {"window": 20}),
    "sharpe_20d": (
        "二十周期收益波动比",
        "mean(return, 20) / std(return, 20, ddof=1)",
        21,
        {"window": 20},
    ),
    "max_drawdown_20d": (
        "二十周期最大回撤",
        "min(close / cummax(close) - 1) within trailing 20 bars",
        20,
        {"window": 20},
    ),
    "win_rate_20d": ("二十周期上涨占比", "mean(return > 0, 20)", 21, {"window": 20}),
    "obv_trend": (
        "能量潮趋势",
        "OLS slope(cumsum(sign(close.diff()) * vol), 20)",
        20,
        {"window": 20},
    ),
    "vol_surge": ("成交量相对均值", "vol / mean(vol, 20)", 20, {"window": 20}),
    "amount_ma_ratio": (
        "成交额均线比",
        "mean(amount, 5) / mean(amount, 20)",
        20,
        {"short": 5, "long": 20},
    ),
    "macd_hist_signal": (
        "MACD 柱相对强度",
        "MyTT.MACD(close,12,26,9).hist / mean(abs(hist),20)",
        20,
        {"short": 12, "long": 26, "signal": 9, "scale_window": 20},
    ),
    "rsi_14": ("十四周期相对强弱", "(MyTT.RSI(close,14) - 50) / 50", 2, {"window": 14}),
    "boll_position": (
        "布林带相对位置",
        "clip((close-lower)/(upper-lower),0,1); MyTT.BOLL(close,20,2)",
        20,
        {"window": 20, "std_multiplier": 2},
    ),
    "chanlun_bi_dir": (
        "最近确认笔方向",
        "在 confirmed_index 更新笔方向，沿用现有 ChanlunAnalyser",
        None,
        {},
    ),
    "chanlun_mmd": (
        "确认时刻结构买卖点",
        "在 confirmed_index 标记买卖点；重合时优先绝对值大的类别",
        None,
        {},
    ),
    "pe_ratio": ("市盈率", "价格 / 当时可得的每股收益；历史数据适配器未实现", None, {}),
    "pb_ratio": ("市净率", "价格 / 当时可得的每股净资产；历史数据适配器未实现", None, {}),
}


def canonical_factor_name(name: str) -> str:
    return ALIASES.get(name, name)


def builtin_defaults(name: str) -> dict[str, int | float] | None:
    from easy_tdx.factor.builtin_parameters import TEMPLATES

    canonical = canonical_factor_name(name)
    return dict(_DEFINITIONS[canonical][3]) if canonical in TEMPLATES else None


def availability_reason(
    definition: dict[str, Any], adjust: str, *, evaluation: bool = False
) -> str:
    """Resolve catalog capability against the actual requested adjustment."""
    key = "evaluation_available" if evaluation else "available"
    if not definition[key]:
        return str(
            definition["evaluation_unavailable_reason" if evaluation else "unavailable_reason"]
        )
    if adjust not in definition.get("supported_adjustments", ["NONE", "QFQ", "HFQ"]):
        return str(definition.get("adjustment_unavailable_reason") or "因子不支持当前复权方式")
    return ""


def describe_factor(cls: type[Factor], parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Preserve registry/CLI fields and add explicit readiness and definition identity."""
    name = cls.name
    from easy_tdx.factor.base import PanelFactor
    from easy_tdx.factor.configuration import configure_factor

    panel_factor = issubclass(cls, PanelFactor)
    compute = cls.compute_panel if issubclass(cls, PanelFactor) else cls.compute

    instance = configure_factor(name, parameters) if parameters else None
    canonical = canonical_factor_name(name)
    known = canonical in _DEFINITIONS
    title, formula, warmup, parameters = _DEFINITIONS.get(
        canonical, (cls.description, "自定义因子：尚未登记公式说明", None, {})
    )
    value = cls.category == "value"
    structural = cls.category == "chanlun"
    reason = "需要按公告可得时间对齐的历史财务数据，且计算适配器尚未实现" if value else ""
    evaluation_reason = reason or (
        "缠论因子尚未完成逐时点因果验收，不参与截面检验" if structural else ""
    )
    limitations = [
        "周期参数按所选 K 线根数解释；不是自动换算成交易日。",
        "数值方向不自动代表买卖建议，也不自动反转负相关因子。",
    ]
    if canonical == "amount_relative_20":
        limitations.append("这是成交额相对均值，不是真正换手率；旧 turnover_rate 仅为兼容别名。")
    if canonical in {"volatility_20d", "sharpe_20d"}:
        limitations.append("不年化；收益波动比未减无风险利率，不等同于策略夏普比率。")
    if canonical in {"macd_hist_signal", "rsi_14"}:
        limitations.append("沿用 MyTT 指数平滑初值与舍入；最少根数不等于收敛，建议至少 120 根。")
    if canonical == "obv_trend":
        limitations.append(
            "完整窗口要求收盘价为有限正数、成交量为有限非负数；缺失或无效值不当作持平，"
            "窗口移出无效数据后恢复。窗口首根 OBV 设为 0，仅去掉不影响斜率的常数；"
            "不依赖更早历史的累计量。平价或零成交量的贡献为 0，斜率单位为成交量单位／K 线。"
        )
    if structural:
        limitations.append(
            "沿用现有 DAILY 识别入口，仅支持日线；没有固定预热根数，0 表示尚无确认结构/信号。"
        )
    if not known:
        limitations.append("自定义因子元数据及独立验收未完备；不计入内置因子验收数。")
    try:
        implementation = inspect.getsource(compute)
    except (OSError, TypeError):
        implementation = f"unavailable:{cls.__module__}.{cls.__qualname__}"
    definition = {
        "canonical_name": canonical,
        "formula": formula,
        "parameters": parameters,
        "inputs": list(cls.inputs),
        "implementation": implementation,
    }
    digest = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
    result: dict[str, Any] = {
        "name": name,
        "category": cls.category,
        "description": cls.description,
        "inputs": list(cls.inputs),
        "display_name": title,
        "canonical_name": canonical,
        "alias_of": canonical if name != canonical else None,
        "library": "easy_tdx_builtin" if known else "custom",
        "formula": formula,
        "formula_sha256": digest,
        "implementation_version": "legacy-v1" if not value else "not-implemented",
        "source": f"{compute.__module__}.{compute.__qualname__}",
        "catalog_version": CATALOG_VERSION,
        "resolved_parameters": dict(parameters),
        "warmup_bars": warmup,
        "warmup_note": "达到最少根数后，常数、零分母或缺失仍可能无有效值。",
        "parameters": {
            key: {
                "default": val,
                "editable": False,
                "unit": "bars" if key != "std_multiplier" else "multiple",
            }
            for key, val in parameters.items()
        },
        "supported_categories": ["DAY"] if structural or value else list(BAR_PERIODS),
        "scope": "single_series",
        "data_requirements": [
            *cls.inputs,
            *(["financials_point_in_time", "available_at"] if value else []),
        ],
        "status": "needs_data_and_implementation" if value else "available",
        "implemented": not value,
        "available": not value,
        "evaluation_available": not value and not structural,
        "unavailable_reason": reason,
        "evaluation_unavailable_reason": evaluation_reason,
        "limitations": limitations,
    }
    defaults = builtin_defaults(name)
    if defaults is not None:
        from easy_tdx.factor.builtin_parameters import metadata

        result.update(metadata(canonical, defaults, instance or cls()))
        result["parameter_family"] = (
            "momentum" if canonical in {"momentum_20d", "momentum_60d"} else canonical
        )
        result["formula_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    "canonical_name": canonical,
                    "formula": result["formula"],
                    "parameters": result["resolved_parameters"],
                    "implementation": implementation,
                    "version": result["implementation_version"],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        limitations.append(
            "可编辑参数按当前 K 线根数解释；不改变默认数值方向。"
            "收益率不填充缺失价格，回撤要求完整有效窗口。"
        )
    from easy_tdx.factor.builtin.alpha158 import (
        Alpha158Factor,
        compute_alpha158,
        definition_metadata,
    )

    if issubclass(cls, Alpha158Factor):
        result.update(
            definition_metadata(cls, instance if isinstance(instance, Alpha158Factor) else None)
        )
        module = inspect.getmodule(compute_alpha158)
        try:
            source_text = inspect.getsource(module) if module is not None else ""
        except (OSError, TypeError):
            source_text = ""
        result["implementation_source_available"] = bool(source_text)
        result["formula_sha256"] = hashlib.sha256(
            (json.dumps(result, sort_keys=True) + source_text).encode()
        ).hexdigest()
    from easy_tdx.factor.builtin import alpha101, gtja191
    from easy_tdx.factor.builtin.alpha101 import Alpha101Factor
    from easy_tdx.factor.builtin.gtja191 import GTJAFactor

    if issubclass(cls, Alpha101Factor):
        result.update(
            alpha101.definition_metadata(
                cls, instance if isinstance(instance, Alpha101Factor) else None
            )
        )
        result["implementation_source_available"] = True
        source = inspect.getsource(alpha101)
        if cls.spec.windows:
            from easy_tdx.factor.builtin import alpha101_compound

            source += inspect.getsource(alpha101_compound)
        if cls.spec.reference is not None or cls.spec.number in {33, 38}:
            source += inspect.getsource(gtja191)
        result["formula_sha256"] = hashlib.sha256(
            (json.dumps(result, sort_keys=True) + source).encode()
        ).hexdigest()
        limitations = result["limitations"]

    if issubclass(cls, GTJAFactor):
        result.update(
            gtja191.definition_metadata(cls, instance if isinstance(instance, GTJAFactor) else None)
        )
        result["implementation_source_available"] = True
        source = inspect.getsource(gtja191)
        if cls.spec.number == 30:
            from easy_tdx.factor import risk_inputs
            from easy_tdx.factor.builtin import risk_residuals

            source += inspect.getsource(risk_residuals) + inspect.getsource(risk_inputs)
        result["formula_sha256"] = hashlib.sha256(
            (json.dumps(result, sort_keys=True) + source).encode()
        ).hexdigest()
        limitations = result["limitations"]
    if panel_factor:
        from easy_tdx.factor import panel

        result.update(
            {
                "scope": "cross_section_panel",
                "available": False,
                "unavailable_reason": "需要明确股票池；请使用截面检验，不能独立单股计算",
                "panel_version": panel.PANEL_VERSION,
            }
        )
        limitations.append(
            "以所选股票池的观测时间并集对齐；缺失不填充，不代表历史成分或完整交易日历。"
            "截面排名采用当时有有效输入的标的，必须结合覆盖率阅读。"
        )
        result["data_requirements"] = [*result["data_requirements"], "explicit_universe"]
        result["formula_sha256"] = hashlib.sha256(
            (result["formula_sha256"] + inspect.getsource(panel)).encode()
        ).hexdigest()
    return result
