"""Alpha158 formulas adapted from Microsoft Qlib v0.9.7 (MIT).

See docs/licenses/qlib-MIT.txt. This is a complete-window adaptation, not a
bit-identical Qlib data provider: missing/invalid inputs invalidate the entire
dependency window, rather than Qlib's min_periods=1 / NaN-skipping behavior.
No volume unit or VWAP is inferred from the existing native feed columns.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from easy_tdx.factor.base import Factor, register_factor

SOURCE_COMMIT = "da920b7f954f48ab1bb64117c976710de198373e"
SOURCE = f"https://github.com/microsoft/qlib/blob/{SOURCE_COMMIT}/qlib/contrib/data/loader.py"
VERSION = "qlib158-complete-window-v1"
EPS = 1e-12
WINDOWS = (5, 10, 20, 30, 60)

# Expressions use Qlib operator names. Greater/Less mean pairwise max/min;
# Rank is trailing time-series average-tie percentile, NOT cross-sectional rank.
_FIXED = {
    "KMID": ("实体相对开盘价", "($close-$open)/$open", ("open", "close")),
    "KLEN": ("振幅相对开盘价", "($high-$low)/$open", ("open", "high", "low")),
    "KMID2": ("实体占振幅", "($close-$open)/($high-$low+1e-12)", ("open", "high", "low", "close")),
    "KUP": ("上影相对开盘价", "($high-Greater($open,$close))/$open", ("open", "high", "close")),
    "KUP2": (
        "上影占振幅",
        "($high-Greater($open,$close))/($high-$low+1e-12)",
        ("open", "high", "low", "close"),
    ),
    "KLOW": ("下影相对开盘价", "(Less($open,$close)-$low)/$open", ("open", "low", "close")),
    "KLOW2": (
        "下影占振幅",
        "(Less($open,$close)-$low)/($high-$low+1e-12)",
        ("open", "high", "low", "close"),
    ),
    "KSFT": ("收盘偏移相对开盘价", "(2*$close-$high-$low)/$open", ("open", "high", "low", "close")),
    "KSFT2": (
        "收盘偏移占振幅",
        "(2*$close-$high-$low)/($high-$low+1e-12)",
        ("high", "low", "close"),
    ),
    "OPEN0": ("开收比", "$open/$close", ("open", "close")),
    "HIGH0": ("高收比", "$high/$close", ("high", "close")),
    "LOW0": ("低收比", "$low/$close", ("low", "close")),
    "VWAP0": ("均价收盘比", "$vwap/$close", ("vwap", "close")),
}
_ROLLING = {
    "ROC": ("历史收盘比", "Ref($close,{w})/$close", ("close",)),
    "MA": ("均价收盘比", "Mean($close,{w})/$close", ("close",)),
    "STD": ("价格波动比", "Std($close,{w})/$close", ("close",)),
    "BETA": ("价格回归斜率比", "Slope($close,{w})/$close", ("close",)),
    "RSQR": ("价格趋势拟合度", "Rsquare($close,{w})", ("close",)),
    "RESI": ("价格回归残差比", "Resi($close,{w})/$close", ("close",)),
    "MAX": ("窗口最高价比", "Max($high,{w})/$close", ("high", "close")),
    "MIN": ("窗口最低价比", "Min($low,{w})/$close", ("low", "close")),
    "QTLU": ("价格八成分位比", "Quantile($close,{w},0.8)/$close", ("close",)),
    "QTLD": ("价格二成分位比", "Quantile($close,{w},0.2)/$close", ("close",)),
    "RANK": ("窗口价格百分位", "Rank($close,{w})", ("close",)),
    "RSV": (
        "窗口价格位置",
        "($close-Min($low,{w}))/(Max($high,{w})-Min($low,{w})+1e-12)",
        ("high", "low", "close"),
    ),
    "IMAX": ("最高价窗口位置", "IdxMax($high,{w})/{w}", ("high",)),
    "IMIN": ("最低价窗口位置", "IdxMin($low,{w})/{w}", ("low",)),
    "IMXD": ("高低价位置差", "(IdxMax($high,{w})-IdxMin($low,{w}))/{w}", ("high", "low")),
    "CORR": ("价量对数相关", "Corr($close,Log($volume+1),{w})", ("close", "volume")),
    "CORD": (
        "价量变化相关",
        "Corr($close/Ref($close,1),Log($volume/Ref($volume,1)+1),{w})",
        ("close", "volume"),
    ),
    "CNTP": ("上涨周期占比", "Mean($close>Ref($close,1),{w})", ("close",)),
    "CNTN": ("下跌周期占比", "Mean($close<Ref($close,1),{w})", ("close",)),
    "CNTD": (
        "涨跌周期占比差",
        "Mean($close>Ref($close,1),{w})-Mean($close<Ref($close,1),{w})",
        ("close",),
    ),
    "SUMP": (
        "上涨幅度占比",
        "Sum(Greater($close-Ref($close,1),0),{w})/(Sum(Abs($close-Ref($close,1)),{w})+1e-12)",
        ("close",),
    ),
    "SUMN": (
        "下跌幅度占比",
        "Sum(Greater(Ref($close,1)-$close,0),{w})/(Sum(Abs($close-Ref($close,1)),{w})+1e-12)",
        ("close",),
    ),
    "SUMD": (
        "涨跌幅度占比差",
        "(Sum(Greater($close-Ref($close,1),0),{w})-Sum(Greater(Ref($close,1)-$close,0),{w}))/(Sum(Abs($close-Ref($close,1)),{w})+1e-12)",
        ("close",),
    ),
    "VMA": ("均量当前量比", "Mean($volume,{w})/($volume+1e-12)", ("volume",)),
    "VSTD": ("量波动当前量比", "Std($volume,{w})/($volume+1e-12)", ("volume",)),
    "WVMA": (
        "量加权波动比",
        "Std(Abs($close/Ref($close,1)-1)*$volume,{w})/(Mean(Abs($close/Ref($close,1)-1)*$volume,{w})+1e-12)",
        ("close", "volume"),
    ),
    "VSUMP": (
        "增量幅度占比",
        "Sum(Greater($volume-Ref($volume,1),0),{w})/(Sum(Abs($volume-Ref($volume,1)),{w})+1e-12)",
        ("volume",),
    ),
    "VSUMN": (
        "减量幅度占比",
        "Sum(Greater(Ref($volume,1)-$volume,0),{w})/(Sum(Abs($volume-Ref($volume,1)),{w})+1e-12)",
        ("volume",),
    ),
    "VSUMD": (
        "增减量幅度占比差",
        "(Sum(Greater($volume-Ref($volume,1),0),{w})-Sum(Greater(Ref($volume,1)-$volume,0),{w}))/(Sum(Abs($volume-Ref($volume,1)),{w})+1e-12)",
        ("volume",),
    ),
}
_SHIFTED = {
    "ROC",
    "CORD",
    "CNTP",
    "CNTN",
    "CNTD",
    "SUMP",
    "SUMN",
    "SUMD",
    "WVMA",
    "VSUMP",
    "VSUMN",
    "VSUMD",
}


@dataclass(frozen=True)
class Alpha158Spec:
    key: str
    family: str
    window: int | None
    title: str
    formula: str
    inputs: tuple[str, ...]

    @property
    def warmup(self) -> int:
        return (self.window or 1) + int(self.family in _SHIFTED)

    @property
    def data_reason(self) -> str:
        if "vwap" in self.inputs:
            return "VWAP 当前仅支持不复权；复权成交均价缺少逐日变换依据，不以收盘价比例替代"
        return ""


SPECS = {
    **{
        key: Alpha158Spec(key, key, None, title, formula, inputs)
        for key, (title, formula, inputs) in _FIXED.items()
    },
    **{
        f"{family}{w}": Alpha158Spec(f"{family}{w}", family, w, title, formula.format(w=w), inputs)
        for family, (title, formula, inputs) in _ROLLING.items()
        for w in WINDOWS
    },
}


def _regression(values: NDArray[np.float64], mode: str) -> float:
    x = np.arange(len(values), dtype=float)
    x -= x.mean()
    y = values - values.mean()
    slope = float(x @ y / (x @ x))
    if mode == "BETA":
        return slope
    if mode == "RESI":
        return float(y[-1] - slope * x[-1])
    if np.isclose(np.std(values, ddof=1), 0, atol=2e-5):
        return float("nan")
    return float((x @ y) ** 2 / ((x @ x) * (y @ y)))


def compute_alpha158(df: pd.DataFrame, spec: Alpha158Spec) -> pd.Series:
    """Compute a full finite dependency window; preserve original row identity."""
    if not df.index.is_unique or not df.index.is_monotonic_increasing:
        raise ValueError("Alpha158 输入索引必须唯一并按时间升序排列")
    if not df.columns.is_unique:
        raise ValueError("Alpha158 输入字段不能重复")
    for identity in ("code", "symbol", "market"):
        if identity in df and df[identity].nunique(dropna=False) > 1:
            raise ValueError("Alpha158 时间序列必须为单标的，不能跨标的滚动")
    time_field = "datetime" if "datetime" in df else "date" if "date" in df else None
    if time_field:
        times = pd.to_datetime(df[time_field], errors="raise")
        if times.isna().any() or not times.is_unique or not times.is_monotonic_increasing:
            raise ValueError("Alpha158 时间字段必须有效、唯一并按时间升序排列")
    missing = set(spec.inputs) - set(df.columns)
    if missing:
        raise ValueError(f"Alpha158 缺少字段：{', '.join(sorted(missing))}")
    data = df.loc[:, list(spec.inputs)].apply(pd.to_numeric, errors="raise").astype(float)
    data = data.where(np.isfinite(data))
    for field in spec.inputs:
        data[field] = data[field].where(data[field] >= 0 if field == "volume" else data[field] > 0)
    # Missing values are not imputed. Invalid candle ranges do not become factors.
    valid = data.notna().all(axis=1)
    if {"high", "low"} <= set(data):
        valid &= data.high >= data.low
    for field in ("open", "close"):
        if field in data and "high" in data:
            valid &= data.high >= data[field]
        if field in data and "low" in data:
            valid &= data.low <= data[field]
    data.loc[~valid] = np.nan
    f, w = spec.family, spec.window
    c = data.get("close")
    with np.errstate(divide="ignore", invalid="ignore"):
        if w is None:
            if f.endswith("0"):
                result = data[f[:-1].lower()] / data.close
            else:
                numerator = {
                    "KMID": lambda: data.close - data.open,
                    "KLEN": lambda: data.high - data.low,
                    "KUP": lambda: data.high - np.maximum(data.open, data.close),
                    "KLOW": lambda: np.minimum(data.open, data.close) - data.low,
                    "KSFT": lambda: 2 * data.close - data.high - data.low,
                }[f.removesuffix("2")]()
                result = numerator / (data.high - data.low + EPS if f.endswith("2") else data.open)
        elif f == "ROC":
            result = data.close.shift(w) / data.close
        elif f in {"MA", "STD", "MAX", "MIN", "QTLU", "QTLD"}:
            field = "high" if f == "MAX" else "low" if f == "MIN" else "close"
            r = data[field].rolling(w, min_periods=w)
            if f in {"QTLU", "QTLD"}:
                result = r.quantile(0.8 if f == "QTLU" else 0.2) / c
            else:
                result = (
                    getattr(r, {"MA": "mean", "STD": "std", "MAX": "max", "MIN": "min"}[f])() / c
                )
        elif f in {"BETA", "RSQR", "RESI"}:
            result = data.close.rolling(w, min_periods=w).apply(
                lambda a: _regression(a, f), raw=True
            )
            if f != "RSQR":
                result = result / c
        elif f == "RANK":
            result = data.close.rolling(w, min_periods=w).rank(method="average", pct=True)
        elif f == "RSV":
            lo = data.low.rolling(w, min_periods=w).min()
            result = (c - lo) / (data.high.rolling(w, min_periods=w).max() - lo + EPS)
        elif f in {"IMAX", "IMIN", "IMXD"}:
            hi = (
                data.high.rolling(w, min_periods=w).apply(lambda a: a.argmax() + 1, raw=True)
                if f != "IMIN"
                else 0
            )
            lo = (
                data.low.rolling(w, min_periods=w).apply(lambda a: a.argmin() + 1, raw=True)
                if f != "IMAX"
                else 0
            )
            result = (hi if f == "IMAX" else lo if f == "IMIN" else hi - lo) / w
        elif f in {"CORR", "CORD"}:
            left = data.close if f == "CORR" else data.close / data.close.shift(1)
            right = (
                np.log(data.volume + 1)
                if f == "CORR"
                else np.log(data.volume / data.volume.shift(1) + 1)
            )
            left, right = left.where(np.isfinite(left)), right.where(np.isfinite(right))
            result = left.rolling(w, min_periods=w).corr(right)
            constant = np.isclose(left.rolling(w).std(), 0, atol=2e-5) | np.isclose(
                right.rolling(w).std(), 0, atol=2e-5
            )
            result = result.mask(constant)
        elif f.startswith("CNT"):
            delta = data.close.diff()
            up, down = (delta > 0).astype(float), (delta < 0).astype(float)
            counts = up if f == "CNTP" else down if f == "CNTN" else up - down
            result = counts.where(delta.notna()).rolling(w, min_periods=w).mean()
        elif f.startswith(("SUM", "VSUM")):
            delta = data["volume" if f.startswith("V") else "close"].diff()
            up = delta.clip(lower=0).rolling(w, min_periods=w).sum()
            down = (-delta).clip(lower=0).rolling(w, min_periods=w).sum()
            result = (up if f.endswith("P") else down if f.endswith("N") else up - down) / (
                delta.abs().rolling(w, min_periods=w).sum() + EPS
            )
        elif f in {"VMA", "VSTD"}:
            r = data.volume.rolling(w, min_periods=w)
            result = (r.mean() if f == "VMA" else r.std()) / (data.volume + EPS)
        elif f == "WVMA":
            weighted = (data.close / data.close.shift(1) - 1).abs() * data.volume
            r = weighted.rolling(w, min_periods=w)
            result = r.std() / (r.mean() + EPS)
        else:
            raise ValueError(f"未实现 Alpha158 公式：{f}")
    dependency_valid = (
        valid.astype(int).rolling(spec.warmup, min_periods=spec.warmup).sum() == spec.warmup
    )
    return result.where(dependency_valid & np.isfinite(result)).rename(
        f"alpha158_{spec.key.lower()}"
    )


class Alpha158Factor(Factor):
    spec: Alpha158Spec

    def __init__(self, *, window: int | None = None) -> None:
        super().__init__()
        if window is not None:
            if self.spec.window is None:
                raise ValueError(f"{self.name} 没有窗口参数")
            if type(window) is not int or not 2 <= window <= 600:
                raise ValueError("因子窗口必须是 2—600 的整数 K 线根数")
            self.spec = replace(
                self.spec, window=window, formula=_ROLLING[self.spec.family][1].format(w=window)
            )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return compute_alpha158(df, self.spec)


def definition_metadata(
    cls: type[Alpha158Factor], instance: Alpha158Factor | None = None
) -> dict[str, Any]:
    spec = instance.spec if instance is not None else cls.spec
    return {
        "display_name": f"{spec.title}{f' · {spec.window}周期' if spec.window else ''}",
        "library": "qlib_alpha158",
        "family": spec.family,
        "source": SOURCE,
        "source_commit": SOURCE_COMMIT,
        "source_license": "MIT",
        "formula": spec.formula,
        "implementation_version": VERSION,
        "warmup_bars": spec.warmup,
        "warmup_note": "完整依赖窗口才输出；缺失会使相关窗口为空，不填零或缩短窗口。",
        "parameters": {
            "window": {
                "default": cls.spec.window,
                "value": spec.window,
                "editable": True,
                "unit": "bars",
                "min": 2,
                "max": 600,
            }
        }
        if spec.window
        else {},
        "resolved_parameters": {"window": spec.window} if spec.window else {},
        "data_requirements": list(spec.inputs),
        "data_contract_version": "mac-factor-units-v1"
        if {"volume", "vwap"}.intersection(spec.inputs)
        else None,
        "status": "conditional" if spec.data_reason else "available",
        "implemented": True,
        "available": True,
        "evaluation_available": True,
        "supported_adjustments": ["NONE"] if "vwap" in spec.inputs else ["NONE", "QFQ", "HFQ"],
        "adjustment_unavailable_reason": spec.data_reason,
        "unavailable_reason": "",
        "evaluation_unavailable_reason": "",
        "limitations": [
            *(
                [
                    "VWAP 仅在不复权、量额单位核验通过时用成交额／实际成交股数计算；"
                    "零成交量为空，不用收盘价或典型价填充。"
                ]
                if "vwap" in spec.inputs
                else []
            ),
            *(
                ["当前使用自定义窗口，是原公式的参数扩展，不是 Qlib 默认 158 项中的额外标准条目。"]
                if spec.window != cls.spec.window
                else []
            ),
            *(
                [
                    "成交量使用实际成交股数，不作价格复权的倒数缩放；"
                    "Web 仅接受通过同日期 MAC 不复权量额核验的数据，其他来源明确报缺数据。"
                ]
                if "volume" in spec.inputs
                else []
            ),
            "Qlib 官方公式的完整窗口适配版：不采用 min_periods=1 或跳过缺失的默认行为，"
            "不能称为全序列逐位相等。",
            "窗口按所选 K 线根数解释；分钟线是同公式分钟周期适配，不自动换算成日线。",
            "STD 为样本标准差；RANK 为单股时间序列平均并列排名；"
            "极值位置从窗口左端 1 开始，同值取首次。",
            "公式中的 1e-12 按原式保留；合法常数产生的 0 与缺失值不同。"
            "相关/拟合度在近常数时未定义。",
            "数值方向不是买卖建议；新增公式仍需真实冻结行情及完整研究流程验收。",
        ],
    }


for _spec in SPECS.values():
    register_factor(
        type(
            f"Alpha158{_spec.key}",
            (Alpha158Factor,),
            {
                "__module__": __name__,
                "name": f"alpha158_{_spec.key.lower()}",
                "category": "volume" if "volume" in _spec.inputs else "technical",
                "description": f"Alpha158 {_spec.key} · {_spec.title}（完整窗口）",
                "inputs": _spec.inputs,
                "spec": _spec,
            },
        )
    )
