"""分型识别。

顶分型：中间 K 线的高点和低点均为三根中最高。
底分型：中间 K 线的高点和低点均为三根中最低。

严格模式下不允许相等（使用 > 而非 >=）。
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import FX, CLKline, FXType


def find_fractals(
    cklines: list[CLKline],
    config: ChanlunConfig | None = None,
) -> list[FX]:
    """从缠论 K 线列表中识别分型。

    扫描每三根相邻的缠论 K 线，判断是否构成顶分型或底分型。

    Args:
        cklines: 合并后的缠论 K 线列表
        config: 缠论配置（默认使用 ChanlunConfig()）

    Returns:
        分型列表，按时间顺序排列
    """
    if config is None:
        config = ChanlunConfig()

    if len(cklines) < 3:
        return []

    fxs: list[FX] = []

    for i in range(len(cklines) - 2):
        left = cklines[i]
        mid = cklines[i + 1]
        right = cklines[i + 2]

        if config.fx_strict:
            # 严格模式：中间 K 线的高/低必须严格大于/小于两边
            is_ding = (
                mid.high > left.high
                and mid.high > right.high
                and mid.low > left.low
                and mid.low > right.low
            )
            is_di = (
                mid.low < left.low
                and mid.low < right.low
                and mid.high < left.high
                and mid.high < right.high
            )
        else:
            # 非严格模式：允许等于
            is_ding = (
                mid.high >= left.high
                and mid.high >= right.high
                and mid.low >= left.low
                and mid.low >= right.low
            )
            is_di = (
                mid.low <= left.low
                and mid.low <= right.low
                and mid.high <= left.high
                and mid.high <= right.high
            )

        if is_ding and is_di:
            # 同时满足顶底分型条件（如十字星），跳过
            continue
        elif is_ding:
            fx = FX(
                fx_type=FXType.DING,
                k=mid,
                klines=[left, mid, right],
                val=mid.high,
                index=len(fxs),
                done=True,
            )
            fxs.append(fx)
        elif is_di:
            fx = FX(
                fx_type=FXType.DI,
                k=mid,
                klines=[left, mid, right],
                val=mid.low,
                index=len(fxs),
                done=True,
            )
            fxs.append(fx)

    return fxs
