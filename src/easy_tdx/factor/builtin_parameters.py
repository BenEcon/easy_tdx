"""Parameter schemas and actual formulas for existing builtins (no new IDs)."""

from __future__ import annotations

import math
from typing import Any

from easy_tdx.factor.base import Factor

# title, expression, minimum rows = selected parameter + offset (RSI is seeded)
TEMPLATES = {
    "momentum_20d": ("动量", "close / close.shift({window}) - 1", "window", 1),
    "momentum_60d": ("动量", "close / close.shift({window}) - 1", "window", 1),
    "reversal_5d": ("反转", "-(close / close.shift({window}) - 1)", "window", 1),
    "volatility_20d": (
        "波动率",
        "std(close.pct_change(fill_method=None), {window}, ddof=1)",
        "window",
        1,
    ),
    "atr_14d": (
        "平均真实波幅",
        "mean(max(high-low, abs(high-prev_close), abs(low-prev_close)), {window})",
        "window",
        1,
    ),
    "amount_relative_20": ("成交额相对均值", "amount / mean(amount, {window})", "window", 0),
    "sharpe_20d": (
        "收益波动比",
        "mean(return, {window}) / std(return, {window}, ddof=1)",
        "window",
        1,
    ),
    "max_drawdown_20d": (
        "最大回撤",
        "min(close / cummax(close) - 1) within trailing {window} complete bars",
        "window",
        0,
    ),
    "win_rate_20d": ("上涨占比", "mean(return > 0, {window})", "window", 1),
    "obv_trend": (
        "能量潮趋势",
        "OLS slope(local OBV(close, vol), {window}); complete window, first OBV = 0",
        "window",
        0,
    ),
    "vol_surge": ("成交量相对均值", "vol / mean(vol, {window})", "window", 0),
    "amount_ma_ratio": ("成交额均线比", "mean(amount, {short}) / mean(amount, {long})", "long", 0),
    "macd_hist_signal": (
        "MACD 柱相对强度",
        "MyTT.MACD(close,{short},{long},{signal}).hist / mean(abs(hist),{scale_window})",
        "scale_window",
        0,
    ),
    "rsi_14": ("相对强弱", "(MyTT.RSI(close,{window}) - 50) / 50", "seed", 2),
    "boll_position": (
        "布林带相对位置",
        "clip((close-lower)/(upper-lower),0,1); MyTT.BOLL(close,{window},{std_multiplier})",
        "window",
        0,
    ),
}
LABELS = {
    "window": "窗口",
    "short": "短窗口",
    "long": "长窗口",
    "signal": "信号平滑",
    "scale_window": "归一窗口",
    "std_multiplier": "标准差倍数",
}


def schemas(defaults: dict[str, int | float]) -> dict[str, Any]:
    return {
        key: {
            "default": value,
            "editable": True,
            "label": LABELS[key],
            "unit": "multiple" if key == "std_multiplier" else "bars",
            "min": 0.1 if key == "std_multiplier" else 1 if key in {"short", "signal"} else 2,
            "max": 10 if key == "std_multiplier" else 600,
            "step": 0.1 if key == "std_multiplier" else 1,
            "integer": key != "std_multiplier",
        }
        for key, value in defaults.items()
    }


def resolve(defaults: dict[str, int | float], parameters: dict[str, Any]) -> dict[str, int | float]:
    if set(parameters) - set(defaults):
        raise ValueError("包含未声明的因子参数；未静默忽略")
    values = {**defaults, **parameters}
    for key, spec in schemas(defaults).items():
        value = values[key]
        valid_type = type(value) is int if spec["integer"] else type(value) in (int, float)
        if not valid_type or not spec["min"] <= value <= spec["max"] or not math.isfinite(value):
            raise ValueError(
                f"{LABELS[key]}必须为 {spec['min']}—{spec['max']} 的"
                f"{'整数' if spec['integer'] else '有限数值'}"
            )
        if key == "std_multiplier":
            values[key] = float(value)
    if "short" in values and "long" in values and values["short"] >= values["long"]:
        raise ValueError("短窗口必须小于长窗口")
    return values


def metadata(canonical: str, defaults: dict[str, int | float], factor: Factor) -> dict[str, Any]:
    values = resolve(defaults, {key: getattr(factor, key) for key in defaults})
    title, formula, warmup_key, offset = TEMPLATES[canonical]
    params = schemas(defaults)
    for key in params:
        params[key]["value"] = values[key]
    result: dict[str, Any] = {
        "formula": formula.format(**values),
        "parameters": params,
        "resolved_parameters": values,
        "parameterized_title": title,
        "warmup_bars": offset + (int(values[warmup_key]) if warmup_key in values else 0),
        "implementation_version": (
            "obv-local-window-v3" if canonical == "obv_trend" else "builtin-parameters-v2"
        ),
    }
    if values != defaults:
        suffix = (
            f"{values['window']}周期"
            if set(values) == {"window"}
            else " / ".join(f"{LABELS[k]} {v:g}" for k, v in values.items())
        )
        result["display_name"] = f"{title} · {suffix}"
    return result
