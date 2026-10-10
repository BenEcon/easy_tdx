"""Selected Alpha101 formulas, locally adapted from DolphinDB's Apache-2.0 module.

Reference author: DolphinDB; commit 43ace2cc4b81d048864ec2e40c25728d5d464e05.
Modified 2026-10-10: original Python implementation, explicit complete windows,
missing values, stable correlation, configuration and panel execution. See
licenses/Alpha101-reference-notice.md and DolphinDB-Apache-2.0.txt.
Local validation is authorized; production redistribution review is outstanding.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.computation import computation_checkpoint
from easy_tdx.factor.base import Factor, PanelFactor, register_factor
from easy_tdx.factor.panel import FactorPanel, cross_section_rank

VERSION = "alpha101-complete-window-v7"
COMMIT = "43ace2cc4b81d048864ec2e40c25728d5d464e05"
SOURCE = (
    f"https://github.com/dolphindb/DolphinDBModules/blob/{COMMIT}/wq101alpha/src/wq101alpha.dos"
)


@dataclass(frozen=True)
class Window:
    key: str
    value: int
    label: str
    minimum: int = 1


@dataclass(frozen=True)
class Spec:
    number: int
    title: str
    inputs: tuple[str, ...]
    formula: str
    window: int | None = None
    panel: bool = False
    reference: int | None = None
    reference_parameters: tuple[tuple[str, int], ...] = ()
    threshold: float | None = None
    windows: tuple[Window, ...] = ()
    warmup_paths: tuple[tuple[int, tuple[str, ...]], ...] = ()
    reference_multiplier: int = 1

    @property
    def resolved_parameters(self) -> dict[str, int]:
        return {w.key: w.value for w in self.windows}

    @property
    def reference_factor(self) -> Factor:
        from easy_tdx.factor.configuration import configure_factor

        assert self.reference is not None
        return configure_factor(f"gtja191_{self.reference:03d}", dict(self.reference_parameters))

    @property
    def warmup(self) -> int:
        if self.reference is not None:
            return int(self.reference_factor.spec.warmup)  # type: ignore[attr-defined]
        if self.windows:
            p = self.resolved_parameters
            return max(offset + sum(p[key] for key in keys) for offset, keys in self.warmup_paths)
        w = self.window or 1
        if self.number in {49, 51}:
            return 2 * w + 1
        if self.number == 10:
            return w + 1
        return w + 1 if self.number in {9, 12, 53} else max(w, 3) if self.number == 23 else w


SPECS = {
    3: Spec(
        3,
        "开盘与成交量截面排序相关",
        ("open", "volume"),
        "-corr(cs_rank(open), cs_rank(volume), window)",
        10,
        True,
    ),
    4: Spec(4, "最低价截面排序的时序位置", ("low",), "-ts_rank(cs_rank(low), window)", 9, True),
    6: Spec(6, "开盘与成交量反向相关", ("open", "volume"), "-corr(open, volume, window)", 10),
    9: Spec(
        9,
        "连续价差条件方向",
        ("close",),
        "d=diff(close,1); min(d,window)>0 or max(d,window)<0 ? d : -d",
        5,
    ),
    12: Spec(
        12,
        "量差方向与反向价差",
        ("close", "volume"),
        "sign(diff(volume,window)) * -diff(close,window)",
        1,
    ),
    23: Spec(23, "高价突破条件变化", ("high",), "high>mean(high,window) ? -diff(high,2) : 0", 20),
    53: Spec(
        53,
        "收盘区间比变化",
        ("close", "high", "low"),
        "-diff(((close-low)-(high-close))/(close-low),window)",
        9,
    ),
    101: Spec(
        101, "开收盘差相对振幅", ("close", "open", "high", "low"), "(close-open)/(high-low+0.001)"
    ),
}

# Same formulas share the existing, independently tested kernels. Different
# default parameters (002 vs GTJA001) remain distinct defaults, not new algebra.
for _n, _ref, _parameters in (
    (2, 1, {"lag": 2, "corr": 6}),
    (11, 7, {"range": 3, "lag": 3}),
    (13, 99, {"covariance": 5}),
    (14, 136, {"lag": 3, "corr": 10}),
    (15, 32, {"corr": 3, "sum": 3}),
    (16, 83, {"covariance": 5}),
    (18, 54, {"body_std": 5, "corr": 10}),
    (20, 107, {"lag": 1}),
    (22, 104, {"corr": 5, "lag": 5, "volatility": 20}),
    (27, 36, {"corr": 6, "sum": 2}),
    (35, 117, {"volume_rank": 32, "price_rank": 16, "return_rank": 32}),
    (37, 184, {"lag": 1, "corr": 200}),
    (40, 42, {"volatility": 10, "corr": 10}),
    (41, 13, {}),
    (42, 120, {}),
    (44, 62, {"corr": 5}),
    (45, 113, {"lag": 5, "mean": 20, "corr": 2, "short": 5, "long": 20}),
    (46, 86, {"window": 10}),
    (50, 16, {"corr": 5, "peak": 5}),
    (55, 176, {"range": 12, "corr": 6}),
):
    from easy_tdx.factor.builtin.gtja191 import SPECS as GTJA_SPECS

    _source = GTJA_SPECS[_ref]
    SPECS[_n] = Spec(
        _n,
        _source.title,
        _source.inputs,
        _source.formula,
        panel=_source.panel,
        reference=_ref,
        reference_parameters=tuple(_parameters.items()),
    )
SPECS[18] = replace(
    SPECS[18],
    formula="−cs_rank(std(abs(close−open),body_std)+(close−open)+corr(close,open,corr))",
)
SPECS[55] = replace(
    SPECS[55],
    title="区间位置与量排名反向相关",
    formula="−corr(cs_rank((close−ts_min(low,range))/(ts_max(high,range)−ts_min(low,range))),cs_rank(volume),corr)",
    reference_multiplier=-1,
)
SPECS[27] = replace(
    SPECS[27],
    title="量价排名相关阈值方向",
    formula="cs_rank(mean(corr(cs_rank(volume),cs_rank(vwap),corr),sum)) > threshold ? −1 : 1",
    threshold=0.5,
)
SPECS.update(
    {
        32: Spec(
            32,
            "均价偏离与滞后价相关归一化",
            ("close", "vwap"),
            "cs_scale(mean(close,mean)−close)+20×cs_scale(corr(vwap,delay(close,lag),corr))",
            panel=True,
            windows=(
                Window("mean", 7, "均价窗口"),
                Window("lag", 5, "价格滞后"),
                Window("corr", 230, "相关窗口", 2),
            ),
            warmup_paths=((0, ("mean",)), (0, ("lag", "corr"))),
        ),
        57: Spec(
            57,
            "收盘均价偏离与极值位置衰减",
            ("close", "vwap"),
            "−(close−vwap)/decay_linear(cs_rank(ts_argmax(close,peak)),decay)",
            panel=True,
            windows=(Window("peak", 30, "极值位置窗口"), Window("decay", 2, "线性衰减窗口")),
            warmup_paths=((-1, ("peak", "decay")),),
        ),
        60: Spec(
            60,
            "量价区间排名与极值位置归一化",
            ("close", "high", "low", "volume"),
            "cs_scale(cs_rank(ts_argmax(close,peak)))−2×cs_scale(cs_rank((2×close−low−high)/(high−low)×volume))",
            panel=True,
            windows=(Window("peak", 10, "极值位置窗口"),),
            warmup_paths=((0, ("peak",)),),
        ),
        5: Spec(
            5,
            "开盘均价偏离与收盘偏离排名",
            ("open", "close", "vwap"),
            "−cs_rank(open−mean(vwap,mean))×abs(cs_rank(close−vwap))",
            panel=True,
            windows=(Window("mean", 10, "成交均价窗口"),),
            warmup_paths=((0, ("mean",)),),
        ),
        52: Spec(
            52,
            "低点变化与区间收益量位置",
            ("close", "low", "volume"),
            "(delay(ts_min(low,trough),lag)−ts_min(low,trough))×"
            "cs_rank((sum(returns,long)−sum(returns,short))/(long−short))×ts_rank(volume,volume_rank)",
            panel=True,
            windows=(
                Window("trough", 5, "低点窗口"),
                Window("lag", 5, "低点变化间隔"),
                Window("long", 240, "长收益累计窗口"),
                Window("short", 20, "短收益累计窗口"),
                Window("volume_rank", 5, "量时序排名窗口"),
            ),
            warmup_paths=((0, ("trough", "lag")), (1, ("long",)), (0, ("volume_rank",))),
        ),
        24: Spec(
            24,
            "长期均价变化条件回撤",
            ("close",),
            "diff(mean(close,mean),lag)/delay(close,lag) ≤ threshold ? "
            "−(close−ts_min(close,trough)) : −diff(close,price_lag)",
            threshold=0.05,
            windows=(
                Window("mean", 100, "收盘均价窗口"),
                Window("lag", 100, "均价变化间隔"),
                Window("trough", 100, "收盘低点窗口"),
                Window("price_lag", 3, "短价差间隔"),
            ),
            warmup_paths=((0, ("mean", "lag")), (0, ("trough",)), (1, ("price_lag",))),
        ),
        8: Spec(
            8,
            "开盘累计与收益累计差排名",
            ("open", "close"),
            "−cs_rank(diff(sum(open,sum)×sum(returns,sum),lag))",
            panel=True,
            windows=(Window("sum", 5, "累计窗口"), Window("lag", 10, "差分间隔")),
            warmup_paths=((1, ("sum", "lag")),),
        ),
        19: Spec(
            19,
            "价格方向与长期收益累计排名",
            ("close",),
            "−sign(2×(close−delay(close,lag)))×(1+cs_rank(1+sum(returns,returns)))",
            panel=True,
            windows=(Window("lag", 7, "价格方向间隔"), Window("returns", 250, "收益累计窗口")),
            warmup_paths=((1, ("lag",)), (1, ("returns",))),
        ),
        26: Spec(
            26,
            "量高时序排名相关上界",
            ("volume", "high"),
            "−ts_max(corr(ts_rank(volume,rank),ts_rank(high,rank),corr),max)",
            windows=(
                Window("rank", 5, "时序排名窗口"),
                Window("corr", 5, "相关窗口", 2),
                Window("max", 3, "最大值窗口"),
            ),
            warmup_paths=((-2, ("rank", "corr", "max")),),
        ),
        30: Spec(
            30,
            "连续价格方向与累计量比",
            ("close", "volume"),
            "(1−cs_rank(sum(sign(diff(close,1)),direction)))×sum(volume,short)/sum(volume,long)",
            panel=True,
            windows=(
                Window("direction", 3, "方向累计窗口"),
                Window("short", 5, "短累计量窗口"),
                Window("long", 20, "长累计量窗口"),
            ),
            warmup_paths=((1, ("direction",)), (0, ("long",))),
        ),
        34: Spec(
            34,
            "收益波动比与价格变化复合排名",
            ("close",),
            "cs_rank(2−cs_rank(std(returns,short)/std(returns,long))−cs_rank(diff(close,lag)))",
            panel=True,
            windows=(
                Window("short", 2, "短收益波动窗口", 2),
                Window("long", 5, "长收益波动窗口", 2),
                Window("lag", 1, "价格变化间隔"),
            ),
            warmup_paths=((1, ("long",)), (1, ("lag",))),
        ),
        10: Spec(
            10,
            "连续价差条件截面位置",
            ("close",),
            "cs_rank(min(diff(C),window)>0 or max(diff(C),window)<0 ? diff(C) : -diff(C))",
            4,
            True,
        ),
        33: Spec(33, "开收盘比截面位置", ("open", "close"), "cs_rank(open/close-1)", panel=True),
        38: Spec(
            38,
            "收盘时序位置与开收盘比",
            ("open", "close"),
            "-cs_rank(ts_rank(close,window))*cs_rank(close/open)",
            10,
            True,
        ),
        49: Spec(
            49,
            "价格曲率负阈值切换一",
            ("close",),
            "a=(C[t-2w]-2C[t-w]+C[t])/w；a<threshold ? 1 : -diff(C,1)",
            10,
            threshold=-0.1,
        ),
        51: Spec(
            51,
            "价格曲率负阈值切换二",
            ("close",),
            "a=(C[t-2w]-2C[t-w]+C[t])/w；a<threshold ? 1 : -diff(C,1)",
            10,
            threshold=-0.05,
        ),
        54: Spec(
            54,
            "价格区间与开收盘五次比",
            ("open", "close", "high", "low"),
            "-(low-close)/(low-high)*(open/close)^5",
        ),
    }
)


def correlation(left: pd.Series, right: pd.Series, window: int) -> pd.Series:
    """Local centered/scaled Pearson; no epsilon denominator or stale rolling sum."""
    out = np.full(len(left), np.nan)
    x, y = left.to_numpy(float), right.to_numpy(float)
    for end in range(window - 1, len(left)):
        computation_checkpoint()
        a, b = x[end + 1 - window : end + 1], y[end + 1 - window : end + 1]
        if not (np.isfinite(a).all() and np.isfinite(b).all()):
            continue
        centered = []
        for values in (a, b):
            scale = np.max(np.abs(values))
            scaled = values / scale if scale else values
            delta = scaled - scaled.mean()
            norm = np.linalg.norm(delta)
            if norm <= 1e-12:
                break
            centered.append(delta / norm)
        if len(centered) == 2:
            out[end] = np.clip(np.dot(*centered), -1, 1)
    return pd.Series(out, index=left.index)


def clean(frame: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    if frame.columns.has_duplicates or set(spec.inputs) - set(frame):
        raise ValueError("Alpha101 输入缺失或重复；不使用替代字段")
    for field in spec.inputs:
        reason = frame.attrs.get("factor_input_errors", {}).get(field)
        if reason:
            raise ValueError(str(reason))
    data = frame[list(spec.inputs)].apply(pd.to_numeric, errors="raise").astype(float)
    data = data.replace([np.inf, -np.inf], np.nan)
    for field in spec.inputs:
        data[field] = data[field].where(
            data[field].ge(0) if field == "volume" else data[field].gt(0)
        )
    if {"high", "low"} <= set(data):
        prices = [key for key in ("open", "close", "high", "low") if key in data]
        valid = data.high.ge(data[prices].max(axis=1)) & data.low.le(data[prices].min(axis=1))
        data = data.where(valid, np.nan)
    if spec.number == 52:
        data = data.where(data.low.le(data.close), np.nan)
    return data


def compute_series(frame: pd.DataFrame, spec: Spec) -> pd.Series:
    computation_checkpoint()
    if spec.panel:
        raise ValueError("Alpha101 截面因子需要明确股票池，不能用单股代替")
    if spec.reference is not None:
        return (spec.reference_factor.compute(frame) * spec.reference_multiplier).rename(
            f"alpha101_{spec.number:03d}"
        )
    if spec.number == 24:
        from easy_tdx.factor.builtin.alpha101_compound import compute_conditional_trough

        return compute_conditional_trough(frame, spec).rename("alpha101_024")
    if spec.number == 26:
        from easy_tdx.factor.builtin.alpha101_compound import compute_rank_correlation

        return compute_rank_correlation(frame, spec).rename("alpha101_026")
    data = clean(frame, spec)
    w = spec.window or 1
    with np.errstate(all="ignore"):
        if spec.number == 6:
            result = -correlation(data.open, data.volume, w)
        elif spec.number == 9:
            delta = data.close.diff()
            same = delta.rolling(w).min().gt(0) | delta.rolling(w).max().lt(0)
            result = delta.where(same, -delta)
        elif spec.number == 12:
            result = np.sign(data.volume.diff(w)) * -data.close.diff(w)
        elif spec.number == 23:
            result = -data.high.diff(2).where(data.high.gt(data.high.rolling(w).mean()), 0.0)
        elif spec.number == 53:
            ratio = ((data.close - data.low) - (data.high - data.close)) / (data.close - data.low)
            result = -ratio.replace([np.inf, -np.inf], np.nan).diff(w)
        elif spec.number == 101:
            result = (data.close - data.open) / (data.high - data.low + 0.001)
        elif spec.number in {49, 51, 54}:
            result = decimal_prices(data, spec)
        else:
            raise ValueError("未实现的 Alpha101 编号")
    valid = data.notna().all(axis=1).astype(int).rolling(spec.warmup).sum().eq(spec.warmup)
    return result.where(valid & np.isfinite(result)).rename(f"alpha101_{spec.number:03d}")


def decimal_prices(data: pd.DataFrame, spec: Spec) -> pd.Series:
    """Exact input-decimal thresholds; avoid overflowing fifth powers separately."""
    out = np.full(len(data), np.nan)
    w = spec.window or 1
    with localcontext() as ctx:
        ctx.prec = 60
        for i in range(spec.warmup - 1, len(data)):
            computation_checkpoint()
            if spec.number == 54:
                row = data.iloc[i]
                if not row.notna().all() or row.low == row.high:
                    continue
                o, c, h, low = (Decimal(str(row[k])) for k in ("open", "close", "high", "low"))
                out[i] = float(-(low - c) / (low - h) * (o / c) ** 5)
            else:
                values = data.close.iloc[[i - 2 * w, i - w, i - 1, i]]
                if not values.notna().all():
                    continue
                a, b, previous, c = (Decimal(str(v)) for v in values)
                out[i] = (
                    1 if a - 2 * b + c < Decimal(str(spec.threshold)) * w else float(previous - c)
                )
    return pd.Series(out, index=data.index)


class Alpha101Factor(Factor):
    spec: Spec

    def __init__(self, **parameters: Any) -> None:
        super().__init__()
        if self.spec.windows:
            allowed = set(self.spec.resolved_parameters) | (
                {"threshold"} if self.spec.number == 24 else set()
            )
            if set(parameters) - allowed:
                raise ValueError("Alpha101 仅接受声明的参数")
            if self.spec.number == 24 and "threshold" in parameters:
                threshold = parameters["threshold"]
                if (
                    type(threshold) not in {int, float}
                    or not np.isfinite(threshold)
                    or not -1 <= threshold <= 1
                ):
                    raise ValueError("均价变化阈值须为 -1 至 1 的有限比例，不接受布尔值")
                self.spec = replace(self.spec, threshold=float(threshold))
            windows = []
            for declared_window in self.spec.windows:
                value = parameters.get(declared_window.key, declared_window.value)
                if type(value) is not int or not declared_window.minimum <= value <= 500:
                    raise ValueError("Alpha101 窗口须为声明范围内的整数，不接受布尔值")
                windows.append(replace(declared_window, value=value))
            self.spec = replace(self.spec, windows=tuple(windows))
            p = self.spec.resolved_parameters
            if "short" in p and p["short"] >= p["long"]:
                raise ValueError("短窗口必须小于长窗口")
            if self.spec.warmup > 600:
                raise ValueError("Alpha101 复合依赖窗口不能超过 600 根")
            return
        if self.spec.reference is not None:
            defaults = dict(self.spec.reference_parameters)
            allowed = set(defaults) | ({"threshold"} if self.spec.number == 27 else set())
            if set(parameters) - allowed:
                raise ValueError("Alpha101 仅接受声明的参数")
            if self.spec.number == 27 and "threshold" in parameters:
                value = parameters["threshold"]
                if type(value) not in {int, float} or not np.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("排名阈值须为 0 至 1 的有限比例，不接受布尔值")
                self.spec = replace(self.spec, threshold=float(value))
            self.spec = replace(
                self.spec,
                reference_parameters=tuple(
                    (defaults | {k: v for k, v in parameters.items() if k in defaults}).items()
                ),
            )
            # Reuse canonical validation; unknown keys/bools/oversized windows fail.
            self.spec.reference_factor
            return
        if set(parameters) - (
            {"window"} | ({"threshold"} if self.spec.threshold is not None else set())
        ):
            raise ValueError("Alpha101 仅接受声明的参数")
        window = parameters.get("window")
        if "window" in parameters and window is None:
            raise ValueError("Alpha101 窗口不能为 null")
        if window is not None:
            minimum = 2 if self.spec.number in {3, 6} else 1
            if self.spec.window is None or type(window) is not int or not minimum <= window <= 500:
                raise ValueError("Alpha101 窗口须为声明范围内的整数，不接受布尔值")
            self.spec = replace(self.spec, window=window)
        if "threshold" in parameters:
            value = parameters["threshold"]
            if type(value) not in {int, float} or not np.isfinite(value) or not -10 <= value <= 0:
                raise ValueError("曲率阈值须为 -10 至 0 的有限数值")
            self.spec = replace(self.spec, threshold=float(value))
        if self.spec.number in {49, 51} and self.spec.warmup > 600:
            raise ValueError("Alpha101 复合依赖窗口不能超过 600 根")

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return compute_series(df, self.spec)


class Alpha101PanelFactor(Alpha101Factor, PanelFactor):
    def compute_panel(self, panel: FactorPanel) -> pd.DataFrame:
        computation_checkpoint()
        if self.spec.windows:
            from easy_tdx.factor.builtin.alpha101_compound import compute_compound_panel

            return panel.validate_result(compute_compound_panel(panel, self.spec), self.name)
        if self.spec.reference is not None:
            factor = self.spec.reference_factor
            assert isinstance(factor, PanelFactor)
            if self.spec.number == 27:
                ranked = factor.compute_panel(panel)
                result = pd.DataFrame(
                    np.where(ranked.gt(self.spec.threshold), -1.0, 1.0),
                    index=ranked.index,
                    columns=ranked.columns,
                ).where(ranked.notna())
                return panel.validate_result(result, self.name)
            return panel.validate_result(
                factor.compute_panel(panel) * self.spec.reference_multiplier, self.name
            )
        if self.spec.number in {10, 33, 38}:
            return panel.validate_result(compute_price_panel(panel, self.spec), self.name)
        ranks = {}
        for field in self.inputs:
            values = panel.fields[field]
            valid = values.ge(0) if field == "volume" else values.gt(0)
            ranks[field] = cross_section_rank(values.where(valid))
        w = self.spec.window or 1
        if self.spec.number == 3:
            result = pd.DataFrame(
                {
                    symbol: -correlation(ranks["open"][symbol], ranks["volume"][symbol], w)
                    for symbol in panel.observed.columns
                }
            )
        elif self.spec.number == 4:
            result = -ranks["low"].rolling(w, min_periods=w).rank(method="average", pct=True)
        else:
            raise ValueError("未实现的 Alpha101 整池编号")
        computation_checkpoint()
        return panel.validate_result(result, self.name)


def compute_price_panel(panel: FactorPanel, spec: Spec) -> pd.DataFrame:
    from easy_tdx.factor.builtin.gtja191 import _panel_ratio_rank

    c = panel.fields["close"].where(panel.fields["close"].gt(0))
    w = spec.window or 1
    if spec.number == 10:
        # Decimal subtraction preserves ties such as 10.1-10 == 20.1-20.
        delta = pd.DataFrame(np.nan, index=c.index, columns=c.columns)
        for symbol in c:
            with localcontext() as ctx:
                ctx.prec = 60
                values = c[symbol].to_numpy(float)
                for i in range(1, len(values)):
                    computation_checkpoint()
                    if np.isfinite(values[i - 1 : i + 1]).all():
                        delta.iloc[i, delta.columns.get_loc(symbol)] = float(
                            Decimal(str(values[i])) - Decimal(str(values[i - 1]))
                        )
        same = delta.rolling(w).min().gt(0) | delta.rolling(w).max().lt(0)
        complete = c.notna().astype(int).rolling(w + 1).sum().eq(w + 1)
        return cross_section_rank(delta.where(same, -delta).where(complete))
    o = panel.fields["open"].where(panel.fields["open"].gt(0))
    if spec.number == 33:
        return _panel_ratio_rank(o, c)
    position = c.rolling(w).rank(method="average", pct=True)
    complete = (c.notna() & o.notna()).astype(int).rolling(w).sum().eq(w)
    return -cross_section_rank(position.where(complete)) * _panel_ratio_rank(
        c.where(complete), o.where(complete)
    )


def definition_metadata(
    cls: type[Alpha101Factor], instance: Alpha101Factor | None = None
) -> dict[str, Any]:
    spec = (instance or cls()).spec
    result: dict[str, Any] = {
        "display_name": f"Alpha101 {spec.number:03d} · {spec.title}",
        "parameterized_title": f"Alpha101 {spec.number:03d} · {spec.title}",
        "library": "alpha101",
        "family": f"alpha101_{spec.number:03d}",
        "parameter_family": f"alpha101_{spec.number:03d}",
        "formula": spec.formula,
        "source": SOURCE,
        "source_commit": COMMIT,
        "source_license": "Apache-2.0（DolphinDB 参考模块）；生产发布待许可复核",
        "original_source": "https://arxiv.org/abs/1601.00991v3",
        "implementation_version": VERSION,
        "release_status": "local_validation_only_pending_license_review",
        "warmup_bars": spec.warmup,
        "warmup_terms": (
            [{"offset": 0, "windows": ["window"]}, {"offset": 3, "windows": []}]
            if spec.number == 23
            else [{"offset": 1 if spec.number in {9, 12, 53} else 0, "windows": ["window"]}]
            if spec.window is not None
            else [{"offset": 1, "windows": []}]
        ),
        "warmup_note": "完整依赖窗口；缺失与非法输入不填零。常数相关或零分母可继续为空。",
        "resolved_parameters": {"window": spec.window} if spec.window is not None else {},
        "parameters": {
            "window": {
                "default": cls.spec.window,
                "value": spec.window,
                "editable": True,
                "min": 2 if spec.number in {3, 6} else 1,
                "max": 500,
                "unit": "bars",
                "label": "窗口",
            }
        }
        if spec.window is not None
        else {},
        "implemented": True,
        "status": "available",
        "available": not spec.panel,
        "evaluation_available": True,
        "evaluation_unavailable_reason": "",
        "unavailable_reason": "需要明确股票池截面检验" if spec.panel else "",
        "data_requirements": list(spec.inputs),
        "supported_adjustments": ["NONE"] if "vwap" in spec.inputs else ["NONE", "QFQ", "HFQ"],
        "adjustment_unavailable_reason": (
            "VWAP仅支持不复权：需同根实际成交额与实际股数；不能用收盘价或复权比例替代"
            if "vwap" in spec.inputs
            else ""
        ),
        "limitations": [
            "仅授权本地适配验证；生产发布待许可复核，不表示原论文全部权利已解除。",
            "原参考基于日线；其它周期为明确的按当前 K 线根数推广，不换算交易日。",
            "截面 rank 为同日有效标的平均并列序号/数量，至少2个标的；"
            "ts_rank 同样平均并列并归一到(0,1]。",
            "完整窗口内缺失不跨过；量为实际成交股数，不替换为成交额或复权伪成交量。",
            "相关先按各自窗口最大绝对值缩放并中心化；中心化范数≤1e−12视为无定义，不制造零相关。",
            "101号保留固定价格常数0.001，故对价格单位及复权敏感；53号收盘等于最低价时分母为零，留空。",
            "数值方向不自动解释为买卖建议；参数变化不增加标准因子数量。",
            "002/033/038的比值排序使用精确十进制输入比值，保留比例相同的并列，不先舍入为浮点数。",
        ],
    }
    if spec.reference is not None:
        from easy_tdx.factor.builtin import gtja191

        factor = spec.reference_factor
        assert isinstance(factor, gtja191.GTJAFactor)
        reference = gtja191.definition_metadata(type(factor), factor)
        for key in (
            "parameters",
            "resolved_parameters",
            "warmup_terms",
            "warmup_limit",
            "warmup_note",
            "parameter_family",
            "supported_adjustments",
            "adjustment_unavailable_reason",
        ):
            if key in reference:
                result[key] = reference[key]
        # The Alpha default may differ from the GTJA default (002 lag=2).
        for key, value in cls.spec.reference_parameters:
            result["parameters"][key]["default"] = value
        if "warmup_terms" not in reference:
            result["warmup_terms"] = [
                {
                    "offset": reference["warmup_offset"],
                    "windows": ["window"] * reference["warmup_multiplier"],
                }
            ]
        result["reuses_factor"] = factor.name
        result["reused_implementation_version"] = reference["implementation_version"]
        result["reused_source"] = reference["source"]
        result["reused_multiplier"] = spec.reference_multiplier
        if spec.reference_multiplier != 1:
            result["parameter_family"] = f"alpha101_{spec.number:03d}"
            result["limitations"].append(
                "055为GTJA176数学结果的负值；负号是公式的一部分，不是按历史收益自动反向。二者并非同义，不去重。"
            )
        result["limitations"].append(
            "复用既有 GTJA191 数学内核；保留各库来源，默认参数相同的项目不重复计数。"
        )
        # Reused kernels have their own numerical conventions and restrictions;
        # do not describe all of them as the first Alpha batch's Pearson kernel.
        result["limitations"] = [
            note for note in result["limitations"] if not note.startswith(("相关先", "101号"))
        ]
        result["limitations"].extend(
            "复用内核说明：" + note for note in reference.get("limitations", [])
        )
    if spec.windows:
        defaults = cls.spec.resolved_parameters
        result["resolved_parameters"] = spec.resolved_parameters
        result["parameters"] = {
            w.key: {
                "default": defaults[w.key],
                "value": w.value,
                "editable": True,
                "min": w.minimum,
                "max": 500,
                "unit": "bars",
                "label": w.label,
            }
            for w in spec.windows
        }
        result["warmup_terms"] = [
            {"offset": offset, "windows": list(keys)} for offset, keys in spec.warmup_paths
        ]
        result["warmup_limit"] = 600
        result["limitations"] = [
            note for note in result["limitations"] if not note.startswith("101号")
        ]
        result["limitations"].append(
            "008/019/030/034的累计、方差比和多层截面排序采用十进制输入的有理数计算，保持精确并列；完整依赖窗口内所有声明字段均须有效。"
        )
        if spec.number == 34:
            result["limitations"].append(
                "收益为相邻收盘价简单收益；标准差使用样本口径ddof=1。对非负标准差比的排序等价于方差比排序，采用后者避免开方舍入制造非并列；长窗口方差为0时留空。"
            )
        if spec.number == 30:
            result["limitations"].append(
                "零成交量允许输入；长窗口累计量为0时分母无定义，留空。方向窗口可配置，默认累计连续3次价格变化的符号。"
            )
    if spec.number == 14:
        result["reference_differences"] = [
            "固定 DolphinDB 参考代码 WQAlpha14 使用 mcovar，但其公式注释与原论文 Alpha#14 "
            "均指定 correlation；本地按公式计算 Pearson 相关系数，不采用协方差。"
        ]
        result["limitations"].extend(result["reference_differences"])
    if spec.number == 18:
        result["parameters"]["body_std"]["label"] = "实体标准差窗口"
        result["limitations"].append(
            "Alpha018 明确使用5根实体样本标准差、10根相关；GTJA054 的省略窗口默认10根。"
            "二者默认配置不同，仅参数调成一致时视为同义。"
        )
    if spec.number == 3:
        result["parameter_family"] = "gtja191:" + GTJA_SPECS[105].family
        result["parameter_aliases"] = {"window": "corr"}
        result["limitations"].append(
            "与 GTJA191 105 公式同义；为兼容旧原档，保留首批缩放相关的近常数判定实现。"
        )
    if spec.number in {10, 49, 51}:
        result["warmup_terms"] = [
            {"offset": 1, "windows": ["window"] * (2 if spec.number in {49, 51} else 1)}
        ]
    if spec.threshold is not None and spec.number in {49, 51}:
        result["parameter_family"] = "alpha101_price_curvature_threshold"
        result["resolved_parameters"]["threshold"] = spec.threshold
        result["parameters"]["threshold"] = {
            "default": cls.spec.threshold,
            "value": spec.threshold,
            "editable": True,
            "min": -10,
            "max": 0,
            "integer": False,
            "step": 0.01,
            "unit": "dimensionless",
            "label": "曲率阈值",
        }
        result["warmup_limit"] = 600
        result["limitations"].append(
            "49/51仅默认阈值不同；曲率阈值使用原价格单位/根，并非百分比，对价格单位与复权敏感。严格小于才切换。"
        )
        result["parameters"]["threshold"]["unit"] = "价格单位/根"
    if spec.number == 24:
        result["resolved_parameters"]["threshold"] = spec.threshold
        result["parameters"]["threshold"] = {
            "default": cls.spec.threshold,
            "value": spec.threshold,
            "editable": True,
            "min": -1,
            "max": 1,
            "integer": False,
            "step": 0.001,
            "unit": "dimensionless",
            "label": "均价变化比例阈值",
        }
        result["limitations"].append(
            "024阈值0.05代表5%，比较的是均价变化/滞后收盘价，不是收益率均值。等于阈值也进入距低点分支；全部分支依赖预热完成后才输出，精确十进制比例比较不加容差。"
        )
    if spec.number == 27:
        result["parameter_family"] = "alpha101_027"
        result["resolved_parameters"]["threshold"] = spec.threshold
        result["parameters"]["threshold"] = {
            "default": cls.spec.threshold,
            "value": spec.threshold,
            "editable": True,
            "min": 0,
            "max": 1,
            "integer": False,
            "step": 0.01,
            "unit": "dimensionless",
            "label": "截面排名阈值",
        }
        result["limitations"].append(
            "027复用GTJA036的排名相关累计内核，再独立按排名阈值输出；均值除以正窗口不改变截面排序。严格大于阈值才取−1，等于取1；任何无定义相关或不足排名保持缺失，不填1。与GTJA036不是同义定义。"
        )
    if spec.number == 5:
        result["limitations"].append(
            "005为abs(rank(close−vwap))，不是GTJA012的rank(abs(close−vwap))。本App排名始终为正，绝对值不改变排名结果。均价和偏离采用精确十进制有理数保持并列。VWAP仅使用合格不复权值。"
        )
    if spec.number == 52:
        result["reference_differences"] = [
            "原论文及固定模块注释均为240根收益累计减20根收益累计，参考函数体却减220根；本App按原文240／20执行，不沿用函数体差异。"
        ]
        result["limitations"].extend(result["reference_differences"])
        result["limitations"].append(
            "自定义窗口保留长收益累计减短收益累计、再除长短差；严格要求short<long。完整依赖内low不得高于close；收益累计、低点差和排名采用精确十进制有理数。"
        )
    if spec.number in {32, 57, 60}:
        result["limitations"].append(
            "截面scale分别按本项同日有效值的绝对值总和归一化，至少2个有效标的；全零总和保持缺失。完整依赖内缺失不跳过，各项先独立运算再相加，不用最终交集重新归一化。"
        )
    if spec.number in {57, 60}:
        result["limitations"].append(
            "ts_argmax是窗口从旧到新的0起始位置，并列取最早一次，遵循参考mimax的方向及并列约定；不是距离今天的根数，更不是最高价。原文未明确并列政策，本App在此明示。缺失窗口不按参考默认行为跳过。"
        )
    if spec.number == 57:
        result["limitations"].append(
            "线性衰减权重从最旧1到最新decay，除权重总和；每个历史日先用该日有效股票池计算极值位置排名，再完整衰减。与GTJA124最高价格排名不同义。"
        )
    if spec.number == 60:
        result["limitations"].append(
            "当前high=low时量价比无定义，第一项不参与该日排名，不填零；第二项仍独立计算。"
        )
    if spec.number == 54:
        result["limitations"].append(
            "54号以等价比率计算五次幂避免中间溢出；高低相等或最终结果超出浮点范围时留空。"
        )
    return result


for _spec in SPECS.values():
    register_factor(
        type(
            f"Alpha101{_spec.number:03d}",
            (Alpha101PanelFactor if _spec.panel else Alpha101Factor,),
            {
                "__module__": __name__,
                "name": f"alpha101_{_spec.number:03d}",
                "category": "volume" if "volume" in _spec.inputs else "technical",
                "description": _spec.title,
                "inputs": _spec.inputs,
                "spec": _spec,
            },
        )
    )
