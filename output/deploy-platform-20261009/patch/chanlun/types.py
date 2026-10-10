"""缠论核心数据结构定义。

参考 chanlun-pro cl_interface.py，去除对 db/exchange 的依赖，
使用纯 dataclass + 类型注解，保持 mypy strict 兼容。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# ── K 线 ──────────────────────────────────────────────────────────────────


@dataclass
class Kline:
    """原始 K 线。"""

    index: int
    date: datetime
    open: float
    close: float
    high: float
    low: float
    amount: float  # 成交量（股数）
    is_closed: bool = True  # Historical callers supply completed candles by default.

    def __str__(self) -> str:
        return (
            f"Kline(i={self.index} {self.date:%Y-%m-%d} "
            f"o={self.open:.2f} c={self.close:.2f} "
            f"h={self.high:.2f} l={self.low:.2f})"
        )


@dataclass
class CLKline:
    """缠论 K 线（包含处理后的合并 K 线）。"""

    k_index: int  # 对应原始 K 线中最后一根的 index
    date: datetime  # 合并 K 线最后一根的时间
    open: float
    close: float
    high: float
    low: float
    amount: float
    index: int = 0  # 在缠论 K 线列表中的序号
    merged_count: int = 1  # 合并了几根原始 K 线
    has_gap: bool = False  # 是否有缺口
    direction: str = ""  # 合并方向 "up" / "down" / ""
    klines: list[Kline] = field(default_factory=list)  # 包含的原始 K 线

    def __str__(self) -> str:
        return (
            f"CLKline(i={self.index} ki={self.k_index} {self.date:%Y-%m-%d} "
            f"h={self.high:.2f} l={self.low:.2f} n={self.merged_count})"
        )


# ── 分型 ──────────────────────────────────────────────────────────────────


class FXType(str, Enum):
    """分型类型。"""

    DING = "ding"  # 顶分型
    DI = "di"  # 底分型


@dataclass
class FX:
    """分型对象。"""

    fx_type: FXType
    k: CLKline  # 分型中间那根缠论 K 线
    klines: list[CLKline]  # 构成分型的三根缠论 K 线 [左, 中, 右]
    val: float  # 分型值（顶分型取 high，底分型取 low）
    index: int = 0  # 分型序号
    done: bool = True  # 分型是否完成

    def __str__(self) -> str:
        return f"FX(i={self.index} {self.fx_type.value} {self.k.date:%Y-%m-%d} val={self.val:.2f})"


# ── 线（笔/线段基类）─────────────────────────────────────────────────────


class Direction(str, Enum):
    """方向。"""

    UP = "up"
    DOWN = "down"


@dataclass
class Line:
    """线的基本定义，笔和线段的基类。"""

    start: FX  # 起始分型
    end: FX  # 结束分型
    direction: Direction  # 方向
    index: int = 0  # 序号
    high: float = 0.0  # 区间最高价
    low: float = 0.0  # 区间最低价

    def is_done(self) -> bool:
        """线是否完成（结束分型已完成）。"""
        return self.end.done

    def __str__(self) -> str:
        return (
            f"Line(i={self.index} {self.direction.value} "
            f"{self.start.k.date:%Y-%m-%d}→{self.end.k.date:%Y-%m-%d} "
            f"h={self.high:.2f} l={self.low:.2f})"
        )


@dataclass
class BI(Line):
    """笔。"""

    # Stabilised by the first valid opposite pen; None denotes the mutable tail.
    confirmed_index: int | None = None


@dataclass
class XD(Line):
    """线段。"""

    lines: list[BI] = field(default_factory=list)
    confirmed_index: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


# ── 中枢 ──────────────────────────────────────────────────────────────────


@dataclass
class ZS:
    """中枢对象。"""

    lines: list[BI | XD] = field(default_factory=list)  # 构成中枢的线
    zg: float = 0.0  # 中枢上沿（重叠区间最高）
    zd: float = 0.0  # 中枢下沿（重叠区间最低）
    gg: float = 0.0  # 中枢最高点
    dd: float = 0.0  # 中枢最低点
    direction: str = ""  # 中枢方向 "up"/"down"/""
    index: int = 0  # 序号
    done: bool = False  # 中枢是否完成
    start: FX | None = None  # 起始分型
    end: FX | None = None  # 结束分型

    def add_line(self, line: BI | XD) -> None:
        self.lines.append(line)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def __str__(self) -> str:
        return (
            f"ZS(i={self.index} lines={self.line_count} "
            f"zg={self.zg:.2f} zd={self.zd:.2f} "
            f"gg={self.gg:.2f} dd={self.dd:.2f} "
            f"done={self.done})"
        )


# ── 买卖点 / 背驰 ─────────────────────────────────────────────────────────


class MMDType(str, Enum):
    """买卖点类型。"""

    BUY_1 = "1buy"
    BUY_2 = "2buy"
    BUY_3 = "3buy"
    SELL_1 = "1sell"
    SELL_2 = "2sell"
    SELL_3 = "3sell"


@dataclass
class MMD:
    """买卖点。"""

    mmd_type: MMDType
    zs: ZS | None = None
    bi: BI | XD | None = None  # 图形锚点；新结构模式使用已确认线段
    msg: str = ""
    confirmed_index: int | None = None
    source: str = "legacy_pen_proxy"
    evidence: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"MMD({self.mmd_type.value} {self.msg})"


class BCType(str, Enum):
    """背驰类型。"""

    BI = "bi"  # 笔背驰
    PZ = "pz"  # 盘整背驰
    QS = "qs"  # 趋势背驰
    MACD = "macd"  # 指标背离，不等同于趋势背驰
    MACD_WAVE = "macd_wave"  # 同向柱波段面积背离
    MACD_WAVE_NONSTANDARD = "macd_wave_nonstandard"  # 面积与 DIF，独立于标准双线条件
    MACD_WAVE_SPECIAL = "macd_wave_special"  # B 色柱内突破 A，等待反向笔


@dataclass
class BC:
    """背驰。"""

    bc_type: BCType
    bc: bool = False  # 是否背驰
    zs: ZS | None = None
    curr: BI | XD | None = None  # 当前背驰笔/线段（用于可视化锚定日期）
    prev: BI | XD | None = None  # 前一同向笔/线段（力度对照基准）
    msg: str = ""
    signal_index: int | None = None
    reference_index: int | None = None
    detected_index: int | None = None
    confirmed_index: int | None = None
    status: str = "confirmed"
    direction: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    # Indicator observations keep preliminary knowledge separate from finality.
    preliminary_index: int | None = None
    invalidated_index: int | None = None
    failure_reason: str = ""
    failure_audit: dict[str, Any] = field(default_factory=dict)
    related_events: list[dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:
        return f"BC({self.bc_type.value} {self.bc})"
