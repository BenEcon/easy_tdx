"""Selected GTJA191 calculations, independently rewritten in NumPy/pandas.

Reference: DolphinDB's Apache-2.0 module, author DolphinDB, 2023-01-17;
see docs/licenses/dolphindb-Apache-2.0.txt and NOTICE. Changes: Python rewrite,
explicit complete windows/invalid inputs, average-tie percentile panel ranks,
configurable windows and provenance. Not a bit-identical DolphinDB port.
Original mathematical definitions checked against the 2017-06-15 report.
The report itself is not redistributed or relicensed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from fractions import Fraction
from math import fsum
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from easy_tdx.computation import computation_checkpoint
from easy_tdx.factor.base import Factor, PanelFactor, register_factor
from easy_tdx.factor.panel import FactorPanel, cross_section_rank, observation_index

VERSION = "gtja191-complete-window-v17"
SOURCE_COMMIT = "43ace2cc4b81d048864ec2e40c25728d5d464e05"
SOURCE = f"https://github.com/dolphindb/DolphinDBModules/blob/{SOURCE_COMMIT}/gtja191Alpha/src/gtja191Alpha.dos"
REPORT = "https://guorn.com/static/upload/file/3/134065454575605.pdf"


@dataclass(frozen=True)
class Window:
    key: str
    value: int
    label: str
    minimum: int = 1
    unit: str = "bars"


@dataclass(frozen=True)
class Spec:
    number: int
    family: str
    title: str
    inputs: tuple[str, ...]
    window: int | None
    formula: str
    multiplier: int = 1
    offset: int = 0
    panel: bool = False
    windows: tuple[Window, ...] = ()
    # Maximum of dependency paths: offset + sum(named windows), not eval(code).
    warmup_terms: tuple[tuple[int, tuple[str, ...]], ...] = ()
    recursive: bool = False

    @property
    def warmup(self) -> int:
        if self.warmup_terms:
            values = self.resolved_parameters
            return max(offset + sum(values[k] for k in keys) for offset, keys in self.warmup_terms)
        return max(1, (self.window or 1) * self.multiplier + self.offset)

    @property
    def resolved_parameters(self) -> dict[str, int]:
        if self.windows:
            return {w.key: w.value for w in self.windows}
        return {"window": self.window} if self.window is not None else {}


# C/O/H/L = same-adjustment prices; V = independently qualified shares.
# These descriptions are our concise algebraic notation, not a report table copy.
SPECS: dict[int, Spec] = {}


def _add(
    numbers: dict[int, int | None],
    family: str,
    title: str,
    inputs: tuple[str, ...],
    formula: str,
    *,
    offset: int = 0,
    multiplier: int = 1,
    panel: bool = False,
) -> None:
    for number, window in numbers.items():
        SPECS[number] = Spec(
            number, family, title, inputs, window, formula, multiplier, offset, panel
        )


_add(
    {2: 1},
    "location_delta",
    "收盘位置变化",
    ("close", "high", "low"),
    "位置=(2C−H−L)/(H−L)；输出 w 根前位置−当前位置",
    offset=1,
)
_add(
    {3: 6, 59: 20},
    "buy_pressure",
    "涨跌价格压力和",
    ("close", "high", "low"),
    "持平贡献0；涨时 C−min(L,前收)，跌时 C−max(H,前收)；累计 w 根",
    offset=1,
)
_add(
    {6: 4},
    "rank_weighted_delta",
    "加权价格变动截面排名",
    ("open", "high"),
    "负的截面排名：sign((0.85O+0.15H)−w 根前同值)",
    offset=1,
    panel=True,
)
_add(
    {11: 6, 60: 20},
    "flow_sum",
    "收盘位置量能和",
    ("close", "high", "low", "volume"),
    "累计 w 根：(2C−H−L)/(H−L) × V",
)
_add({14: 5, 106: 20}, "price_delta", "收盘价格差", ("close",), "C−w 根前 C", offset=1)
_add({15: 1}, "open_gap", "开盘相对前收", ("open", "close"), "O/(w 根前 C)−1", offset=1)
_add({18: 5}, "price_ratio", "收盘价格比", ("close",), "C/(w 根前 C)", offset=1)
_add(
    {19: 5},
    "asymmetric_return",
    "对称价格尺度涨跌",
    ("close",),
    "(C−w 根前 C)/max(C,w 根前 C)",
    offset=1,
)
_add(
    {20: 6, 88: 20}, "return_pct", "区间涨跌百分数", ("close",), "100 × (C/(w 根前 C)−1)", offset=1
)
_add(
    {29: 6, 134: 12, 178: 1},
    "volume_return",
    "量加权区间收益",
    ("close", "volume"),
    "(C/(w 根前 C)−1) × V",
    offset=1,
)
_add(
    {31: 12, 66: 6, 71: 24},
    "deviation_pct",
    "收盘均价偏离百分数",
    ("close",),
    "100 × (C/mean_w(C)−1)",
)
_add({34: 12, 65: 6}, "mean_ratio", "均价收盘比", ("close",), "mean_w(C)/C")
_add(
    {43: 6, 84: 20, 94: 30},
    "signed_volume",
    "涨跌方向成交量和",
    ("close", "volume"),
    "累计 w 根：sign(C−前收) × V",
    offset=1,
)
_add(
    {46: 3},
    "four_mean_ratio",
    "四均线收盘比",
    ("close",),
    "mean(mean_w(C),mean_2w(C),mean_4w(C),mean_8w(C))/C",
    multiplier=8,
)
_add(
    {53: 12, 58: 20},
    "up_count_pct",
    "上涨周期百分比",
    ("close",),
    "100 × 最近 w 根 C>前收 的次数 / w",
    offset=1,
)
_add(
    {80: 5},
    "volume_change_pct",
    "成交量变动百分数",
    ("volume",),
    "100 × (V/(w 根前 V)−1)",
    offset=1,
)
_add(
    {97: 10, 100: 20},
    "volume_std",
    "成交量标准差",
    ("volume",),
    "最近 w 根 V 的样本标准差（ddof=1）",
)
_add(
    {110: 20},
    "range_pressure",
    "高低价相对前收压力比",
    ("close", "high", "low"),
    "100 × sum_w(max(H−前收,0))/sum_w(max(前收−L,0))",
    offset=1,
)
_add(
    {118: 20},
    "open_pressure",
    "高低价相对开盘压力比",
    ("open", "high", "low"),
    "100 × sum_w(H−O)/sum_w(O−L)",
)
_add({126: None}, "typical_price", "三价均值", ("close", "high", "low"), "(C+H+L)/3")
_add({129: 12}, "down_sum", "下跌价格幅度和", ("close",), "sum_w(max(前收−C,0))", offset=1)
_add(
    {150: None},
    "typical_volume",
    "三价均值乘成交量",
    ("close", "high", "low", "volume"),
    "(C+H+L)/3 × V；不是实际成交额",
)
_add(
    {153: 3},
    "four_mean",
    "四均线均值",
    ("close",),
    "mean(mean_w(C),mean_2w(C),mean_4w(C),mean_8w(C))",
    multiplier=8,
)
_add(
    {161: 12, 175: 6},
    "true_range_mean",
    "真实波幅均值",
    ("close", "high", "low"),
    "mean_w(max(H−L,abs(H−前收),abs(L−前收)))",
    offset=1,
)
_add({167: 12}, "up_sum", "上涨价格幅度和", ("close",), "sum_w(max(C−前收,0))", offset=1)
_add({168: 20}, "negative_volume_ratio", "负相对成交量", ("volume",), "−V/mean_w(V)")
_add(
    {185: None},
    "rank_body_square",
    "开收偏离平方截面排名",
    ("open", "close"),
    "截面排名：−(1−O/C)²",
    panel=True,
)
_add(
    {187: 20},
    "open_up_pressure",
    "开盘上行价格压力和",
    ("open", "high"),
    "O≤前开时贡献0，否则 max(H−O,O−前开)；累计 w 根",
    offset=1,
)
_add(
    {189: 6},
    "mean_abs_deviation",
    "均价绝对偏差均值",
    ("close",),
    "mean_w(abs(C−mean_w(C)))",
    multiplier=2,
    offset=-1,
)

_add(
    {21: 6, 147: 12},
    "mean_slope",
    "均价时间回归斜率",
    ("close",),
    "以 1…w 为自变量，对最近 w 个 mean_w(C) 做含截距 OLS，取斜率",
    multiplier=2,
    offset=-1,
)
_add(
    {40: 26},
    "up_down_volume_ratio",
    "涨跌成交量比",
    ("close", "volume"),
    "100 × sum_w(C>前收时V否则0) / sum_w(C≤前收时V否则0)",
    offset=1,
)
for _number, _family, _title, _output in (
    (49, "down_range_share", "下移幅度占比", "D/(U+D)"),
    (50, "range_direction_balance", "上下移幅度差占比", "(U−D)/(U+D)"),
    (51, "up_range_share", "上移幅度占比", "U/(U+D)"),
):
    _add(
        {_number: 12},
        _family,
        _title,
        ("high", "low"),
        f"幅度=max(|ΔH|,|ΔL|)；H+L 上移计入 U，下移计入 D，持平不计；累计 w 根后输出 {_output}",
        offset=1,
    )
_add(
    {52: 26},
    "typical_range_pressure",
    "前典型价多空压力比",
    ("close", "high", "low"),
    "T=(H+L+C)/3；100 × sum_w(max(H−前T,0))/sum_w(max(前T−L,0))",
    offset=1,
)
_add(
    {69: 20},
    "open_pressure_balance",
    "开盘多空压力差",
    ("open", "high", "low"),
    "开盘上涨贡献 max(H−O,ΔO) 累计为 U，下跌贡献 max(O−L,ΔO) 累计为 D；"
    "U=D 时0，否则 (U−D)/max(U,D)",
    offset=1,
)
_add(
    {76: 20},
    "volume_scaled_return_cv",
    "量缩放收益变异系数",
    ("close", "volume"),
    "R=|C/前C−1|/V；std_w(R,ddof=1)/mean_w(R)",
    offset=1,
)
_add(
    {86: 10},
    "price_acceleration_switch",
    "价格加速度条件反转",
    ("close",),
    "A=(C[t−2w]−2C[t−w]+C[t])/w；A>0.25 时−1，A<0 时1，否则−ΔC",
    multiplier=2,
    offset=1,
)
_add(
    {93: 20},
    "open_down_pressure",
    "开盘下行价格压力和",
    ("open", "low"),
    "O≥前开时0，否则 max(O−L,O−前开)；累计 w 根",
    offset=1,
)
_add(
    {103: 20},
    "low_recency",
    "窗口低点接近度",
    ("low",),
    "100 × (w−距最近最低点根数)/w；当根最低距离0，并列取最近者",
)
_add(
    {112: 12},
    "price_direction_balance",
    "涨跌幅度差占比",
    ("close",),
    "100 × (sum_w(max(ΔC,0))−sum_w(max(−ΔC,0)))/sum_w(|ΔC|)",
    offset=1,
)
_add(
    {116: 20},
    "price_slope",
    "价格时间回归斜率",
    ("close",),
    "以 1…w 为自变量，对最近 w 个 C 做含截距 OLS，取斜率",
)
_add(
    {127: 12},
    "peak_deviation_rms",
    "滚动峰值偏离均方根",
    ("close",),
    "sqrt(mean_w((100 × (C/max_w(C)−1))²))；外层均值采用同一 w",
    multiplier=2,
    offset=-1,
)
_add(
    {128: 14},
    "typical_money_flow",
    "典型价量流强度",
    ("close", "high", "low", "volume"),
    "T=(H+L+C)/3；上涨 T×V 累计 U，下跌累计 D；100−100/(1+U/D)，D=0 缺失",
    offset=1,
)
_add(
    {133: 20},
    "extreme_recency_balance",
    "高低点接近度差",
    ("high", "low"),
    "100 × (距最近最低点根数−距最近最高点根数)/w；并列取最近者",
)
_add(
    {139: 10},
    "negative_open_volume_corr",
    "开盘成交量负相关",
    ("open", "volume"),
    "−corr_w(O,V)；窗口内任一序列为常数时缺失",
)
_add(
    {158: None},
    "range_close_ratio",
    "振幅收盘比",
    ("close", "high", "low"),
    "(H−L)/C；原式中两项相同 SMA(C,15,2) 代数消去，无额外平滑预热",
)
_add(
    {171: None},
    "body_range_power",
    "开收五次比幅度",
    ("open", "close", "high", "low"),
    "−(L−C)/(C−H) × (O/C)^5；C=H 时缺失",
)
_add(
    {177: 20},
    "high_recency",
    "窗口高点接近度",
    ("high",),
    "100 × (w−距最近最高点根数)/w；当根最高距离0，并列取最近者",
)
_add(
    {191: 20},
    "volume_mean_low_corr",
    "均量低价相关价差",
    ("close", "high", "low", "volume"),
    "corr_5(mean_w(V),L)+(H+L)/2−C；相关窗口固定5根",
    offset=4,
)


_add(
    {9: 7, 68: 15},
    "sma_midpoint_pressure",
    "中间价量能压力平滑",
    ("high", "low", "volume"),
    "SMA(中间价单根变化×(H−L)/V,w,2)",
    offset=1,
)
_add(
    {24: 5, 151: 20},
    "sma_price_change",
    "价格差递归平滑",
    ("close",),
    "SMA(C−w根前C,w,1)；差值距离与平滑窗口同步",
    multiplier=2,
)
_add(
    {47: 9, 72: 15, 82: 20},
    "sma_high_distance",
    "区间高点距离平滑",
    ("close", "high", "low"),
    "SMA(100×(max_6(H)−C)/(max_6(H)−min_6(L)),w,1)；区间固定6根",
    offset=5,
)
_add(
    {57: 3},
    "sma_stochastic",
    "区间收盘位置平滑",
    ("close", "high", "low"),
    "SMA(100×(C−min_9(L))/(max_9(H)−min_9(L)),w,1)；区间固定9根",
    offset=8,
)
_add(
    {96: 3},
    "sma_double_stochastic",
    "区间收盘位置双重平滑",
    ("close", "high", "low"),
    "SMA(SMA(100×(C−min_9(L))/(max_9(H)−min_9(L)),w,1),w,1)",
    multiplier=2,
    offset=7,
)
_add(
    {63: 6, 67: 24, 79: 12},
    "sma_price_strength",
    "价格变动平滑强弱",
    ("close",),
    "100×SMA(max(ΔC,0),w,1)/SMA(abs(ΔC),w,1)",
    offset=1,
)
_add({81: 21}, "sma_volume", "成交量递归平滑", ("volume",), "SMA(V,w,2)")
_add(
    {102: 6},
    "sma_volume_strength",
    "成交量变动平滑强弱",
    ("volume",),
    "100×SMA(max(ΔV,0),w,1)/SMA(abs(ΔV),w,1)",
    offset=1,
)
_add(
    {109: 10},
    "sma_range_ratio",
    "区间幅度双重平滑比",
    ("high", "low"),
    "SMA(H−L,w,2)/SMA(SMA(H−L,w,2),w,2)",
    multiplier=2,
    offset=-1,
)
_add(
    {122: 13},
    "sma_log_rate",
    "对数价格三重平滑变化率",
    ("close",),
    "T=SMA(SMA(SMA(log(C),w,2),w,2),w,2)；T/前T−1",
    multiplier=3,
    offset=-1,
)
_add(
    {135: 20},
    "sma_lagged_price_ratio",
    "滞后价格比平滑",
    ("close",),
    "SMA(前一根的C/(w根前C),w,1)",
    multiplier=2,
    offset=1,
)
_add(
    {160: 20},
    "sma_down_volatility",
    "非上涨波动平滑",
    ("close",),
    "SMA(C≤前C时取std_w(C)，否则0,w,1)",
    multiplier=2,
    offset=-1,
)
_add(
    {174: 20},
    "sma_up_volatility",
    "上涨波动平滑",
    ("close",),
    "SMA(C>前C时取std_w(C)，否则0,w,1)",
    multiplier=2,
    offset=-1,
)
_add(
    {173: 13},
    "sma_price_log_mix",
    "价格与对数价格平滑组合",
    ("close",),
    "3×SMA(C,w,2)−2×SMA(SMA(C,w,2),w,2)+SMA(SMA(SMA(log(C),w,2),w,2),w,2)",
    multiplier=3,
    offset=-2,
)
_add(
    {188: 11},
    "sma_range_bias",
    "区间幅度平滑偏离",
    ("high", "low"),
    "100×((H−L)/SMA(H−L,w,2)−1)",
)


def _compound(
    number: int,
    title: str,
    inputs: tuple[str, ...],
    formula: str,
    windows: tuple[Window, ...],
    paths: tuple[tuple[int, tuple[str, ...]], ...],
    *,
    recursive: bool = False,
    panel: bool = False,
) -> None:
    SPECS[number] = Spec(
        number,
        f"panel_{number:03d}" if panel else f"compound_{number:03d}",
        title,
        inputs,
        None,
        formula,
        windows=windows,
        warmup_terms=paths,
        recursive=recursive,
        panel=panel,
    )


_compound(
    27,
    "双窗口收益指数加权",
    ("close",),
    "X=100×(C/前short根C−1+C/前long根C−1)；最近window根按距今i的0.9^i归一加权",
    (
        Window("short", 3, "短收益窗口"),
        Window("long", 6, "长收益窗口"),
        Window("window", 12, "加权窗口"),
    ),
    ((0, ("long", "window")),),
)
_compound(
    85,
    "相对量与反向动量时序排名",
    ("close", "volume"),
    "TSRANK(V/mean_volume_mean(V),volume_rank)×TSRANK(−diff_price_lag(C),price_rank)",
    (
        Window("volume_mean", 20, "量均值窗口"),
        Window("volume_rank", 20, "量排名窗口"),
        Window("price_lag", 7, "价格差间隔"),
        Window("price_rank", 8, "价格排名窗口"),
    ),
    ((-1, ("volume_mean", "volume_rank")), (0, ("price_lag", "price_rank"))),
)
for _number, _field, _title in ((89, "close", "价格双平滑差离"), (155, "volume", "量双平滑差离")):
    _compound(
        _number,
        _title,
        (_field,),
        f"X={'C' if _number == 89 else 'V'}；D=SMA(X,short,2)−SMA(X,long,2)；"
        + ("2×" if _number == 89 else "")
        + "(D−SMA(D,signal,2))",
        (
            Window("short", 13, "短平滑窗口", 2),
            Window("long", 27, "长平滑窗口", 2),
            Window("signal", 10, "差值平滑窗口", 2),
        ),
        ((-1, ("long", "signal")),),
        recursive=True,
    )
_compound(
    111,
    "量价位置双平滑差",
    ("close", "high", "low", "volume"),
    "X=V×(2C−H−L)/(H−L)；SMA(X,long,2)−SMA(X,short,2)",
    (Window("short", 4, "短平滑窗口", 2), Window("long", 11, "长平滑窗口", 2)),
    ((0, ("long",)),),
    recursive=True,
)
_compound(
    117,
    "量价收益三时序排名",
    ("close", "high", "low", "volume"),
    "TSRANK(V,volume_rank)×(1−TSRANK(C+H−L,price_rank))×(1−TSRANK(C/前C−1,return_rank))",
    (
        Window("volume_rank", 32, "量排名窗口"),
        Window("price_rank", 16, "价格排名窗口"),
        Window("return_rank", 32, "收益排名窗口"),
    ),
    ((0, ("volume_rank",)), (0, ("price_rank",)), (1, ("return_rank",))),
)
_compound(
    145,
    "成交量双均值差比",
    ("volume",),
    "100×(mean_short(V)−mean_long(V))/mean_scale_window(V)",
    (
        Window("short", 9, "短均值窗口"),
        Window("long", 26, "长均值窗口"),
        Window("scale_window", 12, "分母均值窗口"),
    ),
    ((0, ("long",)), (0, ("scale_window",))),
)
_compound(
    152,
    "滞后价格比复合平滑",
    ("close",),
    "X=delay(SMA(delay(C/delay(C,lag),1),smooth,1),1)；SMA(mean_short(X)−mean_long(X),signal,1)",
    (
        Window("lag", 9, "价格比间隔"),
        Window("smooth", 9, "价格比平滑窗口"),
        Window("short", 12, "短均值窗口"),
        Window("long", 26, "长均值窗口"),
        Window("signal", 9, "差值平滑窗口"),
    ),
    ((0, ("lag", "smooth", "long", "signal")),),
    recursive=True,
)
_compound(
    162,
    "平滑强弱区间位置",
    ("close",),
    "R=100×SMA(max(diff(C),0),smooth,1)/SMA(abs(diff(C)),smooth,1)；"
    "(R−min_lookback(R))/(max_lookback(R)−min_lookback(R))",
    (Window("smooth", 12, "强弱平滑窗口"), Window("lookback", 12, "区间窗口")),
    ((0, ("smooth", "lookback")),),
    recursive=True,
)
_compound(
    164,
    "上行倒数区间平滑",
    ("close", "high", "low"),
    "X=diff(C)>0时取1/diff(C)，否则1；SMA(100×(X−min_lookback(X))/(H−L),smooth,2)",
    (Window("lookback", 12, "倒数极值窗口"), Window("smooth", 13, "平滑窗口", 2)),
    ((0, ("lookback", "smooth")),),
    recursive=True,
)
_compound(
    169,
    "价格差复合平滑",
    ("close",),
    "X=delay(SMA(diff(C),smooth,1),1)；SMA(mean_short(X)−mean_long(X),signal,1)",
    (
        Window("smooth", 9, "价格差平滑窗口"),
        Window("short", 12, "短均值窗口"),
        Window("long", 26, "长均值窗口"),
        Window("signal", 10, "差值平滑窗口"),
    ),
    ((0, ("smooth", "long", "signal")),),
    recursive=True,
)
_compound(
    180,
    "放量动量时序排名切换",
    ("close", "volume"),
    "V>mean_volume_mean(V)时取−TSRANK(abs(diff_price_lag(C)),price_rank)×sign(diff_price_lag(C))，否则−V",
    (
        Window("volume_mean", 20, "量均值窗口"),
        Window("price_lag", 7, "价格差间隔"),
        Window("price_rank", 60, "价格排名窗口"),
    ),
    ((0, ("volume_mean",)), (0, ("price_lag", "price_rank"))),
)


# R is a same-observation cross-section; T is a per-symbol trailing rank.
_compound(
    1,
    "量变与实体收益排名相关",
    ("open", "close", "volume"),
    "−corr_corr(R(diff_lag(log(V))),R((C−O)/O))",
    (Window("lag", 1, "量变间隔"), Window("corr", 6, "相关窗口", 2)),
    ((0, ("lag", "corr")),),
    panel=True,
)
_compound(
    10,
    "收益条件波动极大值排名",
    ("close",),
    "R(max_peak((RET<0 ? std_volatility(RET) : C)^2))；RET=C/前C−1",
    (Window("volatility", 20, "波动窗口", 2), Window("peak", 5, "极大值窗口")),
    ((0, ("volatility", "peak")),),
    panel=True,
)
_compound(
    32,
    "价量排名相关累计",
    ("high", "volume"),
    "−sum_sum(R(corr_corr(R(H),R(V))))",
    (Window("corr", 3, "相关窗口", 2), Window("sum", 3, "累计窗口")),
    ((-1, ("corr", "sum")),),
    panel=True,
)
_compound(
    37,
    "开盘收益累计差排名",
    ("open", "close"),
    "−R(diff_lag(sum_sum(O)×sum_sum(RET)))",
    (Window("sum", 5, "累计窗口"), Window("lag", 10, "比较间隔")),
    ((1, ("sum", "lag")),),
    panel=True,
)
_compound(
    42,
    "高价波动排名与量价相关",
    ("high", "volume"),
    "−R(std_volatility(H))×corr_corr(H,V)",
    (Window("volatility", 10, "波动窗口", 2), Window("corr", 10, "相关窗口", 2)),
    ((0, ("volatility",)), (0, ("corr",))),
    panel=True,
)
_compound(
    48,
    "连续方向排名与量比",
    ("close", "volume"),
    "−R(sum_direction(sign(diff(C))))×sum_short(V)/sum_long(V)",
    (
        Window("direction", 3, "方向累计窗口"),
        Window("short", 5, "短量窗口"),
        Window("long", 20, "长量窗口"),
    ),
    ((1, ("direction",)), (0, ("long",))),
    panel=True,
)
_compound(
    62,
    "高价与量排名负相关",
    ("high", "volume"),
    "−corr_corr(H,R(V))",
    (Window("corr", 5, "相关窗口", 2),),
    ((0, ("corr",)),),
    panel=True,
)
for _number, _price, _title in ((83, "high", "高价"), (99, "close", "收盘")):
    _compound(
        _number,
        f"{_title}与量排名协方差",
        (_price, "volume"),
        f"−R(cov_covariance(R({'H' if _price == 'high' else 'C'}),R(V)))；样本协方差ddof=1",
        (Window("covariance", 5, "协方差窗口", 2),),
        ((0, ("covariance",)),),
        panel=True,
    )
_compound(
    91,
    "高点距离与均量低价相关排名",
    ("close", "low", "volume"),
    "−R(C−max_peak(C))×R(corr_corr(mean_volume_mean(V),L))",
    (
        Window("peak", 5, "高点窗口"),
        Window("volume_mean", 40, "均量窗口"),
        Window("corr", 5, "相关窗口", 2),
    ),
    ((0, ("peak",)), (-1, ("volume_mean", "corr"))),
    panel=True,
)
_compound(
    104,
    "量价相关变化与波动排名",
    ("high", "close", "volume"),
    "−diff_lag(corr_corr(H,V))×R(std_volatility(C))",
    (
        Window("corr", 5, "相关窗口", 2),
        Window("lag", 5, "变化间隔"),
        Window("volatility", 20, "波动窗口", 2),
    ),
    ((0, ("corr", "lag")), (0, ("volatility",))),
    panel=True,
)
_compound(
    105,
    "开盘量排名负相关",
    ("open", "volume"),
    "−corr_corr(R(O),R(V))",
    (Window("corr", 10, "相关窗口", 2),),
    ((0, ("corr",)),),
    panel=True,
)
_compound(
    107,
    "开盘相对前价三重排名",
    ("open", "high", "close", "low"),
    "−R(O−delay_lag(H))×R(O−delay_lag(C))×R(O−delay_lag(L))",
    (Window("lag", 1, "前价间隔"),),
    ((1, ("lag",)),),
    panel=True,
)
_compound(
    113,
    "滞后均价排名与双相关",
    ("close", "volume"),
    "−R(mean_mean(delay_lag(C)))×corr_corr(C,V)×R(corr_corr(sum_short(C),sum_long(C)))",
    (
        Window("lag", 5, "均价滞后"),
        Window("mean", 20, "均价窗口"),
        Window("corr", 2, "相关窗口", 2),
        Window("short", 5, "短累计窗口"),
        Window("long", 20, "长累计窗口"),
    ),
    ((0, ("lag", "mean")), (-1, ("long", "corr"))),
    panel=True,
)
_compound(
    115,
    "量价相关排名幂",
    ("high", "low", "close", "volume"),
    "R(corr_corr(0.9H+0.1C,mean_volume_mean(V))) ^ "
    "R(corr_rank_corr(T_price_rank((H+L)/2),T_volume_rank(V)))",
    (
        Window("corr", 10, "价量相关窗口", 2),
        Window("volume_mean", 30, "均量窗口"),
        Window("price_rank", 4, "价格时序排名"),
        Window("volume_rank", 10, "量时序排名"),
        Window("rank_corr", 7, "排名相关窗口", 2),
    ),
    (
        (-1, ("corr", "volume_mean")),
        (-1, ("price_rank", "rank_corr")),
        (-1, ("volume_rank", "rank_corr")),
    ),
    panel=True,
)
_compound(
    136,
    "收益变化排名与开盘量相关",
    ("open", "close", "volume"),
    "−R(diff_lag(RET))×corr_corr(O,V)",
    (Window("lag", 3, "收益变化间隔"), Window("corr", 10, "相关窗口", 2)),
    ((2, ("lag",)), (0, ("corr",))),
    panel=True,
)
_compound(
    142,
    "价格与相对量多层排名",
    ("close", "volume"),
    "−R(T_price_rank(C))×R(diff_lag(diff_lag(C)))×R(T_volume_rank(V/mean_volume_mean(V)))",
    (
        Window("price_rank", 10, "价格时序排名"),
        Window("lag", 1, "二阶差分间隔"),
        Window("volume_mean", 20, "均量窗口"),
        Window("volume_rank", 5, "量时序排名"),
    ),
    ((0, ("price_rank",)), (1, ("lag", "lag")), (-1, ("volume_mean", "volume_rank"))),
    panel=True,
)
_compound(
    148,
    "均量相关与开盘低点排名比较",
    ("open", "volume"),
    "−1×[R(corr_corr(O,sum_sum(mean_volume_mean(V)))) < R(O−min_trough(O))]；缺失不记为0",
    (
        Window("volume_mean", 60, "均量窗口"),
        Window("sum", 9, "均量累计窗口"),
        Window("corr", 6, "相关窗口", 2),
        Window("trough", 14, "低点窗口"),
    ),
    ((-2, ("volume_mean", "sum", "corr")), (0, ("trough",))),
    panel=True,
)
_compound(
    176,
    "区间位置与量排名相关",
    ("close", "high", "low", "volume"),
    "corr_corr(R((C−min_range(L))/(max_range(H)−min_range(L))),R(V))",
    (Window("range", 12, "区间窗口"), Window("corr", 6, "相关窗口", 2)),
    ((-1, ("range", "corr")),),
    panel=True,
)
_compound(
    184,
    "滞后实体相关与实体排名",
    ("open", "close"),
    "R(corr_corr(delay_lag(O−C),C))+R(O−C)",
    (Window("lag", 1, "实体滞后"), Window("corr", 200, "相关窗口", 2)),
    ((0, ("lag", "corr")),),
    panel=True,
)


_compound(
    4,
    "均价波动与量能条件",
    ("close", "volume"),
    "均价快速突破均价带时输出−1／1；否则V≥mean_volume_mean(V)为1，否则−1",
    (
        Window("mean", 8, "均价与样本波动窗口", 2),
        Window("fast", 2, "快速均价窗口"),
        Window("volume_mean", 20, "成交量均值窗口"),
    ),
    ((0, ("mean",)), (0, ("fast",)), (0, ("volume_mean",))),
)
_compound(
    5,
    "量价时序排名相关峰值",
    ("high", "volume"),
    "−max_peak(corr_corr(TSRANK(V,rank),TSRANK(H,rank)))",
    (
        Window("rank", 5, "时序排名窗口", 2),
        Window("corr", 5, "相关窗口", 2),
        Window("peak", 3, "相关峰值窗口"),
    ),
    ((-2, ("rank", "corr", "peak")),),
)
_compound(
    22,
    "均价偏离差平滑",
    ("close",),
    "X=(C−mean_mean(C))/mean_mean(C)；SMA(X−delay_lag(X),smooth,1)",
    (
        Window("mean", 6, "均价窗口"),
        Window("lag", 3, "偏离差间隔"),
        Window("smooth", 12, "平滑窗口"),
    ),
    ((-1, ("mean", "lag", "smooth")),),
    recursive=True,
)
_compound(
    23,
    "上涨条件波动占比",
    ("close",),
    "S=std_std(C)；U=SMA(C>前收?S:0,smooth,1)，D=SMA(C≤前收?S:0,smooth,1)；100U/(U+D)",
    (Window("std", 20, "样本波动窗口", 2), Window("smooth", 20, "平滑窗口")),
    ((-1, ("std", "smooth")),),
    recursive=True,
)
_compound(
    38,
    "高价突破条件变化",
    ("high",),
    "H>mean_mean(H)时输出−diff_lag(H)，否则0；两分支均等待完整窗口",
    (Window("mean", 20, "高价均值窗口"), Window("lag", 2, "高价变化间隔")),
    ((0, ("mean",)), (1, ("lag",))),
)
for _n, _w in ((70, 6), (95, 20), (132, 20)):
    _compound(
        _n,
        "实际成交额均值" if _n == 132 else "实际成交额样本波动",
        ("amount",),
        "mean_window(AMOUNT)" if _n == 132 else "std_window(AMOUNT)，样本口径ddof=1",
        (Window("window", _w, "成交额窗口", 1 if _n == 132 else 2),),
        ((0, ("window",)),),
    )
_compound(
    78,
    "典型价收盘偏差强度",
    ("close", "high", "low"),
    "T=(C+H+L)/3，M=mean_mean(T)；(T−M)/(0.015×mean_deviation(|C−M|))",
    (Window("mean", 12, "典型价均值窗口"), Window("deviation", 12, "收盘偏差均值窗口")),
    ((-1, ("mean", "deviation")),),
)
_compound(
    98,
    "长期均价条件反向价格差",
    ("close",),
    "diff_lag(mean_mean(C))/delay_lag(C)≤0.05时−(C−min_trough(C))，否则−diff_change(C)",
    (
        Window("mean", 100, "长期均价窗口"),
        Window("lag", 100, "均价变化间隔"),
        Window("trough", 100, "低点窗口"),
        Window("change", 3, "反向价格差间隔"),
    ),
    ((0, ("mean", "lag")), (0, ("trough",)), (1, ("change",))),
)
for _n in (55, 137):
    _compound(
        _n,
        "条件价格压力累计" if _n == 55 else "条件价格压力",
        ("open", "close", "high", "low"),
        "P=delay_lag(C)，Q=delay_lag(O)，R=delay_lag(L)；a=|H−P|，b=|L−P|，d=|H−R|；"
        "D=a+b/2+|P−Q|/4（a>b且a>d），或b+a/2+|P−Q|/4（b>d且b>a），否则d+|P−Q|/4；"
        "X=16×(C−P+(C−O)/2+P−Q)×max(a,b)/D；" + ("sum_window(X)" if _n == 55 else "输出X"),
        (Window("lag", 1, "前值间隔"),)
        + ((Window("window", 20, "压力累计窗口"),) if _n == 55 else ()),
        ((0, ("lag", "window")),) if _n == 55 else ((1, ("lag",)),),
    )
_compound(
    144,
    "下跌日单位成交额振幅",
    ("close", "amount"),
    "最近window根中，C<前收的|C/前收−1|/AMOUNT之和，除以下跌根数；无下跌时为空",
    (Window("window", 20, "条件统计窗口"),),
    ((1, ("window",)),),
)
for _n in (172, 186):
    _compound(
        _n,
        "方向强度滞后均值" if _n == 186 else "价格方向强度",
        ("close", "high", "low"),
        "HD=H−前H，LD=前L−L；TR=max(H−L,|H−前收|,|L−前收|)；"
        "DI+=100sum_direction(HD>0且HD>LD?HD:0)/sum_direction(TR)，DI−对称；"
        "X=mean_smooth(100|DI+−DI−|/(DI++DI−))；"
        + ("(X+delay_lag(X))/2" if _n == 186 else "输出X"),
        (Window("direction", 14, "方向统计窗口"), Window("smooth", 6, "强度均值窗口"))
        + ((Window("lag", 6, "强度滞后间隔"),) if _n == 186 else ()),
        ((0, ("direction", "smooth", "lag")),) if _n == 186 else ((0, ("direction", "smooth")),),
    )


# W is qualified, unadjusted transaction VWAP, never a close/typical-price proxy.
_VWAP_WINDOWS = {
    "range": "区间窗口",
    "lag": "滞后根数",
    "mean": "均价窗口",
    "corr": "相关窗口",
    "peak": "最高值窗口",
    "sum": "累计窗口",
    "volume_mean": "均量窗口",
    "trough": "最低值窗口",
    "decay": "线性加权窗口",
    "rank": "时序排名窗口",
    "high_mean": "最高价均值窗口",
    "rank_corr": "排名相关窗口",
}


def _vwap_spec(
    number: int,
    title: str,
    inputs: tuple[str, ...],
    formula: str,
    windows: tuple[tuple[str, int], ...],
    paths: tuple[tuple[int, tuple[str, ...]], ...],
    *,
    panel: bool = True,
) -> None:
    _compound(
        number,
        title,
        inputs,
        formula,
        tuple(
            Window(k, v, _VWAP_WINDOWS[k], 2 if k in {"corr", "rank_corr"} else 1)
            for k, v in windows
        ),
        paths,
        panel=panel,
    )


_vwap_spec(
    7,
    "均价偏离区间与量变排名",
    ("vwap", "close", "volume"),
    "(R(max_range(W−C))+R(min_range(W−C)))×R(diff_lag(V))",
    (("range", 3), ("lag", 3)),
    ((0, ("range",)), (1, ("lag",))),
)
_vwap_spec(
    8,
    "混合均价反向变化排名",
    ("high", "low", "vwap"),
    "R(−diff_lag(0.2×(H+L)/2+0.8W))",
    (("lag", 4),),
    ((1, ("lag",)),),
)
_vwap_spec(
    12,
    "开盘与成交均价偏离排名",
    ("open", "close", "vwap"),
    "−R(O−mean_mean(W))×R(abs(C−W))",
    (("mean", 10),),
    ((0, ("mean",)),),
)
_vwap_spec(
    13,
    "高低几何均价与成交均价差",
    ("high", "low", "vwap"),
    "sqrt(H×L)−W",
    (),
    ((1, ()),),
    panel=False,
)
_vwap_spec(
    16,
    "量价排名相关峰值",
    ("volume", "vwap"),
    "−max_peak(R(corr_corr(R(V),R(W))))",
    (("corr", 5), ("peak", 5)),
    ((-1, ("corr", "peak")),),
)
_vwap_spec(
    17,
    "均价距峰排名的价格变化幂",
    ("vwap", "close"),
    "R(W−max_peak(W))^diff_lag(C)",
    (("peak", 15), ("lag", 5)),
    ((0, ("peak",)), (1, ("lag",))),
)
_vwap_spec(
    26,
    "均价偏离与滞后收盘相关",
    ("close", "vwap"),
    "mean_mean(C)−C+corr_corr(W,delay_lag(C))",
    (("mean", 7), ("lag", 5), ("corr", 230)),
    ((0, ("mean",)), (0, ("lag", "corr"))),
    panel=False,
)
_vwap_spec(
    36,
    "量价排名相关累积排名",
    ("volume", "vwap"),
    "R(sum_sum(corr_corr(R(V),R(W))))",
    (("corr", 6), ("sum", 2)),
    ((-1, ("corr", "sum")),),
)
_vwap_spec(
    41,
    "成交均价变化峰值反向排名",
    ("vwap",),
    "−R(max_peak(diff_lag(W)))",
    (("lag", 3), ("peak", 5)),
    ((0, ("lag", "peak")),),
)
_vwap_spec(
    45,
    "混合价格变化与量均价相关",
    ("close", "open", "vwap", "volume"),
    "R(diff_lag(0.6C+0.4O))×R(corr_corr(W,mean_volume_mean(V)))",
    (("lag", 1), ("volume_mean", 150), ("corr", 15)),
    ((1, ("lag",)), (-1, ("volume_mean", "corr"))),
)
_vwap_spec(
    90,
    "成交均价量排名相关反向排名",
    ("vwap", "volume"),
    "−R(corr_corr(R(W),R(V)))",
    (("corr", 5),),
    ((0, ("corr",)),),
)
_vwap_spec(
    108,
    "高价距谷排名的量价相关幂",
    ("high", "vwap", "volume"),
    "−R(H−min_trough(H))^R(corr_corr(W,mean_volume_mean(V)))",
    (("trough", 2), ("volume_mean", 120), ("corr", 6)),
    ((0, ("trough",)), (-1, ("volume_mean", "corr"))),
)
_vwap_spec(
    114,
    "相对振幅量排名与均价差",
    ("high", "low", "close", "volume", "vwap"),
    "X=(H−L)/mean_mean(C)；R(delay_lag(X))×R(R(V)) / (X/(W−C))",
    (("mean", 5), ("lag", 2)),
    ((0, ("mean", "lag")),),
)
_vwap_spec(120, "均价收盘差与和排名比", ("vwap", "close"), "R(W−C)/R(W+C)", (), ((1, ()),))
_vwap_spec(
    124,
    "收盘均价差与线性加权峰价排名",
    ("close", "vwap"),
    "(C−W)/DECAYLINEAR(R(max_peak(C)),decay)",
    (("peak", 30), ("decay", 2)),
    ((-1, ("peak", "decay")),),
)
_vwap_spec(
    131,
    "均价变化排名的量价相关时序幂",
    ("vwap", "close", "volume"),
    "R(diff_lag(W))^TSRANK(corr_corr(C,mean_volume_mean(V)),rank)",
    (("lag", 1), ("volume_mean", 50), ("corr", 18), ("rank", 18)),
    ((1, ("lag",)), (-2, ("volume_mean", "corr", "rank"))),
)
_vwap_spec(
    154,
    "均价距谷与量价相关比较",
    ("vwap", "volume"),
    "(W−min_trough(W)) < corr_corr(W,mean_volume_mean(V))；仅两侧有效时输出0/1",
    (("trough", 16), ("volume_mean", 180), ("corr", 18)),
    ((0, ("trough",)), (-1, ("volume_mean", "corr"))),
    panel=False,
)
_vwap_spec(
    163,
    "反向收益量均价与上影排名",
    ("close", "high", "volume", "vwap"),
    "R(−(C/前收−1)×mean_volume_mean(V)×W×(H−C))",
    (("volume_mean", 20),),
    ((2, ()), (0, ("volume_mean",))),
)
_vwap_spec(
    170,
    "逆价格量高价强度与均价变化",
    ("close", "high", "volume", "vwap"),
    "(R(1/C)×V/mean_volume_mean(V))×(H×R(H−C)/mean_high_mean(H))−R(W−delay_lag(W))",
    (("volume_mean", 20), ("high_mean", 5), ("lag", 5)),
    ((0, ("volume_mean",)), (0, ("high_mean",)), (1, ("lag",))),
)
_vwap_spec(
    179,
    "均价量相关与低价均量排名相关",
    ("vwap", "volume", "low"),
    "R(corr_corr(W,V))×R(corr_rank_corr(R(L),R(mean_volume_mean(V))))",
    (("corr", 4), ("volume_mean", 50), ("rank_corr", 12)),
    ((0, ("corr",)), (-1, ("volume_mean", "rank_corr"))),
)


_DECAY_LABELS = {
    "lag": "价格差分间隔",
    "price_decay": "价格线性加权窗口",
    "corr": "相关窗口",
    "corr_decay": "相关线性加权窗口",
    "volume_mean": "均量窗口",
    "ratio_decay": "比值线性加权窗口",
    "rank": "时序排名窗口",
    "mix_lag": "混合价格差分间隔",
    "mix_decay": "混合价格线性加权窗口",
}
for _n, _title, _inputs, _formula, _windows, _paths in (
    (
        35,
        "开盘变化与量价相关加权排名",
        ("open", "volume"),
        "−min(R(D_price_decay(diff_lag(O))),R(D_corr_decay(corr_corr(V,O))))；原式0.65O+0.35O合并为O",
        (("lag", 1), ("price_decay", 15), ("corr", 17), ("corr_decay", 7)),
        ((0, ("lag", "price_decay")), (-1, ("corr", "corr_decay"))),
    ),
    (
        61,
        "均价变化与低价均量相关加权排名",
        ("vwap", "low", "volume"),
        "−max(R(D_price_decay(diff_lag(W))),R(D_corr_decay(R(corr_corr(L,mean_volume_mean(V))))))",
        (("lag", 1), ("price_decay", 12), ("volume_mean", 80), ("corr", 8), ("corr_decay", 17)),
        ((0, ("lag", "price_decay")), (-2, ("volume_mean", "corr", "corr_decay"))),
    ),
    (
        87,
        "均价变化与开盘位置加权排名",
        ("vwap", "open", "high", "low"),
        "−R(D_price_decay(diff_lag(W)))−TSRANK_rank(D_ratio_decay((L−W)/(O−(H+L)/2)))；原式0.9L+0.1L合并为L",
        (("lag", 4), ("price_decay", 7), ("ratio_decay", 11), ("rank", 7)),
        ((0, ("lag", "price_decay")), (-1, ("ratio_decay", "rank"))),
    ),
    (
        92,
        "混合均价变化与量价相关强度",
        ("close", "vwap", "volume"),
        "−max(R(D_price_decay(diff_lag(0.35C+0.65W))),TSRANK_rank(D_corr_decay(abs(corr_corr(mean_volume_mean(V),C)))))",
        (
            ("lag", 2),
            ("price_decay", 3),
            ("volume_mean", 180),
            ("corr", 13),
            ("corr_decay", 5),
            ("rank", 15),
        ),
        ((0, ("lag", "price_decay")), (-3, ("volume_mean", "corr", "corr_decay", "rank"))),
    ),
    (
        156,
        "成交均价与混合低价变化排名",
        ("vwap", "open", "low"),
        "X=0.15O+0.85L；−max(R(D_price_decay(diff_lag(W))),R(D_mix_decay(−diff_mix_lag(X)/X)))",
        (("lag", 5), ("price_decay", 3), ("mix_lag", 2), ("mix_decay", 3)),
        ((0, ("lag", "price_decay")), (0, ("mix_lag", "mix_decay"))),
    ),
):
    _compound(
        _n,
        _title,
        _inputs,
        _formula + "；R为当期真实股票池排名；D为完整窗口内由旧至新1…w归一线性加权；"
        "min/max逐元素比较且任一缺失则缺失",
        tuple(Window(k, v, _DECAY_LABELS[k], 2 if k == "corr" else 1) for k, v in _windows),
        _paths,
        panel=True,
    )


_MULTISTAGE_LABELS = {
    "lag": "差分或滞后间隔",
    "volume_mean": "均量窗口",
    "volume_sum": "均量累计窗口",
    "return_sum": "收益累计窗口",
    "volume_decay": "量比线性加权窗口",
    "trough": "低点窗口",
    "long": "长收益窗口",
    "short": "短收益窗口",
    "volume_rank": "成交量时序排名窗口",
    "price_decay": "价格线性加权窗口",
    "corr": "相关窗口",
    "corr_decay": "相关线性加权窗口",
    "corr_rank": "相关时序排名窗口",
    "price_rank": "价格时序排名窗口",
    "price_sum": "价格累计窗口",
    "rank_corr": "排名相关窗口",
    "rank_decay": "排名相关线性加权窗口",
    "trough_open": "开盘低点窗口",
    "inner_decay": "内层线性加权窗口",
    "outer_decay": "外层线性加权窗口",
    "second_corr": "第二相关窗口",
}
for _n, _title, _inputs, _formula, _multi_windows, _multi_paths in (
    (
        25,
        "量比加权的价格变化与长期收益排名",
        ("close", "volume"),
        "−R(diff_lag(C)×(1−R(D_volume_decay(V/mean_volume_mean(V)))))×(1+R(sum_return_sum(RET)))",
        (("lag", 7), ("volume_mean", 20), ("volume_decay", 9), ("return_sum", 250)),
        ((1, ("lag",)), (-1, ("volume_mean", "volume_decay")), (1, ("return_sum",))),
    ),
    (
        33,
        "低点迁移与长短收益量排名",
        ("close", "low", "volume"),
        "(delay_lag(min_trough(L))−min_trough(L))×R((sum_long(RET)−sum_short(RET))/(long−short))×T_volume_rank(V)；long必须大于short",
        (("trough", 5), ("lag", 5), ("long", 240), ("short", 20), ("volume_rank", 5)),
        ((0, ("trough", "lag")), (1, ("long",)), (0, ("volume_rank",))),
    ),
    (
        39,
        "价格变化与累计量价相关加权排名差",
        ("open", "close", "volume", "vwap"),
        "R(D_corr_decay(corr_corr(0.3W+0.7O,sum_volume_sum(mean_volume_mean(V)))))−R(D_price_decay(diff_lag(C)))",
        (
            ("lag", 2),
            ("price_decay", 8),
            ("volume_mean", 180),
            ("volume_sum", 37),
            ("corr", 14),
            ("corr_decay", 12),
        ),
        ((0, ("lag", "price_decay")), (-3, ("volume_mean", "volume_sum", "corr", "corr_decay"))),
    ),
    (
        44,
        "低价量相关与均价变化时序排名",
        ("low", "volume", "vwap"),
        "T_corr_rank(D_corr_decay(corr_corr(L,mean_volume_mean(V))))+T_price_rank(D_price_decay(diff_lag(W)))；全部为本股时序算子，无截面排名",
        (
            ("volume_mean", 10),
            ("corr", 7),
            ("corr_decay", 6),
            ("corr_rank", 4),
            ("lag", 3),
            ("price_decay", 10),
            ("price_rank", 15),
        ),
        (
            (-3, ("volume_mean", "corr", "corr_decay", "corr_rank")),
            (-1, ("lag", "price_decay", "price_rank")),
        ),
    ),
    (
        56,
        "开盘低点与累计量价相关排名比较",
        ("open", "high", "low", "volume"),
        "R(O−min_trough_open(O))<R(R(corr_corr(sum_price_sum((H+L)/2),sum_volume_sum(mean_volume_mean(V))))^5)；双方有限才输出0/1",
        (
            ("trough_open", 12),
            ("price_sum", 19),
            ("volume_mean", 40),
            ("volume_sum", 19),
            ("corr", 13),
        ),
        (
            (0, ("trough_open",)),
            (-1, ("price_sum", "corr")),
            (-2, ("volume_mean", "volume_sum", "corr")),
        ),
    ),
    (
        73,
        "双层加权量价相关排名差",
        ("close", "volume", "vwap"),
        "R(D_corr_decay(corr_second_corr(W,mean_volume_mean(V))))−T_corr_rank(D_outer_decay(D_inner_decay(corr_corr(C,V))))",
        (
            ("corr", 10),
            ("inner_decay", 16),
            ("outer_decay", 4),
            ("corr_rank", 5),
            ("volume_mean", 30),
            ("second_corr", 4),
            ("corr_decay", 3),
        ),
        (
            (-3, ("corr", "inner_decay", "outer_decay", "corr_rank")),
            (-2, ("volume_mean", "second_corr", "corr_decay")),
        ),
    ),
    (
        74,
        "累计混合低价与量价排名相关",
        ("low", "volume", "vwap"),
        "R(corr_corr(sum_price_sum(0.35L+0.65W),sum_volume_sum(mean_volume_mean(V))))+R(corr_rank_corr(R(W),R(V)))",
        (("price_sum", 20), ("volume_mean", 40), ("volume_sum", 20), ("corr", 7), ("rank_corr", 6)),
        (
            (-1, ("price_sum", "corr")),
            (-2, ("volume_mean", "volume_sum", "corr")),
            (0, ("rank_corr",)),
        ),
    ),
    (
        77,
        "中价均价偏离与量价相关较小排名",
        ("high", "low", "volume", "vwap"),
        "min(R(D_price_decay((H+L)/2−W)),R(D_corr_decay(corr_corr((H+L)/2,mean_volume_mean(V)))))；原式两侧+H相消",
        (("price_decay", 20), ("volume_mean", 40), ("corr", 3), ("corr_decay", 6)),
        ((0, ("price_decay",)), (-2, ("volume_mean", "corr", "corr_decay"))),
    ),
    (
        101,
        "累计均量相关与排名相关比较",
        ("close", "high", "volume", "vwap"),
        "−(R(corr_corr(C,sum_volume_sum(mean_volume_mean(V))))<R(corr_rank_corr(R(0.1H+0.9W),R(V))))；双方有限才输出0/−1",
        (("volume_mean", 30), ("volume_sum", 37), ("corr", 15), ("rank_corr", 11)),
        ((-2, ("volume_mean", "volume_sum", "corr")), (0, ("rank_corr",))),
    ),
    (
        123,
        "累计中价量相关与低价量相关比较",
        ("high", "low", "volume"),
        "−(R(corr_corr(sum_price_sum((H+L)/2),sum_volume_sum(mean_volume_mean(V))))<R(corr_second_corr(L,V)))；双方有限才输出0/−1",
        (
            ("price_sum", 20),
            ("volume_mean", 60),
            ("volume_sum", 20),
            ("corr", 9),
            ("second_corr", 6),
        ),
        (
            (-1, ("price_sum", "corr")),
            (-2, ("volume_mean", "volume_sum", "corr")),
            (0, ("second_corr",)),
        ),
    ),
    (
        125,
        "量均价相关与混合价格变化排名比",
        ("close", "volume", "vwap"),
        "R(D_corr_decay(corr_corr(W,mean_volume_mean(V))))/R(D_price_decay(diff_lag(0.5C+0.5W)))",
        (("volume_mean", 80), ("corr", 17), ("corr_decay", 20), ("lag", 3), ("price_decay", 16)),
        ((-2, ("volume_mean", "corr", "corr_decay")), (0, ("lag", "price_decay"))),
    ),
    (
        130,
        "中价均量相关与排名相关加权比",
        ("high", "low", "volume", "vwap"),
        "R(D_corr_decay(corr_corr((H+L)/2,mean_volume_mean(V))))/R(D_rank_decay(corr_rank_corr(R(W),R(V))))",
        (("volume_mean", 40), ("corr", 9), ("corr_decay", 10), ("rank_corr", 7), ("rank_decay", 3)),
        ((-2, ("volume_mean", "corr", "corr_decay")), (-1, ("rank_corr", "rank_decay"))),
    ),
    (
        141,
        "高价均量排名相关反向排名",
        ("high", "volume"),
        "−R(corr_rank_corr(R(H),R(mean_volume_mean(V))))",
        (("volume_mean", 15), ("rank_corr", 9)),
        ((-1, ("volume_mean", "rank_corr")),),
    ),
):
    _compound(
        _n,
        _title,
        _inputs,
        _formula,
        tuple(
            Window(
                k, v, _MULTISTAGE_LABELS[k], 2 if k in {"corr", "rank_corr", "second_corr"} else 1
            )
            for k, v in _multi_windows
        ),
        _multi_paths,
        panel=_n != 44,
    )


_NESTED_LABELS = {
    "corr": "第一相关窗口",
    "rank_corr": "排名相关窗口",
    "price_decay": "第一线性加权窗口",
    "corr_decay": "第二线性加权窗口",
    "volume_mean": "均量窗口",
    "volume_sum": "均量累计窗口",
    "peak": "相关高点窗口",
    "trough": "相关低点窗口",
    "rank": "中间时序排名窗口",
    "rank_decay": "排名线性加权窗口",
    "price_trough": "均价低点窗口",
    "price_rank": "价格时序排名窗口",
    "volume_rank": "均量时序排名窗口",
    "corr_rank": "相关时序排名窗口",
    "outer_rank": "外层时序排名窗口",
    "lag": "价格差分间隔",
    "inner_min": "内层排名低点窗口",
    "sum": "排名累计窗口",
    "product": "排名乘积窗口",
    "outer_min": "外层排名低点窗口",
    "return_lag": "收益滞后间隔",
    "return_rank": "收益时序排名窗口",
    "short": "短累计窗口",
    "middle": "中累计窗口",
    "long": "长累计窗口",
    "rank_volume_mean": "第二均量窗口",
}
for _n, _title, _nested_inputs, _formula, _nested_windows, _nested_paths in (
    (
        64,
        "两路排名相关加权较大值",
        ("close", "volume", "vwap"),
        "−max(R(D_price_decay(corr_corr(R(W),R(V)))),R(D_corr_decay(max_peak(corr_rank_corr(R(C),R(mean_volume_mean(V)))))))",
        (
            ("corr", 4),
            ("price_decay", 4),
            ("volume_mean", 60),
            ("rank_corr", 4),
            ("peak", 13),
            ("corr_decay", 14),
        ),
        ((-1, ("corr", "price_decay")), (-3, ("volume_mean", "rank_corr", "peak", "corr_decay"))),
    ),
    (
        119,
        "均价累计量相关与开盘排名低点差",
        ("open", "volume", "vwap"),
        "R(D_price_decay(corr_corr(W,sum_volume_sum(mean_volume_mean(V)))))−R(D_rank_decay(T_rank(min_trough(corr_rank_corr(R(O),R(mean_rank_volume_mean(V)))))))",
        (
            ("volume_mean", 5),
            ("volume_sum", 26),
            ("corr", 5),
            ("price_decay", 7),
            ("rank_volume_mean", 15),
            ("rank_corr", 21),
            ("trough", 9),
            ("rank", 7),
            ("rank_decay", 8),
        ),
        (
            (-3, ("volume_mean", "volume_sum", "corr", "price_decay")),
            (-4, ("rank_volume_mean", "rank_corr", "trough", "rank", "rank_decay")),
        ),
    ),
    (
        121,
        "均价低点排名的量价时序相关幂",
        ("volume", "vwap"),
        "−R(W−min_price_trough(W))^T_corr_rank(corr_corr(T_price_rank(W),T_volume_rank(mean_volume_mean(V))))；底数和指数均有限才计算",
        (
            ("price_trough", 12),
            ("price_rank", 20),
            ("volume_mean", 60),
            ("volume_rank", 2),
            ("corr", 18),
            ("corr_rank", 3),
        ),
        (
            (0, ("price_trough",)),
            (-2, ("price_rank", "corr", "corr_rank")),
            (-3, ("volume_mean", "volume_rank", "corr", "corr_rank")),
        ),
    ),
    (
        138,
        "混合低价变化与多层量价排名差",
        ("low", "volume", "vwap"),
        "T_outer_rank(D_rank_decay(T_corr_rank(corr_corr(T_price_rank(L),T_volume_rank(mean_volume_mean(V))))))−R(D_price_decay(diff_lag(0.7L+0.3W)))",
        (
            ("lag", 3),
            ("price_decay", 20),
            ("price_rank", 8),
            ("volume_mean", 60),
            ("volume_rank", 17),
            ("corr", 5),
            ("corr_rank", 19),
            ("rank_decay", 16),
            ("outer_rank", 7),
        ),
        (
            (0, ("lag", "price_decay")),
            (-4, ("price_rank", "corr", "corr_rank", "rank_decay", "outer_rank")),
            (-5, ("volume_mean", "volume_rank", "corr", "corr_rank", "rank_decay", "outer_rank")),
        ),
    ),
    (
        140,
        "四价截面排名差与量价相关较小值",
        ("open", "close", "high", "low", "volume"),
        "min(R(D_price_decay(R(O)+R(L)−R(H)−R(C))),T_corr_rank(D_corr_decay(corr_corr(T_price_rank(C),T_volume_rank(mean_volume_mean(V))))))",
        (
            ("price_decay", 8),
            ("price_rank", 8),
            ("volume_mean", 60),
            ("volume_rank", 20),
            ("corr", 8),
            ("corr_decay", 7),
            ("corr_rank", 3),
        ),
        (
            (0, ("price_decay",)),
            (-3, ("price_rank", "corr", "corr_decay", "corr_rank")),
            (-4, ("volume_mean", "volume_rank", "corr", "corr_decay", "corr_rank")),
        ),
    ),
    (
        157,
        "价格变化嵌套排名与滞后收益排名",
        ("close",),
        "min_outer_min(prod_product(R(R(log(sum_sum(min_inner_min(R(R(−R(diff_lag(C)))))))))))+T_return_rank(delay_return_lag(−RET))；diff(C−1)=diff(C)，默认sum与product窗口均为1",
        (
            ("lag", 5),
            ("inner_min", 2),
            ("sum", 1),
            ("product", 1),
            ("outer_min", 5),
            ("return_lag", 6),
            ("return_rank", 5),
        ),
        (
            (-3, ("lag", "inner_min", "sum", "product", "outer_min")),
            (1, ("return_lag", "return_rank")),
        ),
    ),
    (
        159,
        "三窗口累计低价与真实波幅比",
        ("close", "high", "low"),
        "L*=min(L,C前)，TR=max(H,C前)−L*；Q_w=(C−sum_w(L*))/sum_w(TR)；100×(Q_short×middle×long+Q_middle×short×long+Q_long×short×long)/(short×middle+short×long+middle×long)",
        (("short", 6), ("middle", 12), ("long", 24)),
        ((1, ("long",)),),
    ),
):
    _compound(
        _n,
        _title,
        _nested_inputs,
        _formula,
        tuple(
            Window(k, v, _NESTED_LABELS[k], 2 if k in {"corr", "rank_corr"} else 1)
            for k, v in _nested_windows
        ),
        _nested_paths,
        panel=_n != 159,
    )


_compound(
    28,
    "双低价区间递归差（原表口径）",
    ("close", "high", "low"),
    "U=100(C−min_range(L))/(max_range(H)−min_range(L))；"
    "V=100(C−min_range(L))/(max_range(H)−max_range(L))；"
    "3SMA(U,smooth,1)−2SMA(SMA(V,smooth,1),smooth,1)",
    (Window("range", 9, "高低价区间窗口"), Window("smooth", 3, "递归平滑窗口")),
    ((-2, ("range", "smooth", "smooth")),),
    recursive=True,
)
_compound(
    54,
    "实体离散与开收相关反向排名",
    ("open", "close"),
    "−R(std_body_std(|C−O|)+(C−O)+corr_corr(C,O))；原表STD未写窗口，本App默认10根，可独立配置",
    (
        Window("body_std", 10, "实体标准差窗口（原文省略）", 2),
        Window("corr", 10, "开收相关窗口", 2),
    ),
    ((0, ("body_std",)), (0, ("corr",))),
    panel=True,
)
_compound(
    190,
    "收益上下阈值对数比（原表口径）",
    ("close",),
    "R=C/前C−1，G=(C/delay_lag(C))^(1/root)−1；"
    "U=count_window(R>G)，D=count_window(R<G)；"
    "log((U−1)sum_window(R<G?(R−G−2)^2:0)/(D sum_window(R>G?(R−G)^2:0)))；"
    "仅正分子分母有定义，不将原表两侧平方项改成对称",
    (
        Window("lag", 19, "几何阈值回看间隔"),
        Window("root", 20, "几何阈值根指数", unit="dimensionless"),
        Window("window", 20, "上下阈值统计窗口"),
    ),
    ((0, ("lag", "window")),),
)


_add(
    {143: None},
    "self_up_product",
    "上涨收益递乘（初始值1）",
    ("close",),
    "C>前C时 F=前F×(C−前C)/前C，否则F=前F；"
    "连续行情首根以1初始化且不发布，第二根开始输出；缺失后重新初始化",
    offset=1,
)


_add(
    {75: 50},
    "benchmark_resilience",
    "基准下跌时上涨占比",
    ("open", "close", "benchmark_open", "benchmark_close"),
    "w根中个股C>O且指数C<O的次数 / 同窗口指数C<O的次数；分母为0时缺失",
)
_add(
    {182: 20},
    "benchmark_agreement",
    "与基准同向占比",
    ("open", "close", "benchmark_open", "benchmark_close"),
    "w根中个股与指数同为C>O或同为C<O的次数 / w；任一平盘不计同向",
)
_add(
    {149: 252},
    "benchmark_filtered_beta",
    "基准下跌样本回归系数",
    ("close", "benchmark_close"),
    "先筛选指数B<前B的成对收益(C/前C−1,B/前B−1)，取最近w个下跌样本，"
    "带截距回归个股收益对指数收益的斜率；不是最近w根内的部分样本回归",
    offset=1,
)
_add(
    {181: 20},
    "benchmark_price_moment",
    "收益偏离与指数价格矩比（原表口径）",
    ("close", "benchmark_close"),
    "R=C/前C−1，D=B−mean_w(B)；sum_w((R−mean_w(R))−D²)/sum_w(D³)；"
    "B为指数价格不是收益，原表分母省略窗口，本App明确采用w（默认20）",
    multiplier=2,
)


SPECS[30] = Spec(
    30,
    "risk_residual_energy",
    "风险三因子残差能量",
    ("close", "risk_mkt", "risk_smb", "risk_hml"),
    None,
    "R=C/前C−1；每个完整regression窗口带截距回归R对MKT/SMB/HML，取当根残差e；"
    "对最近smoothing根e²按距当前0、1…根的0.9^i归一加权",
    windows=(Window("regression", 60, "风险回归窗口", 5), Window("smoothing", 20, "残差平滑窗口")),
    warmup_terms=((0, ("regression", "smoothing")),),
)

SPECS[146] = Spec(
    146,
    "interpreted_return_deviation",
    "递归收益偏离（省略权重明确为1）",
    ("close",),
    None,
    "R=C/前C−1；B=SMA(R,smooth,2)；mean_mean(R−B)×(R−B)/SMA(B²,denominator,1)",
    windows=(
        Window("smooth", 61, "收益递归窗口", 2),
        Window("mean", 20, "偏离均值窗口"),
        Window("denominator", 60, "分母递归窗口"),
    ),
    warmup_terms=((0, ("smooth", "mean")), (0, ("smooth", "denominator"))),
    recursive=True,
)
_add(
    {165: 48, 183: 24},
    "interpreted_cumulative_extrema",
    "累计偏离极值（窗口与括号明示）",
    ("close",),
    "D=C−mean_w(C)；S为最近w根D从窗口起点逐根累加的w个前缀；max(S)−min(S)/std_w(C)",
    multiplier=2,
    offset=-1,
)
_add(
    {166: 20},
    "interpreted_centered_return",
    "收益偏离矩比（残缺项均值解释）",
    ("close",),
    "Q=C/前C；U=Q−mean_w(Q)；−w×(w−1)^1.5×sum_w(U)/((w−1)×(w−2)×sum_w(mean_w(Q)²)^1.5)",
    multiplier=2,
)


def _self_up_product(close: pd.Series) -> pd.Series:
    """Keep the recursive state even when its float64 display is unrepresentable.

    Decimal round-trip prices avoid cancellation of tiny upward returns. Decimal
    state (80 significant digits, wide exponent range) prevents a float underflow
    or overflow from permanently destroying subsequent valid outputs. Missing
    prices reset the history; numerical display limits alone must not reset it.
    """
    output = np.full(len(close), np.nan)
    previous: Decimal | None = None
    state = Decimal(1)
    with localcontext() as context:
        context.prec = 80
        context.Emin = -999999999
        context.Emax = 999999999
        for i, price in enumerate(close.to_numpy(float)):
            if i % 64 == 0:
                computation_checkpoint()
            if not np.isfinite(price) or price <= 0:
                previous, state = None, Decimal(1)
                continue
            current = Decimal(str(price))
            if previous is not None:
                if current > previous:
                    state *= (current - previous) / previous
                value = float(state)
                if np.isfinite(value) and value > 0:
                    output[i] = value
            previous = current
    return pd.Series(output, index=close.index)


def _minimum_window(spec: Spec) -> int:
    if spec.number == 166:
        return 3
    return (
        2
        if spec.family
        in {
            "volume_std",
            "interpreted_cumulative_extrema",
            "benchmark_filtered_beta",
            "volume_scaled_return_cv",
            "mean_slope",
            "price_slope",
            "negative_open_volume_corr",
            "sma_midpoint_pressure",
            "sma_volume",
            "sma_range_ratio",
            "sma_log_rate",
            "sma_down_volatility",
            "sma_up_volatility",
            "sma_price_log_mix",
            "sma_range_bias",
        }
        else 1
    )


def _rolling_slope(values: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float) - (window - 1) / 2
    denominator = float(x @ x)
    return values.rolling(window).apply(lambda y: float(x @ (y - y[0])) / denominator, raw=True)


def _sma(values: pd.Series, window: int, weight: int) -> pd.Series:
    """First finite seed; reset on gaps; expose only after window consecutive inputs.

    Not an adjusted EWM or a finite moving average. Every nested stage applies
    its own warmup, so its first *published* input seeds the next stage.
    """
    output = np.full(len(values), np.nan)
    state, count = 0.0, 0
    alpha = weight / window
    for i, value in enumerate(values.to_numpy(dtype=float)):
        computation_checkpoint()
        if not np.isfinite(value):
            state, count = 0.0, 0
            continue
        state = value if count == 0 else alpha * value + (1 - alpha) * state
        if not np.isfinite(state):
            state, count = 0.0, 0
            continue
        count += 1
        if count >= window:
            output[i] = state
    return pd.Series(output, index=values.index)


def _compute_smoothed(data: pd.DataFrame, valid: pd.Series, spec: Spec) -> pd.Series:
    w = spec.window or 1
    c, h, l, v = (data.get(k) for k in ("close", "high", "low", "volume"))  # noqa: E741
    family = spec.family
    if family == "sma_midpoint_pressure":
        return _sma(((h + l) / 2).diff() * (h - l) / v, w, 2)
    if family == "sma_price_change":
        return _sma(c.diff(w).where(valid.rolling(w + 1).sum().eq(w + 1)), w, 1)
    if family in {"sma_high_distance", "sma_stochastic", "sma_double_stochastic"}:
        n = 6 if family == "sma_high_distance" else 9
        top, bottom = h.rolling(n).max(), l.rolling(n).min()
        raw = (top - c if family == "sma_high_distance" else c - bottom) / (top - bottom) * 100
        smooth = _sma(raw, w, 1)
        return _sma(smooth, w, 1) if family == "sma_double_stochastic" else smooth
    if family in {"sma_price_strength", "sma_volume_strength"}:
        delta = (c if family == "sma_price_strength" else v).diff()
        return _sma(delta.clip(lower=0), w, 1) / _sma(delta.abs(), w, 1) * 100
    if family == "sma_volume":
        return _sma(v, w, 2)
    if family in {"sma_range_ratio", "sma_range_bias"}:
        smooth = _sma(h - l, w, 2)
        return (
            smooth / _sma(smooth, w, 2)
            if family == "sma_range_ratio"
            else ((h - l) / smooth - 1) * 100
        )
    if family == "sma_log_rate":
        triple = _sma(_sma(_sma(np.log(c), w, 2), w, 2), w, 2)
        return triple / triple.shift(1) - 1
    if family == "sma_lagged_price_ratio":
        raw = (c / c.shift(w)).shift(1).where(valid.rolling(w + 2).sum().eq(w + 2))
        return _sma(raw, w, 1)
    if family in {"sma_down_volatility", "sma_up_volatility"}:
        std = c.rolling(w).std(ddof=1)
        direction = c.diff().le(0) if family == "sma_down_volatility" else c.diff().gt(0)
        return _sma(std.where(direction, 0).where(std.notna() & c.diff().notna()), w, 1)
    if family == "sma_price_log_mix":
        first = _sma(c, w, 2)
        return 3 * first - 2 * _sma(first, w, 2) + _sma(_sma(_sma(np.log(c), w, 2), w, 2), w, 2)
    raise ValueError(f"未实现平滑公式 {spec.number}")


def _ts_rank(values: pd.Series, window: int) -> pd.Series:
    """Ascending average-tie rank / complete window size; never cross-sectional."""

    def rank(a: NDArray[np.float64]) -> float:
        computation_checkpoint()
        return float(
            (np.count_nonzero(a < a[-1]) + (np.count_nonzero(a == a[-1]) + 1) / 2) / window
        )

    return values.replace([np.inf, -np.inf], np.nan).rolling(window).apply(rank, raw=True)


def _geometric_mean(values: pd.Series, window: int) -> pd.Series:
    weights = np.power(0.9, np.arange(window - 1, -1, -1, dtype=float))
    weights /= weights.sum()

    def weighted(a: NDArray[np.float64]) -> float:
        computation_checkpoint()
        return float(a @ weights)

    return values.replace([np.inf, -np.inf], np.nan).rolling(window).apply(weighted, raw=True)


def _compute_compound(data: pd.DataFrame, valid: pd.Series, spec: Spec) -> pd.Series:
    computation_checkpoint()
    p = spec.resolved_parameters
    c, h, l, v = (data.get(k) for k in ("close", "high", "low", "volume"))  # noqa: E741
    n = spec.number
    if n == 28:
        lower = l.rolling(p["range"]).min()
        upper = h.rolling(p["range"]).max()
        high_low = l.rolling(p["range"]).max()
        first = (100 * (c - lower) / (upper - lower)).replace([np.inf, -np.inf], np.nan)
        second = (100 * (c - lower) / (upper - high_low)).replace([np.inf, -np.inf], np.nan)
        return 3 * _sma(first, p["smooth"], 1) - 2 * _sma(
            _sma(second, p["smooth"], 1), p["smooth"], 1
        )
    if n == 190:
        ret = c / c.shift(1) - 1
        growth = np.expm1(np.log(c / c.shift(p["lag"])) / p["root"])
        complete = valid.rolling(p["lag"] + 1).sum().eq(p["lag"] + 1)
        up = pd.Series(np.nan, index=c.index)
        down = up.copy()
        # Integer powers of exact decimal price ratios decide discontinuous
        # threshold comparisons without a spurious float difference at equality.
        for i in np.flatnonzero(complete.to_numpy()):
            computation_checkpoint()
            price, previous, old = (Fraction(str(c.iloc[j])) for j in (i, i - 1, i - p["lag"]))
            ratio = (price / previous) ** p["root"]
            boundary = price / old
            up.iloc[i], down.iloc[i] = float(ratio > boundary), float(ratio < boundary)
        above = ((ret - growth) ** 2).where(up.eq(1), 0).where(up.notna())
        below = ((ret - growth - 2) ** 2).where(down.eq(1), 0).where(down.notna())
        count_up = up.rolling(p["window"]).sum() - 1
        count_down = down.rolling(p["window"]).sum()
        sum_up = above.rolling(p["window"]).sum()
        sum_down = below.rolling(p["window"]).sum()
        return (
            np.log(count_up.where(count_up.gt(0)))
            + np.log(sum_down.where(sum_down.gt(0)))
            - np.log(count_down.where(count_down.gt(0)))
            - np.log(sum_up.where(sum_up.gt(0)))
        )
    if n == 159:
        lower = pd.concat([l, c.shift(1)], axis=1).min(axis=1, skipna=False)
        upper = pd.concat([h, c.shift(1)], axis=1).max(axis=1, skipna=False)
        ranges = upper - lower
        ratios = [
            (c - lower.rolling(p[k]).sum()) / ranges.rolling(p[k]).sum()
            for k in ("short", "middle", "long")
        ]
        short, middle, long = p["short"], p["middle"], p["long"]
        return (
            100
            * (ratios[0] * middle * long + ratios[1] * short * long + ratios[2] * short * long)
            / (short * middle + short * long + middle * long)
        )
    if n == 44:
        low_corr = _rolling_corr(data.low, data.volume.rolling(p["volume_mean"]).mean(), p["corr"])
        left = _ts_rank(
            _linear_decay(low_corr.to_frame(), p["corr_decay"]).iloc[:, 0], p["corr_rank"]
        )
        change = data.vwap.diff(p["lag"]).where(valid.rolling(p["lag"] + 1).sum().eq(p["lag"] + 1))
        right = _ts_rank(
            _linear_decay(change.to_frame(), p["price_decay"]).iloc[:, 0], p["price_rank"]
        )
        return left + right
    if n == 13:
        return np.sqrt(h) * np.sqrt(l) - data.vwap
    if n == 26:
        return (
            c.rolling(p["mean"]).mean() - c + _rolling_corr(data.vwap, c.shift(p["lag"]), p["corr"])
        )
    if n == 154:
        left = data.vwap - data.vwap.rolling(p["trough"]).min()
        right = _rolling_corr(data.vwap, v.rolling(p["volume_mean"]).mean(), p["corr"])
        return left.lt(right).astype(float).where(np.isfinite(left) & np.isfinite(right))
    if n in {4, 38, 98}:
        return _conditional_prices(data, spec)
    if n == 5:
        return (
            -_rolling_corr(_ts_rank(v, p["rank"]), _ts_rank(h, p["rank"]), p["corr"])
            .rolling(p["peak"])
            .max()
        )
    if n == 22:
        mean = c.rolling(p["mean"]).mean()
        return _sma(((c - mean) / mean).diff(p["lag"]), p["smooth"], 1)
    if n == 23:
        std = _sample_std(c, p["std"])
        ready = std.notna() & c.diff().notna()
        up = _sma(std.where(c.diff() > 0, 0).where(ready), p["smooth"], 1)
        down = _sma(std.where(c.diff() <= 0, 0).where(ready), p["smooth"], 1)
        return 100 * up / (up + down)
    if n in {70, 95, 132}:
        window = data.amount.rolling(p["window"])
        return window.mean() if n == 132 else _sample_std(data.amount, p["window"])
    if n == 78:
        typical = (h + l + c) / 3
        mean = typical.rolling(p["mean"]).mean()
        return (typical - mean) / (0.015 * (c - mean).abs().rolling(p["deviation"]).mean())
    if n in {55, 137}:
        pressure = _conditional_pressure(data, p["lag"])
        return pressure.rolling(p["window"]).sum() if n == 55 else pressure
    if n == 144:
        delta = c / c.shift(1) - 1
        down = c < c.shift(1)
        selected = (delta.abs() / data.amount).where(down, 0).where(delta.notna())
        selected = selected.replace([np.inf, -np.inf], np.nan)
        count = down.astype(float).where(delta.notna()).rolling(p["window"]).sum()
        return selected.rolling(p["window"]).sum() / count
    if n in {172, 186}:
        hd, ld = h.diff(), -l.diff()
        direction = _sum_direction(h, l)
        up = hd.where((hd > 0) & (direction > 0), 0).where(hd.notna() & ld.notna())
        down = ld.where((ld > 0) & (direction < 0), 0).where(hd.notna() & ld.notna())
        tr = np.maximum(np.maximum(h - l, (h - c.shift(1)).abs()), (l - c.shift(1)).abs())
        total = tr.rolling(p["direction"]).sum()
        plus = 100 * up.rolling(p["direction"]).sum() / total
        minus = 100 * down.rolling(p["direction"]).sum() / total
        raw = (100 * (plus - minus).abs() / (plus + minus)).replace([np.inf, -np.inf], np.nan)
        result = raw.rolling(p["smooth"]).mean()
        return (result + result.shift(p["lag"])) / 2 if n == 186 else result
    if n == 27:
        raw = ((c / c.shift(p["short"]) - 1) + (c / c.shift(p["long"]) - 1)) * 100
        return _geometric_mean(raw, p["window"])
    if n == 85:
        return _ts_rank(v / v.rolling(p["volume_mean"]).mean(), p["volume_rank"]) * _ts_rank(
            -c.diff(p["price_lag"]), p["price_rank"]
        )
    if n in {89, 155}:
        source = c if n == 89 else v
        delta = _sma(source, p["short"], 2) - _sma(source, p["long"], 2)
        return (delta - _sma(delta, p["signal"], 2)) * (2 if n == 89 else 1)
    if n == 111:
        raw = v * (2 * c - h - l) / (h - l)
        return _sma(raw, p["long"], 2) - _sma(raw, p["short"], 2)
    if n == 117:
        return (
            _ts_rank(v, p["volume_rank"])
            * (1 - _ts_rank(c + h - l, p["price_rank"]))
            * (1 - _ts_rank(c / c.shift(1) - 1, p["return_rank"]))
        )
    if n == 145:
        return (
            100
            * (v.rolling(p["short"]).mean() - v.rolling(p["long"]).mean())
            / v.rolling(p["scale_window"]).mean()
        )
    if n in {152, 169}:
        if n == 152:
            raw = (c / c.shift(p["lag"])).shift(1)
            span = p["lag"] + 2
            raw = raw.where(valid.rolling(span).sum().eq(span))
        else:
            raw = c.diff()
        inner = _sma(raw, p["smooth"], 1).shift(1)
        return _sma(
            inner.rolling(p["short"]).mean() - inner.rolling(p["long"]).mean(), p["signal"], 1
        )
    if n == 162:
        delta = c.diff()
        ratio = (
            _sma(delta.clip(lower=0), p["smooth"], 1) / _sma(delta.abs(), p["smooth"], 1) * 100
        ).replace([np.inf, -np.inf], np.nan)
        top, bottom = ratio.rolling(p["lookback"]).max(), ratio.rolling(p["lookback"]).min()
        return (ratio - bottom) / (top - bottom)
    if n == 164:
        delta = c.diff()
        inverse = (
            (1 / delta).where(delta > 0, 1).where(delta.notna()).replace([np.inf, -np.inf], np.nan)
        )
        return _sma(
            100 * (inverse - inverse.rolling(p["lookback"]).min()) / (h - l), p["smooth"], 2
        )
    if n == 180:
        delta = c.diff(p["price_lag"])
        ranked = -_ts_rank(delta.abs(), p["price_rank"]) * np.sign(delta)
        return ranked.where(v > v.rolling(p["volume_mean"]).mean(), -v)
    raise ValueError(f"未实现复合公式 {n}")


def _sample_std(values: pd.Series, window: int) -> pd.Series:
    """Recenter every complete window; an old outlier must not poison later STD."""

    def std(a: NDArray[np.float64]) -> float:
        computation_checkpoint()
        scale = np.max(np.abs(a))
        if scale == 0:
            return 0.0
        # Subtract before scaling when safe, preserving tiny spread at large offsets.
        centered = (a - a[0]) / scale
        centered -= centered.mean()
        return float(np.linalg.norm(centered) / np.sqrt(window - 1) * scale)

    return values.rolling(window).apply(std, raw=True)


def _conditional_prices(data: pd.DataFrame, spec: Spec) -> pd.Series:
    """Exact decimal branch thresholds; no epsilon switches near equality."""
    p, n = spec.resolved_parameters, spec.number
    out = pd.Series(np.nan, index=data.index)
    with localcontext() as context:
        context.prec = 50
        series = {
            k: [Decimal(str(x)) if np.isfinite(x) else Decimal("NaN") for x in data[k]]
            for k in spec.inputs
        }
        for i in range(spec.warmup - 1, len(data)):
            computation_checkpoint()
            if any(
                not x.is_finite()
                for values in series.values()
                for x in values[i - spec.warmup + 1 : i + 1]
            ):
                continue
            # Every item in these complete slices is a finite Decimal.
            values = series["high" if n == 38 else "close"]
            now = values[i]
            recent = values[i - p["mean"] + 1 : i + 1]
            mean = sum(recent, Decimal(0)) / p["mean"]
            if n == 4:
                delta = sum(values[i - p["fast"] + 1 : i + 1], Decimal(0)) / p["fast"] - mean
                variance = sum(((x - mean) ** 2 for x in recent), Decimal(0)) / (p["mean"] - 1)
                volume = series["volume"]
                volume_sum = sum(volume[i - p["volume_mean"] + 1 : i + 1])
                fallback = (
                    (1 if volume[i] * p["volume_mean"] >= volume_sum else -1)
                    if volume_sum > 0
                    else np.nan
                )
                out.iloc[i] = (-1 if delta > 0 else 1) if delta * delta > variance else fallback
            elif n == 38:
                out.iloc[i] = float(values[i - p["lag"]] - now) if mean < now else 0
            else:
                previous_sum = sum(values[i - p["lag"] - p["mean"] + 1 : i - p["lag"] + 1])
                low = min(values[i - p["trough"] + 1 : i + 1])
                low_growth = (
                    sum(recent) - previous_sum <= Decimal("0.05") * p["mean"] * values[i - p["lag"]]
                )
                out.iloc[i] = float(low - now if low_growth else values[i - p["change"]] - now)
    return out


def _conditional_pressure(data: pd.DataFrame, lag: int) -> pd.Series:
    out = pd.Series(np.nan, index=data.index)
    with localcontext() as context:
        context.prec = 50
        for i in range(lag, len(data)):
            computation_checkpoint()
            inputs = [
                data.close.iloc[i],
                data.open.iloc[i],
                data.high.iloc[i],
                data.low.iloc[i],
                data.close.iloc[i - lag],
                data.open.iloc[i - lag],
                data.low.iloc[i - lag],
            ]
            if not np.isfinite(inputs).all():
                continue
            c, o, h, l, pc, po, pl = (Decimal(str(x)) for x in inputs)  # noqa: E741
            a, b, d, q = abs(h - pc), abs(l - pc), abs(h - pl), abs(pc - po) / 4
            denominator = (
                a + b / 2 + q if a > b and a > d else b + a / 2 + q if b > d and b > a else d + q
            )
            if denominator:
                out.iloc[i] = float(16 * (c - pc + (c - o) / 2 + pc - po) * max(a, b) / denominator)
    return out


def _rolling_corr(left: pd.Series, right: pd.Series, window: int) -> pd.Series:
    """Centered/scaled Pearson avoids rolling E[XY]−E[X]E[Y] cancellation."""
    a, b = left.to_numpy(), right.to_numpy()
    out = np.full(len(a), np.nan)
    for end in range(window, len(a) + 1):
        computation_checkpoint()
        x, y = a[end - window : end], b[end - window : end]
        if not (np.isfinite(x).all() and np.isfinite(y).all()):
            continue
        x, y = x - x[0], y - y[0]
        sx, sy = np.max(np.abs(x)), np.max(np.abs(y))
        if sx == 0 or sy == 0:
            continue
        x, y = x / sx, y / sy
        x, y = x - x.mean(), y - y.mean()
        out[end - 1] = np.clip((x @ y) / np.sqrt((x @ x) * (y @ y)), -1, 1)
    return pd.Series(out, index=left.index)


def _extreme_age(values: pd.Series, window: int, *, high: bool) -> pd.Series:
    pick = np.argmax if high else np.argmin
    return values.rolling(window).apply(lambda a: float(pick(a[::-1])), raw=True)


def _sum_direction(*values: pd.Series) -> pd.Series:
    """Compare consecutive decimal price sums without changing equality into a trend."""
    arrays = [value.to_numpy() for value in values]
    result = np.full(len(values[0]), np.nan)
    with localcontext() as context:
        context.prec = 40
        for i in range(1, len(result)):
            computation_checkpoint()
            pairs = [(a[i], a[i - 1]) for a in arrays]
            if not np.isfinite(pairs).all():
                continue
            change = sum(
                (Decimal(str(now)) - Decimal(str(previous)) for now, previous in pairs), Decimal(0)
            )
            result[i] = 1 if change > 0 else -1 if change < 0 else 0
    return pd.Series(result, index=values[0].index)


def _clean(frame: pd.DataFrame, spec: Spec) -> tuple[pd.DataFrame, pd.Series]:
    if "vwap" in spec.inputs and frame.attrs.get("snapshot_metadata", {}).get(
        "actual_adjust"
    ) not in (None, "NONE"):
        raise ValueError("VWAP 当前仅支持不复权；未静默转换复权方式")
    if (
        frame.columns.has_duplicates
        or frame.index.has_duplicates
        or not frame.index.is_monotonic_increasing
    ):
        raise ValueError("GTJA191 输入索引或字段重复／未递增")
    if "datetime" in frame or "date" in frame or isinstance(frame.index, pd.DatetimeIndex):
        observation_index(frame)
    for identity in ("code", "symbol", "market"):
        if identity in frame and frame[identity].nunique(dropna=False) > 1:
            raise ValueError("GTJA191 单股序列不能混合标的")
    missing = set(spec.inputs) - set(frame.columns)
    if missing:
        raise ValueError(f"GTJA191 缺少字段：{', '.join(sorted(missing))}")
    values = frame.loc[:, list(spec.inputs)].apply(pd.to_numeric, errors="raise").astype(float)
    valid = pd.Series(True, index=frame.index)
    for field in spec.inputs:
        if reason := frame.attrs.get("factor_input_errors", {}).get(field):
            raise ValueError(reason)
        valid &= np.isfinite(values[field])
        if field not in {"risk_mkt", "risk_smb", "risk_hml"}:
            valid &= values[field].ge(0) if field in {"volume", "amount"} else values[field].gt(0)
    if "high" in values and "low" in values:
        valid &= values.high.ge(values.low)
    for price in ("open", "close"):
        if price in values and "high" in values:
            valid &= values[price].le(values.high)
        if price in values and "low" in values:
            valid &= values[price].ge(values.low)
    if spec.number == 30:
        # Missing risk data must not erase the known previous price needed by
        # the next return. The regression kernel enforces its dependency spans.
        return values.replace([np.inf, -np.inf], np.nan), valid
    return values.where(valid, axis=0), valid


def compute_gtja(frame: pd.DataFrame, spec: Spec) -> pd.Series:
    if spec.panel:
        raise ValueError("此 GTJA191 因子必须使用明确股票池的截面计算")
    if spec.number == 30:
        from easy_tdx.factor.risk_inputs import validate_risk_inputs

        if "factor_risk_inputs" not in frame.attrs:
            raise ValueError("GTJA030需要有来源和历史可得时间的MKT、SMB、HML数据包，不能用指数代理")
        validate_risk_inputs(frame)
    data, valid = _clean(frame, spec)
    w = spec.window or 1
    c, h, l, o, v = (data.get(key) for key in ("close", "high", "low", "open", "volume"))  # noqa: E741
    # Only declared inputs are used in each branch; no proxy field substitution.
    f = spec.family
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        if f == "risk_residual_energy":
            from easy_tdx.factor.builtin.risk_residuals import residual_energy

            return residual_energy(data, **spec.resolved_parameters).rename("gtja191_030")
        elif f == "self_up_product":
            result = _self_up_product(c)
        elif f.startswith("benchmark_"):
            from easy_tdx.factor.builtin.benchmark_statistics import (
                filtered_beta,
                price_moment_ratio,
            )

            if f == "benchmark_filtered_beta":
                result = filtered_beta(c, data.benchmark_close, w)
            elif f == "benchmark_price_moment":
                result = price_moment_ratio(c, data.benchmark_close, w)
            elif f == "benchmark_resilience":
                down = data.benchmark_close.lt(data.benchmark_open)
                numerator = (c.gt(o) & down).astype(float).where(valid).rolling(w).sum()
                denominator = down.astype(float).where(valid).rolling(w).sum()
                result = numerator / denominator.replace(0, np.nan)
            else:
                up = data.benchmark_close.gt(data.benchmark_open)
                down = data.benchmark_close.lt(data.benchmark_open)
                same = (c.gt(o) & up) | (c.lt(o) & down)
                result = same.astype(float).where(valid).rolling(w).sum() / w
        elif f.startswith("interpreted_"):
            from easy_tdx.factor.builtin.window_interpretations import (
                centered_return_ratio,
                cumulative_extrema,
                return_deviation,
            )

            if spec.number == 146:
                p = spec.resolved_parameters
                result = return_deviation(c, p["smooth"], p["mean"], p["denominator"])
            elif spec.number == 166:
                result = centered_return_ratio(c, w)
            else:
                result = cumulative_extrema(c, w)
        elif f.startswith("compound_"):
            result = _compute_compound(data, valid, spec)
            computation_checkpoint()
        elif f.startswith("sma_"):
            result = _compute_smoothed(data, valid, spec)
        elif f == "location_delta":
            location = (2 * c - h - l) / (h - l)
            result = location.shift(w) - location
        elif f == "buy_pressure":
            previous = c.shift(1)
            anchor = pd.Series(
                np.where(c > previous, np.minimum(l, previous), np.maximum(h, previous)),
                index=data.index,
            )
            flow = (c - anchor).where(c != previous, 0).where(previous.notna())
            result = flow.rolling(w).sum()
        elif f == "flow_sum":
            result = (
                ((2 * c - h - l) / (h - l) * v).replace([np.inf, -np.inf], np.nan).rolling(w).sum()
            )
        elif f == "price_delta":
            result = c - c.shift(w)
        elif f == "open_gap":
            result = o / c.shift(w) - 1
        elif f == "price_ratio":
            result = c / c.shift(w)
        elif f == "asymmetric_return":
            result = (c - c.shift(w)) / np.maximum(c, c.shift(w))
        elif f == "return_pct":
            result = (c / c.shift(w) - 1) * 100
        elif f == "volume_return":
            result = (c / c.shift(w) - 1) * v
        elif f == "deviation_pct":
            result = (c / c.rolling(w).mean() - 1) * 100
        elif f == "mean_ratio":
            result = c.rolling(w).mean() / c
        elif f == "signed_volume":
            result = (np.sign(c.diff()) * v).rolling(w).sum()
        elif f in {"four_mean", "four_mean_ratio"}:
            result = sum(c.rolling(w * k).mean() for k in (1, 2, 4, 8)) / 4
            if f == "four_mean_ratio":
                result = result / c
        elif f == "up_count_pct":
            result = (c.diff() > 0).astype(float).where(c.diff().notna()).rolling(w).mean() * 100
        elif f == "volume_change_pct":
            result = (v / v.shift(w) - 1) * 100
        elif f == "volume_std":
            result = v.rolling(w).std(ddof=1)
        elif f == "range_pressure":
            result = (
                (h - c.shift(1)).clip(lower=0).rolling(w).sum()
                / (c.shift(1) - l).clip(lower=0).rolling(w).sum()
                * 100
            )
        elif f == "open_pressure":
            result = (h - o).rolling(w).sum() / (o - l).rolling(w).sum() * 100
        elif f == "typical_price":
            result = (c + h + l) / 3
        elif f == "typical_volume":
            result = (c + h + l) / 3 * v
        elif f == "down_sum":
            result = (-c.diff()).clip(lower=0).rolling(w).sum()
        elif f == "up_sum":
            result = c.diff().clip(lower=0).rolling(w).sum()
        elif f == "true_range_mean":
            result = (
                np.maximum(np.maximum(h - l, abs(h - c.shift(1))), abs(l - c.shift(1)))
                .rolling(w)
                .mean()
            )
        elif f == "negative_volume_ratio":
            result = -v / v.rolling(w).mean()
        elif f == "open_up_pressure":
            result = (
                pd.Series(
                    np.where(o > o.shift(1), np.maximum(h - o, o.diff()), 0.0), index=data.index
                )
                .where(o.diff().notna())
                .rolling(w)
                .sum()
            )
        elif f == "mean_abs_deviation":
            result = abs(c - c.rolling(w).mean()).rolling(w).mean()
        elif f in {"mean_slope", "price_slope"}:
            result = _rolling_slope(c.rolling(w).mean() if f == "mean_slope" else c, w)
        elif f == "up_down_volume_ratio":
            up = v.where(c > c.shift(1), 0).rolling(w).sum()
            down = v.where(c <= c.shift(1), 0).rolling(w).sum()
            result = up / down * 100
        elif f in {"down_range_share", "up_range_share", "range_direction_balance"}:
            movement = np.maximum(abs(h.diff()), abs(l.diff()))
            direction = _sum_direction(h, l)
            up = movement.where(direction > 0, 0).rolling(w).sum()
            down = movement.where(direction < 0, 0).rolling(w).sum()
            numerator = (
                down if f == "down_range_share" else up if f == "up_range_share" else up - down
            )
            result = numerator / (up + down)
        elif f == "typical_range_pressure":
            previous = ((h + l + c) / 3).shift(1)
            result = (
                (h - previous).clip(lower=0).rolling(w).sum()
                / ((previous - l).clip(lower=0).rolling(w).sum())
                * 100
            )
        elif f in {"open_pressure_balance", "open_down_pressure"}:
            down = np.maximum(o - l, o.diff()).where(o < o.shift(1), 0).rolling(w).sum()
            if f == "open_down_pressure":
                result = down
            else:
                up = np.maximum(h - o, o.diff()).where(o > o.shift(1), 0).rolling(w).sum()
                result = ((up - down) / np.maximum(up, down)).where(up != down, 0)
        elif f == "volume_scaled_return_cv":
            value = (abs(c / c.shift(1) - 1) / v).replace([np.inf, -np.inf], np.nan)
            result = value.rolling(w).std(ddof=1) / value.rolling(w).mean()
        elif f == "price_acceleration_switch":
            # This is a discontinuous branch, so round-off around 0 / 0.25
            # must not fabricate a different condition. No arbitrary epsilon.
            result = -c.diff()
            with localcontext() as context:
                context.prec = 40
                for i in range(2 * w, len(c)):
                    computation_checkpoint()
                    values = [c.iloc[i - 2 * w], c.iloc[i - w], c.iloc[i]]
                    if not np.isfinite(values).all():
                        continue
                    a, b, z = (Decimal(str(value)) for value in values)
                    change = a - 2 * b + z
                    if change > Decimal("0.25") * w:
                        result.iloc[i] = -1
                    elif change < 0:
                        result.iloc[i] = 1
        elif f in {"low_recency", "high_recency", "extreme_recency_balance"}:
            if f == "extreme_recency_balance":
                result = (_extreme_age(l, w, high=False) - _extreme_age(h, w, high=True)) / w * 100
            else:
                result = (
                    (w - _extreme_age(h if f == "high_recency" else l, w, high=f == "high_recency"))
                    / w
                    * 100
                )
        elif f == "price_direction_balance":
            up, down = (
                c.diff().clip(lower=0).rolling(w).sum(),
                (-c.diff()).clip(lower=0).rolling(w).sum(),
            )
            result = (up - down) / (up + down) * 100
        elif f == "peak_deviation_rms":
            result = np.sqrt(((c / c.rolling(w).max() - 1) * 100).pow(2).rolling(w).mean())
        elif f == "typical_money_flow":
            typical = (h + l + c) / 3
            direction = _sum_direction(h, l, c)
            up = (typical * v).where(direction > 0, 0).rolling(w).sum()
            down = (typical * v).where(direction < 0, 0).rolling(w).sum()
            ratio = (up / down).replace([np.inf, -np.inf], np.nan)
            result = 100 - 100 / (1 + ratio)
        elif f == "negative_open_volume_corr":
            result = -_rolling_corr(o, v, w)
        elif f == "range_close_ratio":
            result = (h - l) / c
        elif f == "body_range_power":
            result = -(l - c) / (c - h) * (o / c).pow(5)
        elif f == "volume_mean_low_corr":
            result = _rolling_corr(v.rolling(w).mean(), l, 5) + (h + l) / 2 - c
        else:
            raise ValueError(f"尚未实现 GTJA191 公式 {spec.number}")
    complete = valid.rolling(spec.warmup).sum().eq(spec.warmup)
    return result.where(complete & np.isfinite(result)).rename(f"gtja191_{spec.number:03d}")


class GTJAFactor(Factor):
    spec: Spec

    def __init__(self, *, window: int | None = None, **parameters: Any) -> None:
        super().__init__()
        if self.spec.windows:
            if window is not None:
                parameters["window"] = window
            declared = {w.key: w for w in self.spec.windows}
            if set(parameters) - set(declared):
                raise ValueError("GTJA191 不接受未声明的参数")
            for key, value in parameters.items():
                if type(value) is not int or not declared[key].minimum <= value <= 600:
                    raise ValueError(f"GTJA191 {key} 必须为 {declared[key].minimum}—600 的整数")
            self.spec = replace(
                self.spec,
                windows=tuple(
                    replace(w, value=parameters.get(w.key, w.value)) for w in self.spec.windows
                ),
            )
            values = self.spec.resolved_parameters
            if "short" in values and values["short"] >= values["long"]:
                raise ValueError("GTJA191 短窗口必须小于长窗口")
            if self.spec.number == 159 and not values["short"] < values["middle"] < values["long"]:
                raise ValueError("三个累计窗口必须满足短 < 中 < 长")
            if self.spec.warmup > 600:
                raise ValueError("GTJA191 复合依赖窗口不能超过600根；未静默缩小参数")
            return
        if parameters:
            raise ValueError("GTJA191 不接受未声明的参数")
        if window is not None:
            minimum = _minimum_window(self.spec)
            maximum = 600 // self.spec.multiplier
            if (
                self.spec.window is None
                or type(window) is not int
                or not minimum <= window <= maximum
            ):
                raise ValueError(f"GTJA191 窗口必须为 {minimum}—{maximum} 的整数，且公式须声明窗口")
            self.spec = replace(self.spec, window=window)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if self.spec.family.startswith("benchmark_"):
            from easy_tdx.factor.benchmark import validate_benchmark

            validate_benchmark(df)
        return compute_gtja(df, self.spec)


class GTJAPanelFactor(GTJAFactor, PanelFactor):
    def compute(self, df: pd.DataFrame) -> pd.Series:
        return PanelFactor.compute(self, df)

    def compute_panel(self, panel: FactorPanel) -> pd.DataFrame:
        computation_checkpoint()
        if self.spec.family.startswith("panel_"):
            return _compute_panel_compound(panel, self.spec)
        fields = {
            key: value.where(np.isfinite(value) & value.gt(0))
            for key, value in panel.fields.items()
        }
        if self.spec.family == "rank_weighted_delta":
            consistent = fields["open"].le(fields["high"])
            fields = {key: value.where(consistent) for key, value in fields.items()}
            w = self.spec.window or 1
            complete = (
                (fields["open"].notna() & fields["high"].notna()).rolling(w + 1).sum().eq(w + 1)
            )
            # SIGN is discontinuous: subtracting weighted binary floats can
            # turn equal decimal prices into opposite ranks. Compare 17O+3H
            # using the decimal round-trip values, without an arbitrary epsilon.
            value = pd.DataFrame(np.nan, index=complete.index, columns=complete.columns)
            with localcontext() as context:
                context.prec = 40
                for symbol in complete.columns:
                    computation_checkpoint()
                    opens, highs = (
                        fields["open"][symbol].to_numpy(),
                        fields["high"][symbol].to_numpy(),
                    )
                    signs = np.full(len(value), np.nan)
                    for i in np.flatnonzero(complete[symbol].to_numpy()):
                        change = 17 * (Decimal(str(opens[i])) - Decimal(str(opens[i - w]))) + 3 * (
                            Decimal(str(highs[i])) - Decimal(str(highs[i - w]))
                        )
                        signs[i] = 1 if change > 0 else -1 if change < 0 else 0
                    value[symbol] = signs
            return -cross_section_rank(value)
        if self.spec.number == 185:
            value = -((1 - fields["open"] / fields["close"]) ** 2)
            return cross_section_rank(value.replace([np.inf, -np.inf], np.nan))
        raise ValueError(f"未实现股票池公式 {self.spec.number}")


def _panel_correlation(a: pd.DataFrame, b: pd.DataFrame, window: int) -> pd.DataFrame:
    result = {}
    for symbol in a.columns:
        computation_checkpoint()
        if window == 2:
            # Two nonconstant pairs have exactly +/-1 correlation. Prevent a
            # last-bit error becoming a false cross-sectional rank difference.
            x, y = a[symbol].diff(), b[symbol].diff()
            result[symbol] = (np.sign(x) * np.sign(y)).where(
                x.ne(0) & y.ne(0) & np.isfinite(x) & np.isfinite(y)
            )
        else:
            result[symbol] = _rolling_corr(a[symbol], b[symbol], window)
    return pd.DataFrame(result, index=a.index, columns=a.columns)


def _panel_rank_moment(
    a: pd.DataFrame,
    b: pd.DataFrame,
    window: int,
    *,
    denominators: tuple[int, int] | None = None,
    covariance: bool = False,
) -> pd.DataFrame:
    """Exact rational rank moments, then one float conversion, preserving ties.

    Average rank / count has denominator <= 2*count. Only call with known
    ranks, never round raw prices or approximate correlations with an epsilon.
    Sliding sums keep the work linear in observations, not in window size.
    """
    bounds = denominators or (2 * len(a.columns), 2 * len(b.columns))
    result = pd.DataFrame(np.nan, index=a.index, columns=a.columns)
    for symbol in a.columns:
        caches: list[dict[float, Fraction]] = [{}, {}]
        samples: list[tuple[Fraction, Fraction] | None] = []
        sx = sy = sxx = syy = sxy = Fraction(0)
        count = 0
        values = np.full(len(a), np.nan)
        for i, (left, right) in enumerate(zip(a[symbol], b[symbol])):
            computation_checkpoint()
            sample = None
            if np.isfinite(left) and np.isfinite(right):
                converted = []
                for side, value in enumerate((left, right)):
                    if value not in caches[side]:
                        caches[side][value] = Fraction(float(value)).limit_denominator(bounds[side])
                    converted.append(caches[side][value])
                sample = converted[0], converted[1]
            samples.append(sample)
            for pair, sign in ((sample, 1), (samples[i - window] if i >= window else None, -1)):
                if pair is not None:
                    x, y = pair
                    count += sign
                    sx += sign * x
                    sy += sign * y
                    sxx += sign * x * x
                    syy += sign * y * y
                    sxy += sign * x * y
            if count != window:
                continue
            numerator = window * sxy - sx * sy
            if covariance:
                values[i] = float(numerator / (window * (window - 1)))
            else:
                variance = (window * sxx - sx * sx) * (window * syy - sy * sy)
                if variance > 0:
                    sign = 1 if numerator > 0 else -1 if numerator < 0 else 0
                    values[i] = sign * np.sqrt(float(numerator * numerator / variance))
        result[symbol] = values
    return result


def _panel_time_rank(a: pd.DataFrame, window: int) -> pd.DataFrame:
    return pd.DataFrame({s: _ts_rank(a[s], window) for s in a.columns}, index=a.index)


def _linear_mean(a: pd.DataFrame, window: int) -> pd.DataFrame:
    weights = np.arange(1, window + 1, dtype=float)
    weights /= weights.sum()

    def weighted(values: NDArray[np.float64]) -> float:
        computation_checkpoint()
        return float(values @ weights)

    return a.replace([np.inf, -np.inf], np.nan).rolling(window).apply(weighted, raw=True)


def _linear_rank_mean(
    a: pd.DataFrame, window: int, *, denominator_bound: int | None = None
) -> pd.DataFrame:
    """Only for percentile ranks: preserve exact weighted ties before ranking again.

    Average-tie percentile ranks have a denominator at most twice pool size,
    including changing valid membership. Never rationalize raw prices.
    """
    bound = denominator_bound or 2 * len(a.columns)
    denominator = window * (window + 1) // 2

    def weighted(values: NDArray[np.float64]) -> float:
        computation_checkpoint()
        return float(
            sum((i + 1) * Fraction(float(x)).limit_denominator(bound) for i, x in enumerate(values))
            / denominator
        )

    return a.rolling(window).apply(weighted, raw=True)


def _rank_price_contrast(
    o: pd.DataFrame, low: pd.DataFrame, h: pd.DataFrame, c: pd.DataFrame
) -> pd.DataFrame:
    """Exact O+L-H-C for known ranks sharing one observed membership mask."""
    bound = 2 * len(o.columns)
    out = np.full(o.shape, np.nan)
    arrays = [a.to_numpy() for a in (o, low, h, c)]
    for i in range(len(o)):
        computation_checkpoint()
        for j in range(len(o.columns)):
            values = [a[i, j] for a in arrays]
            if all(np.isfinite(values)):
                out[i, j] = float(
                    sum(
                        sign * Fraction(float(v)).limit_denominator(bound)
                        for sign, v in zip((1, 1, -1, -1), values)
                    )
                )
    return pd.DataFrame(out, index=o.index, columns=o.columns)


def _rank_window_sum(a: pd.DataFrame, window: int) -> pd.DataFrame:
    """Sum known percentile ranks without splitting equal rational totals."""
    bound = 2 * len(a.columns)

    def total(values: NDArray[np.float64]) -> float:
        computation_checkpoint()
        return float(sum(Fraction(float(v)).limit_denominator(bound) for v in values))

    return a.rolling(window).apply(total, raw=True)


def _linear_decay(a: pd.DataFrame, window: int) -> pd.DataFrame:
    """Local compensated sum; keep the legacy 124 arithmetic unchanged."""
    denominator = window * (window + 1) // 2

    def weighted(values: NDArray[np.float64]) -> float:
        computation_checkpoint()
        try:
            total = fsum((i + 1) * float(x) for i, x in enumerate(values))
            if np.isfinite(total):
                return total / denominator
        except (OverflowError, ValueError):
            pass
        scale = float(np.max(np.abs(values)))
        return (
            fsum((i + 1) * (float(x) / scale) for i, x in enumerate(values)) / denominator * scale
        )

    return a.replace([np.inf, -np.inf], np.nan).rolling(window).apply(weighted, raw=True)


def _panel_ratio_rank(numerator: pd.DataFrame, denominator: pd.DataFrame) -> pd.DataFrame:
    """Rank exact decimal-input ratios before any float rounding or log subtraction.

    For positive inputs log(a)-log(b), a/b and a/b-1 have identical order.
    Ratios are never materialized as floats, so proportional volumes stay tied.
    """
    out = np.full(numerator.shape, np.nan)
    for i, (top, bottom) in enumerate(zip(numerator.to_numpy(), denominator.to_numpy())):
        computation_checkpoint()
        ratios = {
            j: Fraction(str(a)) / Fraction(str(b))
            for j, (a, b) in enumerate(zip(top, bottom))
            if np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0
        }
        if len(ratios) < 2:
            continue
        ordered = sorted(ratios.values())
        positions: dict[Fraction, list[int]] = {}
        for pos, value in enumerate(ordered, 1):
            positions.setdefault(value, []).append(pos)
        ranked = {
            value: (indices[0] + indices[-1]) / (2 * len(ordered))
            for value, indices in positions.items()
        }
        for j, value in ratios.items():
            out[i, j] = ranked[value]
    return pd.DataFrame(out, index=numerator.index, columns=numerator.columns)


def _compute_panel_compound(panel: FactorPanel, spec: Spec) -> pd.DataFrame:
    p, n = spec.resolved_parameters, spec.number
    fields = {key: panel.fields[key].copy() for key in spec.inputs}
    valid = panel.observed.copy()
    for key, value in fields.items():
        valid &= np.isfinite(value) & (value.ge(0) if key == "volume" else value.gt(0))
    for top, bottom in (
        ("high", "low"),
        ("high", "open"),
        ("high", "close"),
        ("open", "low"),
        ("close", "low"),
    ):
        if top in fields and bottom in fields:
            valid &= fields[top].ge(fields[bottom])
    fields = {key: value.where(valid) for key, value in fields.items()}
    empty = pd.DataFrame(np.nan, index=valid.index, columns=valid.columns)
    c, o, h, l, v = (fields.get(k, empty) for k in ("close", "open", "high", "low", "volume"))  # noqa: E741
    w = fields.get("vwap", empty)
    complete = valid.rolling(spec.warmup).sum().eq(spec.warmup)
    rank, corr, trank = cross_section_rank, _panel_correlation, _panel_time_rank
    decay = _linear_decay

    def span(a: pd.DataFrame, length: int) -> pd.DataFrame:
        return a.where(valid.rolling(length).sum().eq(length))

    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        ret = c / c.shift(1) - 1
        if n == 1:
            # Even a skipped intermediate zero cannot be a valid log-volume input.
            volume_change_rank = _panel_ratio_rank(
                v.where(v.gt(0).rolling(p["lag"] + 1).sum().eq(p["lag"] + 1)),
                v.shift(p["lag"]),
            )
            result = -_panel_rank_moment(volume_change_rank, _panel_ratio_rank(c, o), p["corr"])
        elif n == 7:
            result = (
                rank((w - c).rolling(p["range"]).max()) + rank((w - c).rolling(p["range"]).min())
            ) * rank(span(v.diff(p["lag"]), p["lag"] + 1))
        elif n == 8:
            result = rank(span(-(0.2 * (h + l) / 2 + 0.8 * w).diff(p["lag"]), p["lag"] + 1))
        elif n == 54:
            result = -rank(
                (c - o).abs().rolling(p["body_std"]).std(ddof=1) + (c - o) + corr(c, o, p["corr"])
            )
        elif n == 25:
            volume_rank = rank(decay(v / v.rolling(p["volume_mean"]).mean(), p["volume_decay"]))
            change = span(c.diff(p["lag"]), p["lag"] + 1)
            result = -rank(change * (1 - volume_rank)) * (
                1 + rank(ret.rolling(p["return_sum"]).apply(fsum, raw=True))
            )
        elif n == 33:
            low = l.rolling(p["trough"]).min()
            # Algebraically cancel the shared recent returns, avoiding two
            # large almost-equal totals. Still require the entire long history.
            older = span(
                ret.shift(p["short"]).rolling(p["long"] - p["short"]).mean(), p["long"] + 1
            )
            result = (low.shift(p["lag"]) - low) * rank(older) * trank(v, p["volume_rank"])
        elif n == 39:
            left = rank(decay(span(c.diff(p["lag"]), p["lag"] + 1), p["price_decay"]))
            right = rank(
                decay(
                    corr(
                        0.3 * w + 0.7 * o,
                        v.rolling(p["volume_mean"]).mean().rolling(p["volume_sum"]).sum(),
                        p["corr"],
                    ),
                    p["corr_decay"],
                )
            )
            result = right - left
        elif n == 56:
            left = rank(o - o.rolling(p["trough_open"]).min())
            right = rank(
                rank(
                    corr(
                        (h / 2 + l / 2).rolling(p["price_sum"]).sum(),
                        v.rolling(p["volume_mean"]).mean().rolling(p["volume_sum"]).sum(),
                        p["corr"],
                    )
                ).pow(5)
            )
            result = left.lt(right).astype(float).where(left.notna() & right.notna())
        elif n == 73:
            left = trank(
                decay(decay(corr(c, v, p["corr"]), p["inner_decay"]), p["outer_decay"]),
                p["corr_rank"],
            )
            right = rank(
                decay(
                    corr(w, v.rolling(p["volume_mean"]).mean(), p["second_corr"]), p["corr_decay"]
                )
            )
            result = right - left
        elif n == 74:
            left = rank(
                corr(
                    (0.35 * l + 0.65 * w).rolling(p["price_sum"]).sum(),
                    v.rolling(p["volume_mean"]).mean().rolling(p["volume_sum"]).sum(),
                    p["corr"],
                )
            )
            result = left + rank(_panel_rank_moment(rank(w), rank(v), p["rank_corr"]))
        elif n == 77:
            mid = h / 2 + l / 2
            result = np.minimum(
                rank(decay(mid - w, p["price_decay"])),
                rank(
                    decay(corr(mid, v.rolling(p["volume_mean"]).mean(), p["corr"]), p["corr_decay"])
                ),
            )
        elif n == 101:
            left = rank(
                corr(
                    c, v.rolling(p["volume_mean"]).mean().rolling(p["volume_sum"]).sum(), p["corr"]
                )
            )
            right = rank(_panel_rank_moment(rank(0.1 * h + 0.9 * w), rank(v), p["rank_corr"]))
            result = -left.lt(right).astype(float).where(left.notna() & right.notna())
        elif n == 123:
            left = rank(
                corr(
                    (h / 2 + l / 2).rolling(p["price_sum"]).sum(),
                    v.rolling(p["volume_mean"]).mean().rolling(p["volume_sum"]).sum(),
                    p["corr"],
                )
            )
            right = rank(corr(l, v, p["second_corr"]))
            result = -left.lt(right).astype(float).where(left.notna() & right.notna())
        elif n == 125:
            left = rank(
                decay(corr(w, v.rolling(p["volume_mean"]).mean(), p["corr"]), p["corr_decay"])
            )
            right = rank(
                decay(span((c / 2 + w / 2).diff(p["lag"]), p["lag"] + 1), p["price_decay"])
            )
            result = left / right
        elif n == 130:
            left = rank(
                decay(
                    corr(h / 2 + l / 2, v.rolling(p["volume_mean"]).mean(), p["corr"]),
                    p["corr_decay"],
                )
            )
            right = rank(
                decay(_panel_rank_moment(rank(w), rank(v), p["rank_corr"]), p["rank_decay"])
            )
            result = left / right
        elif n == 141:
            result = -rank(
                _panel_rank_moment(
                    rank(h), rank(v.rolling(p["volume_mean"]).mean()), p["rank_corr"]
                )
            )
        elif n == 64:
            first = _panel_rank_moment(rank(w), rank(v), p["corr"])
            second = _panel_rank_moment(
                rank(c), rank(v.rolling(p["volume_mean"]).mean()), p["rank_corr"]
            )
            result = -np.maximum(
                rank(decay(first, p["price_decay"])),
                rank(decay(second.rolling(p["peak"]).max(), p["corr_decay"])),
            )
        elif n == 119:
            first = corr(
                w, v.rolling(p["volume_mean"]).mean().rolling(p["volume_sum"]).sum(), p["corr"]
            )
            second = _panel_rank_moment(
                rank(o), rank(v.rolling(p["rank_volume_mean"]).mean()), p["rank_corr"]
            )
            intermediate = trank(second.rolling(p["trough"]).min(), p["rank"])
            result = rank(decay(first, p["price_decay"])) - rank(
                _linear_rank_mean(intermediate, p["rank_decay"], denominator_bound=2 * p["rank"])
            )
        elif n == 121:
            base = rank(w - w.rolling(p["price_trough"]).min())
            moment = _panel_rank_moment(
                trank(w, p["price_rank"]),
                trank(v.rolling(p["volume_mean"]).mean(), p["volume_rank"]),
                p["corr"],
                denominators=(2 * p["price_rank"], 2 * p["volume_rank"]),
            )
            power = trank(moment, p["corr_rank"])
            result = -base.pow(power).where(base.notna() & power.notna())
        elif n == 138:
            first = rank(
                decay(span((0.7 * l + 0.3 * w).diff(p["lag"]), p["lag"] + 1), p["price_decay"])
            )
            moment = _panel_rank_moment(
                trank(l, p["price_rank"]),
                trank(v.rolling(p["volume_mean"]).mean(), p["volume_rank"]),
                p["corr"],
                denominators=(2 * p["price_rank"], 2 * p["volume_rank"]),
            )
            second = trank(
                _linear_rank_mean(
                    trank(moment, p["corr_rank"]),
                    p["rank_decay"],
                    denominator_bound=2 * p["corr_rank"],
                ),
                p["outer_rank"],
            )
            result = second - first
        elif n == 140:
            contrast = _rank_price_contrast(rank(o), rank(l), rank(h), rank(c))
            first = rank(_linear_rank_mean(contrast, p["price_decay"]))
            moment = _panel_rank_moment(
                trank(c, p["price_rank"]),
                trank(v.rolling(p["volume_mean"]).mean(), p["volume_rank"]),
                p["corr"],
                denominators=(2 * p["price_rank"], 2 * p["volume_rank"]),
            )
            second = trank(decay(moment, p["corr_decay"]), p["corr_rank"])
            result = np.minimum(first, second)
        elif n == 157:
            inner = rank(rank(-rank(span(c.diff(p["lag"]), p["lag"] + 1))))
            accumulated = _rank_window_sum(inner.rolling(p["inner_min"]).min(), p["sum"])
            ranked = rank(rank(np.log(accumulated.where(accumulated.gt(0)))))
            first = (
                ranked.rolling(p["product"]).apply(np.prod, raw=True).rolling(p["outer_min"]).min()
            )
            second = trank((-ret).shift(p["return_lag"]), p["return_rank"])
            result = first + second
        elif n == 35:
            left = rank(decay(span(o.diff(p["lag"]), p["lag"] + 1), p["price_decay"]))
            right = rank(decay(corr(v, o, p["corr"]), p["corr_decay"]))
            result = -np.minimum(left, right)
        elif n == 61:
            left = rank(decay(span(w.diff(p["lag"]), p["lag"] + 1), p["price_decay"]))
            right = rank(
                _linear_rank_mean(
                    rank(corr(l, v.rolling(p["volume_mean"]).mean(), p["corr"])), p["corr_decay"]
                )
            )
            result = -np.maximum(left, right)
        elif n == 87:
            left = rank(decay(span(w.diff(p["lag"]), p["lag"] + 1), p["price_decay"]))
            ratio = (l - w) / (o - (h / 2 + l / 2))
            right = trank(decay(ratio, p["ratio_decay"]), p["rank"])
            result = -(left + right)
        elif n == 92:
            mix = 0.35 * c + 0.65 * w
            left = rank(decay(span(mix.diff(p["lag"]), p["lag"] + 1), p["price_decay"]))
            right = trank(
                decay(
                    corr(v.rolling(p["volume_mean"]).mean(), c, p["corr"]).abs(), p["corr_decay"]
                ),
                p["rank"],
            )
            result = -np.maximum(left, right)
        elif n == 156:
            mix = 0.15 * o + 0.85 * l
            left = rank(decay(span(w.diff(p["lag"]), p["lag"] + 1), p["price_decay"]))
            right = rank(
                decay(span(-mix.diff(p["mix_lag"]) / mix, p["mix_lag"] + 1), p["mix_decay"])
            )
            result = -np.maximum(left, right)
        elif n == 12:
            result = -rank(o - w.rolling(p["mean"]).mean()) * rank((c - w).abs())
        elif n == 16:
            result = -rank(_panel_rank_moment(rank(v), rank(w), p["corr"])).rolling(p["peak"]).max()
        elif n == 17:
            base = rank(w - w.rolling(p["peak"]).max())
            exponent = c.diff(p["lag"])
            result = base.pow(exponent).where(np.isfinite(base) & np.isfinite(exponent))
        elif n == 36:
            # Recompute the current window; a rolling accumulator's old
            # rounding residue can otherwise split a genuine zero rank tie.
            result = rank(
                _panel_rank_moment(rank(v), rank(w), p["corr"])
                .rolling(p["sum"])
                .apply(fsum, raw=True)
            )
        elif n == 41:
            result = -rank(span(w.diff(p["lag"]).rolling(p["peak"]).max(), spec.warmup))
        elif n == 45:
            result = rank(span((0.6 * c + 0.4 * o).diff(p["lag"]), p["lag"] + 1)) * rank(
                corr(w, v.rolling(p["volume_mean"]).mean(), p["corr"])
            )
        elif n == 90:
            result = -rank(_panel_rank_moment(rank(w), rank(v), p["corr"]))
        elif n == 108:
            base = rank(h - h.rolling(p["trough"]).min())
            exponent = rank(corr(w, v.rolling(p["volume_mean"]).mean(), p["corr"]))
            result = -base.pow(exponent).where(np.isfinite(base) & np.isfinite(exponent))
        elif n == 114:
            relative = (h - l) / c.rolling(p["mean"]).mean()
            denominator = (relative / (w - c)).replace([np.inf, -np.inf], np.nan)
            result = rank(span(relative.shift(p["lag"]), spec.warmup)) * rank(rank(v)) / denominator
        elif n == 120:
            result = rank(w - c) / rank(w + c)
        elif n == 124:
            result = (c - w) / _linear_mean(rank(c.rolling(p["peak"]).max()), p["decay"])
        elif n == 131:
            base = rank(span(w.diff(p["lag"]), p["lag"] + 1))
            exponent = trank(corr(c, v.rolling(p["volume_mean"]).mean(), p["corr"]), p["rank"])
            result = base.pow(exponent).where(np.isfinite(base) & np.isfinite(exponent))
        elif n == 163:
            result = rank(
                span(-ret * v.rolling(p["volume_mean"]).mean() * w * (h - c), spec.warmup)
            )
        elif n == 170:
            result = rank(1 / c) * v / v.rolling(p["volume_mean"]).mean() * h * rank(
                h - c
            ) / h.rolling(p["high_mean"]).mean() - rank(span(w.diff(p["lag"]), p["lag"] + 1))
        elif n == 179:
            result = rank(corr(w, v, p["corr"])) * rank(
                _panel_rank_moment(
                    rank(l), rank(v.rolling(p["volume_mean"]).mean()), p["rank_corr"]
                )
            )
        elif n == 10:
            std = ret.rolling(p["volatility"]).std(ddof=1)
            value = std.where(ret.lt(0), c).where(std.notna())
            result = rank(value.pow(2).rolling(p["peak"]).max())
        elif n == 32:
            result = -rank(_panel_rank_moment(rank(h), rank(v), p["corr"])).rolling(p["sum"]).sum()
        elif n == 37:
            value = o.rolling(p["sum"]).sum() * ret.rolling(p["sum"]).sum()
            result = -rank(value.diff(p["lag"]).where(complete))
        elif n == 42:
            result = -rank(h.rolling(p["volatility"]).std(ddof=1)) * corr(h, v, p["corr"])
        elif n == 48:
            result = -rank(np.sign(c.diff()).rolling(p["direction"]).sum()) * (
                v.rolling(p["short"]).sum() / v.rolling(p["long"]).sum()
            )
        elif n == 62:
            result = -corr(h, rank(v), p["corr"])
        elif n in {83, 99}:
            result = -rank(
                _panel_rank_moment(
                    rank(h if n == 83 else c), rank(v), p["covariance"], covariance=True
                )
            )
        elif n == 91:
            result = -rank(c - c.rolling(p["peak"]).max()) * rank(
                corr(v.rolling(p["volume_mean"]).mean(), l, p["corr"])
            )
        elif n == 104:
            result = -corr(h, v, p["corr"]).diff(p["lag"]) * rank(
                c.rolling(p["volatility"]).std(ddof=1)
            )
        elif n == 105:
            result = -_panel_rank_moment(rank(o), rank(v), p["corr"])
        elif n == 107:
            result = (
                -rank((o - h.shift(p["lag"])).where(complete))
                * rank((o - c.shift(p["lag"])).where(complete))
                * rank((o - l.shift(p["lag"])).where(complete))
            )
        elif n == 113:
            result = (
                -rank(span(c.shift(p["lag"]).rolling(p["mean"]).mean(), p["lag"] + p["mean"]))
                * corr(c, v, p["corr"])
                * rank(corr(c.rolling(p["short"]).sum(), c.rolling(p["long"]).sum(), p["corr"]))
            )
        elif n == 115:
            base = rank(corr(0.9 * h + 0.1 * c, v.rolling(p["volume_mean"]).mean(), p["corr"]))
            exponent = rank(
                _panel_rank_moment(
                    trank((h + l) / 2, p["price_rank"]),
                    trank(v, p["volume_rank"]),
                    p["rank_corr"],
                    denominators=(2 * p["price_rank"], 2 * p["volume_rank"]),
                )
            )
            result = base.pow(exponent)
        elif n == 136:
            result = -rank(span(ret.diff(p["lag"]), p["lag"] + 2)) * corr(o, v, p["corr"])
        elif n == 142:
            result = (
                -rank(trank(c, p["price_rank"]))
                * rank(span(c.diff(p["lag"]).diff(p["lag"]), 2 * p["lag"] + 1))
                * rank(trank(v / v.rolling(p["volume_mean"]).mean(), p["volume_rank"]))
            )
        elif n == 148:
            left = rank(
                corr(o, v.rolling(p["volume_mean"]).mean().rolling(p["sum"]).sum(), p["corr"])
            )
            right = rank(o - o.rolling(p["trough"]).min())
            result = -left.lt(right).astype(float).where(left.notna() & right.notna())
        elif n == 176:
            bottom, top = l.rolling(p["range"]).min(), h.rolling(p["range"]).max()
            result = _panel_rank_moment(rank((c - bottom) / (top - bottom)), rank(v), p["corr"])
        elif n == 184:
            result = rank(corr((o - c).shift(p["lag"]), c, p["corr"]).where(complete)) + rank(o - c)
        else:
            raise ValueError(f"未实现复合股票池公式 {n}")
    computation_checkpoint()
    return result.where(complete & np.isfinite(result))


def definition_metadata(
    cls: type[GTJAFactor], instance: GTJAFactor | None = None
) -> dict[str, Any]:
    spec = (instance or cls()).spec
    defaults = cls.spec
    metadata = {
        "display_name": f"GTJA {spec.number:03d} · {spec.title}",
        "parameterized_title": f"GTJA {spec.number:03d} · {spec.title}",
        "library": "gtja191",
        "family": spec.family,
        "parameter_family": f"gtja191:{spec.family}",
        "source": SOURCE,
        "source_commit": SOURCE_COMMIT,
        "source_license": "Apache-2.0（参考模块）；原始研报保留版权",
        "original_source": REPORT,
        "formula": spec.formula,
        "implementation_version": VERSION,
        "warmup_bars": spec.warmup,
        "warmup_multiplier": spec.multiplier,
        "warmup_offset": spec.offset,
        "warmup_note": (
            "warmup_bars仅为理论最少根数；须积累w个有效基准下跌样本。非下跌日保持最近样本估计，缺失重置，不自动扩展历史。"
            if spec.number == 149
            else (
                "至少2根连续有效收盘价；首根种子1不发布，断档重置。"
                "此后依赖完整输入起点，不是2根滚动因子。"
            )
            if spec.number == 143
            else (
                "最少连续输入，不代表递归收敛；每层首个有限值作种子，"
                "满w根才向下一层输出，断档重置。"
            )
            if spec.recursive or spec.family.startswith("sma_")
            else "完整依赖窗口；缺失、非法价格、零分母不填零。"
        ),
        "resolved_parameters": spec.resolved_parameters,
        "parameters": {
            "window": {
                "default": defaults.window,
                "value": spec.window,
                "editable": True,
                "min": _minimum_window(spec),
                "max": 600 // spec.multiplier,
                "unit": "selected_observations" if spec.number == 149 else "bars",
                "label": "基准下跌样本数"
                if spec.number == 149
                else "基础窗口"
                if spec.multiplier == 8
                else "窗口",
            }
        }
        if spec.window is not None
        else {},
        "status": "available",
        "implemented": True,
        "available": not spec.panel,
        "evaluation_available": True,
        "unavailable_reason": "需要股票池截面检验" if spec.panel else "",
        "evaluation_unavailable_reason": "",
        "data_requirements": list(spec.inputs),
        "adjustment_unavailable_reason": (
            "VWAP仅支持不复权：需同根实际成交额与实际股数；不能用收盘价或复权比例替代"
            if "vwap" in spec.inputs
            else ""
        ),
        "supported_adjustments": ["NONE"] if "vwap" in spec.inputs else ["NONE", "QFQ", "HFQ"],
        "limitations": [
            "GTJA191 完整窗口适配；不是逐位复现参考软件。未实现编号不登记为可选项。",
            "原始公式以日线定义；分钟线窗口按 K 线根数解释，不自动换算成交易日。",
            "自定义窗口是原公式参数扩展，不增加标准因子数；均线组保持 1:2:4:8 倍数。",
            "STD 明确使用样本标准差；截面排名为平均并列序号／有效数量，至少两只有效标的。",
            "006 的加权价格符号用输入浮点数往返十进制值比较，避免浮点消减噪音将相等值拆成涨跌。",
            "049—051 与128的价格和方向使用往返十进制比较；相等不计为上涨或下跌。",
            "成交量 V 为已核验的实际股数，不随价格复权逆向缩放；三价均值乘量不等于实际成交额。",
            *(
                {
                    146: [
                        "原表分母SMA省略权重m；本App明确采用m=1，保留分子当期偏离乘数。参考模块省略该乘数并用有限均值作分母的差异未沿用，不宣称唯一原文解释。",
                        "两层SMA各自首值初始化、完整预热、断档重置；递归结果依赖输入起点。",
                    ],
                    165: [
                        "原表SUMAC和单参数MAX/MIN省略范围；本App明确采用最近w根偏离的窗口内前缀累加，再求这些前缀的最大最小值，不含初始0，不跨股票。",
                        "保留原式运算优先级：max−min/std，不是(max−min)/std，不是标准R/S。默认48根；这是公开解释口径，不宣称原文唯一或与参考模块相等。",
                    ],
                    183: [
                        "与165相同的明确解释：最近w根偏离的窗口内前缀累加，不含初始0，不跨股票；max−min/std，不是(max−min)/std。",
                        "默认24根；原表省略的累计及极值范围均取w，非唯一原文解释，不宣称与参考模块相等。",
                    ],
                    166: [
                        "原表分母价格比后有悬空窗口参数；明确采用参考模块的MEAN(价格比,w)解释。分子保留一次偏离累计，不补三次方，不是常规偏度。",
                        "默认20根；系数中的20同步替换为w，w至少3；完整两层窗口，缺失重置。不是原文无歧义定义或逐位参考复现。",
                    ],
                    75: [
                        "必须显式选择独立基准指数；完整窗口内按收盘相对开盘判断，不比较前收。平盘不计上涨／下跌，指数下跌次数为0时缺失。"
                    ],
                    182: [
                        "必须显式选择独立基准指数；收盘相对开盘同涨或同跌才计数，双方均平盘也不计同向；分母为完整窗口根数。"
                    ],
                    149: [
                        "按原表FILTER先压缩为下跌样本，最近252个合格样本做带截距回归；参考模块mbeta以固定行情窗口接收空值的实现未沿用，不声称数值一致。",
                        "理论至少w+1根不代表就绪；实际需要足够下跌观测。非下跌日保持同一组样本的估计；缺失或非法价格清空样本。样本不足或指数收益方差为零时留空，不自动补数或改窗口。",
                    ],
                    181: [
                        "原式使用基准收盘价减自身均值的偏差，不是指数收益；分子是相减，不改成乘积。尺度依赖所选指数，不宜将不同指数数值视为同尺度。",
                        "原表分母SUM省略窗口；明确采用参考模块的20根，与分子共用可编辑窗口。分母是有符号三次方之和，精确为零或输出无法表示时留空。",
                    ],
                    143: [
                        "原报告仅定义SELF为前一期因子值，未规定种子；本App明确固定初始值1，与参考模块初始尺度一致，但首根不发布。没有可编辑窗口。",
                        "上涨时乘收益率本身，不是1加收益率；下跌或相等保持前值。非正、缺失或非有限价格重置，恢复后第二根才发布。",
                        "80位十进制内部状态；低于float64可表示范围或溢出时输出缺失，保留内部状态供后续恢复，不伪造0或截断至上下限。",
                        "数值通常快速趋近零；依赖完整历史起点，截短历史可改变重叠值。追加未来不改过去；研究比较须核对各股输入起点及断档，不视为收益净值。",
                    ],
                    28: [
                        "028保留原表两条不同分母：第一项减最低LOW，第二项减最高LOW；MAX(HIGH,range)按滚动最高价。不是通用KDJ的J值。参考模块的100位置及统一分母差异未沿用。"
                    ],
                    54: [
                        "054原表STD省略窗口；本App公开采用参考模块的10根默认，并提供独立body_std参数。不是原文唯一可确定的默认定义。"
                    ],
                    190: [
                        "190按原表保留下方平方项R−G−2、上方R−G；不是对称半方差。DELAY(C)解释为1根；严格大于／小于，等于两侧均不计。分母采用完整窗口下侧次数，不沿用参考模块的当根条件；两侧累计只统计满足条件项。"
                    ],
                }.get(spec.number, [])
            ),
            *(
                [
                    "007遵循因子表括号：先相加两个排名，再乘量变排名；固定参考模块漏括号的运算优先级未沿用。"
                ]
                if spec.number == 7
                else []
            ),
            *(
                [
                    "033按原表将长短收益和之差整体除以窗口差；固定参考代码仅除短项的括号差异未沿用。"
                    "实际等价累计已排除最近short根的较早收益，避免相近大累计值相减；仍要求完整long+1根。"
                ]
                if spec.number == 33
                else []
            ),
            *(
                [
                    "原报告算子表把MIN/MAX定义为两值比较，但本式使用MIN/MAX(序列,整数)，与窗口写法混用。"
                    "本App显式采用滚动窗口解释（TSMIN/TSMAX），不是逐项与常数比较；不声称歧义已有唯一原文结论。"
                ]
                if spec.number in {7, 17, 41, 64, 108, 119, 121, 154, 157}
                else []
            ),
            *(
                [
                    "159按原表保留C−累计低价（不是逐根差累计），长项系数保留short×long；HGIH解释为HIGH。"
                    "因此结果不限制0—100，也不是常见ULTOSC；短、中、长窗口必须严格递增。"
                ]
                if spec.number == 159
                else []
            ),
            *(
                [
                    "W为独立核验实际成交额/实际股数的VWAP，仅支持不复权；零成交量均价为空，不用收盘价替代。",
                    "R为同日明确股票池排名，TSRANK为本标的时序排名；DECAYLINEAR从旧到新使用1…w的归一权重。",
                    "114保留嵌套除法：W=C或H=L时未定义；154按原式比较价格差与相关系数，不额外归一化。",
                ]
                if "vwap" in spec.inputs
                else []
            ),
            *(
                [
                    "AMOUNT为实际成交额（元），不随价格复权缩放；不以V×收盘价或典型价替代。"
                    "零成交额可参与均值／标准差；条件除数为零则该窗口为空。"
                ]
                if "amount" in spec.inputs
                else []
            ),
            *(
                [
                    "004／038／098 条件比较使用输入往返十进制价格，完整窗口后才计算；"
                    "098的0.05边界包含等号。004若进入量比条件且均量为0，返回空值。"
                ]
                if spec.number in {4, 38, 98}
                else []
            ),
            *(
                [
                    "022 原报告写作SMEAN且无独立算子定义；按固定参考实现明确解释为SMA(X,12,1)，"
                    "采用本App公开种子与断档规则。"
                ]
                if spec.number == 22
                else []
            ),
            *(
                ["078 分母是收盘价C对典型价均值的绝对偏差，不替换为常见CCI的典型价偏差。"]
                if spec.number == 78
                else []
            ),
            *(
                [
                    "055／137 保留原报告的完整前实体C前−O前，不额外除2；"
                    "两个严格大于分支不含等号，并列进入第三分支。"
                ]
                if spec.number in {55, 137}
                else []
            ),
            *(
                [
                    "144 只统计下跌根；无下跌时分母0，返回空值而非0。"
                    "非下跌根金额为0贡献0；下跌根金额为0使整个统计窗口无效。"
                ]
                if spec.number == 144
                else []
            ),
            *(
                [
                    "172／186 严格比较HD和LD，同幅时两方向均不计；"
                    "无方向变动或TR为0时为空，不把缺失当作0强度。"
                ]
                if spec.number in {172, 186}
                else []
            ),
            "数值正负不代表买卖建议，也不自动将负相关反向交易。",
            *(
                [
                    "001 的对数量变及实体收益排序使用等价的精确十进制输入比值，"
                    "保留比例相同的并列，避免对数相减噪声制造相关。"
                ]
                if spec.number == 1
                else []
            ),
            *(
                [
                    "R是同一观测时刻股票池排名，T/TSRANK是单股完整窗口时序排名，二者不能互换。",
                    "各层截面按本层有限值排名，至少2只；股票缺日期不填充、不压缩跨越缺口。"
                    "最终仍要求完整原始依赖窗口，因此各层参与数可能与最终覆盖数不同。",
                    "排名输入的相关／协方差按有理数精确矩计算，避免舍入噪音破坏数学并列；"
                    "原始价格不按容差合并，协方差用样本口径ddof=1，常数序列相关为缺失。",
                ]
                if spec.family.startswith("panel_")
                else []
            ),
            *(
                ["010 的条件分支统一等待收益标准差的完整窗口，不因当前收益非负提前产生排名。"]
                if spec.number == 10
                else []
            ),
            *(
                [
                    "SMA为Y=m/w×当前值+(1−m/w)×前Y；首个有限输入作种子，连续满w根才发布。",
                    "每层独立暖机；缺失、非法值或非有限中间值重置状态，不跨缺口递推。最少根数不等于收敛。",
                    "递归结果依赖输入历史起点；截短历史可能改变重叠日期值，追加未来数据不改变既有值。原档保留完整输入。",
                    "原报告未规定种子与断档策略；此处为明确的完整窗口适配，不宣称参考软件逐位等价。",
                ]
                if spec.recursive or spec.family.startswith("sma_")
                else []
            ),
            *(["081 按原报告使用2/w，不采用参考模块的1/21。"] if spec.number == 81 else []),
            *(
                ["027 使用原报告算子表的归一化指数权重0.9^i，不使用参考模块的线性权重。"]
                if spec.number == 27
                else []
            ),
            *(
                [
                    "089／155 短、长平滑均独立作用于原始序列，"
                    "不沿用参考模块将长平滑作用于短平滑结果的写法。"
                ]
                if spec.number in {89, 155}
                else []
            ),
            *(
                [
                    "TSRANK 明确采用最近完整窗口内当前值的平均并列升序名次／窗口长度，"
                    "范围为1/n至1；不是股票池截面排名。"
                    "原报告未明确并列与归一口径，此为公开适配约定。"
                ]
                if spec.number in {5, 85, 115, 117, 142, 180}
                else []
            ),
            *(
                [
                    "180 两条件分支单位不同：放量为无量纲排名，否则为负成交股数；"
                    "保留原公式，不额外标准化。所有分支均等完整依赖窗口，不因当前条件缩短预热。"
                ]
                if spec.number == 180
                else []
            ),
            *(
                [
                    "173 按原报告第三项使用log(C)，不采用参考模块三项均为C的写法。"
                    "价格项与对数项不作额外单位归一。"
                ]
                if spec.number == 173
                else []
            ),
            *(
                {
                    "mean_slope": [
                        "021 使用原报告的均价回归，不沿用参考模块遗漏均价的实现；"
                        "含截距，斜率不除以价格。"
                    ],
                    "peak_deviation_rms": [
                        "127 原表外层均值未写窗口；本适配明确采用参考实现的12根（自定义时同w），"
                        "MAX解释为滚动峰值。"
                    ],
                    "low_recency": ["极值并列时取最近一次；距离按0起算，不按1起算。"],
                    "high_recency": ["极值并列时取最近一次；距离按0起算，不按1起算。"],
                    "extreme_recency_balance": ["极值并列时取最近一次；距离按0起算，不按1起算。"],
                    "body_range_power": [
                        "等价计算先取开收比，避免对价格直接五次幂溢出；收盘等于最高时缺失。"
                    ],
                    "price_acceleration_switch": [
                        "固定阈值0.25使用价格单位，不解释为25%；自定义w同步改变两段距离及除数。",
                        "0及0.25边界以输入价格的往返十进制值比较，避免浮点误差切换条件分支。",
                    ],
                    "range_close_ratio": [
                        "两项相同平滑值在代数上相消；不递归计算与输出无关的平滑状态。"
                    ],
                }.get(spec.family, [])
            ),
        ],
    }
    if spec.windows:
        default_windows = {w.key: w for w in defaults.windows}
        metadata["parameters"] = {
            w.key: {
                "default": default_windows[w.key].value,
                "value": w.value,
                "editable": True,
                "min": w.minimum,
                "max": 600,
                "integer": True,
                "unit": w.unit,
                "label": w.label,
            }
            for w in spec.windows
        }
        metadata["warmup_terms"] = [
            {"offset": offset, "windows": list(keys)} for offset, keys in spec.warmup_terms
        ]
        metadata["warmup_limit"] = 600
        metadata.pop("warmup_multiplier")
        metadata.pop("warmup_offset")
    if spec.number == 30:
        reason = (
            "需接入有授权、明确构建口径及历史发布时间的A股MKT、SMB、HML；当前网页尚无合格数据源"
        )
        metadata.update(
            {
                "status": "needs_data",
                "available": False,
                "evaluation_available": False,
                "unavailable_reason": reason,
                "evaluation_unavailable_reason": reason,
                "supported_categories": ["DAY"],
                "period_unit": "daily_observations",
            }
        )
        metadata["limitations"] = [
            "仅支持日线；当前仅内核及冻结数据契约已实现，网页计算与检验不可用，不增加页面可用数量。",
            "完整60根收益回归，带截距；每次取当根样本内残差平方，20根归一指数权重0.9^i；最少80根价格。",
            "原表未明示截距与残差选取方式，此处为明确的工程约定，不宣称唯一解释或逐位复现参考软件。",
            "回归列先中心化及按列缩放；奇异值比≤1e−12的病态或秩不足窗口留空，不改用岭回归或删列；80位十进制求解。",
            "风险因子需同日且收盘时已可得；迟发或修订数据不能回填预测历史。缺失、异常、奇异窗口打断平滑；完整重新预热。",
            "不将未复权／前复权／后复权收益混用；无风险收益只属于MKT输入定义，个股被解释变量沿用原式价格收益。",
            "数值为残差平方的加权量，不是买卖建议；常数股价配合满秩风险因子可得真实零，数值上下溢留空。",
        ]
    return metadata


for _spec in SPECS.values():
    register_factor(
        type(
            f"GTJA191{_spec.number:03d}",
            (GTJAPanelFactor if _spec.panel else GTJAFactor,),
            {
                "__module__": __name__,
                "name": f"gtja191_{_spec.number:03d}",
                "category": "volume"
                if {"volume", "amount"}.intersection(_spec.inputs)
                else "technical",
                "description": f"GTJA191 {_spec.number:03d} · {_spec.title}",
                "inputs": _spec.inputs,
                "spec": _spec,
            },
        )
    )
