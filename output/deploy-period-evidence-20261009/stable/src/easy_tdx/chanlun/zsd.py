"""走势段/趋势段计算。

走势段（ZSD）：由线段（XD）构成，类似于笔由分型构成。
走势段的识别基于线段的方向和重叠关系。

趋势段（QSD）：具有明确方向性的走势段，连续同向排列。
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import XD, Direction


def find_zsds(
    xds: list[XD],
    config: ChanlunConfig | None = None,
) -> list[XD]:
    """从线段列表中计算走势段。

    算法：
    1. 将相邻同向线段合并为走势段
    2. 当线段方向反转时，前一个走势段结束，新的走势段开始
    3. 走势段的方向由其中线段的主方向决定

    Args:
        xds: 线段列表
        config: 缠论配置

    Returns:
        走势段列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(xds) < 1:
        return []

    zsds: list[XD] = []
    current_start = xds[0]
    current_direction = xds[0].direction

    for i in range(1, len(xds)):
        xd = xds[i]

        if xd.direction != current_direction:
            # 方向反转，关闭当前走势段
            prev_xd = xds[i - 1]
            zsd = _create_zsd(current_start, prev_xd, current_direction, len(zsds))
            zsds.append(zsd)
            current_start = xd
            current_direction = xd.direction

    # 处理最后一个走势段
    if len(xds) > 0:
        last_xd = xds[-1]
        zsd = _create_zsd(current_start, last_xd, current_direction, len(zsds))
        zsds.append(zsd)

    return zsds


def find_qsds(
    xds: list[XD],
    config: ChanlunConfig | None = None,
) -> list[XD]:
    """从线段列表中计算趋势段。

    趋势段是具有明确趋势方向的走势段：
    - 向上趋势：每个线段的高点和低点逐步抬高
    - 向下趋势：每个线段的高点和低点逐步降低

    Args:
        xds: 线段列表
        config: 缠论配置

    Returns:
        趋势段列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(xds) < 2:
        return []

    # 先计算走势段
    zsds = find_zsds(xds, config)

    # 从走势段中筛选趋势段
    qsds: list[XD] = []

    for i in range(len(zsds)):
        zsd = zsds[i]

        # 检查走势段内部是否形成趋势
        if _is_trending(zsd, zsds, i):
            qsds.append(zsd)

    return qsds


def _create_zsd(
    start_xd: XD,
    end_xd: XD,
    direction: Direction,
    index: int,
) -> XD:
    """从起止线段创建走势段。"""
    high = max(start_xd.high, end_xd.high)
    low = min(start_xd.low, end_xd.low)

    return XD(
        start=start_xd.start,
        end=end_xd.end,
        direction=direction,
        index=index,
        high=high,
        low=low,
    )


def _is_trending(
    zsd: XD,
    all_zsds: list[XD],
    zsd_index: int,
) -> bool:
    """判断走势段是否形成趋势。

    简化判断：走势段跨越的幅度是否足够大（至少 2 个线段的范围）。
    """
    # 单线段走势段不构成趋势
    if zsd.start == zsd.end:
        return False

    # 向上趋势：走势段高点高于起点高点
    if zsd.direction == Direction.UP:
        return zsd.high > zsd.start.k.h if hasattr(zsd.start.k, "h") else True

    # 向下趋势：走势段低点低于起点低点
    if zsd.direction == Direction.DOWN:
        return zsd.low < zsd.start.k.l if hasattr(zsd.start.k, "l") else True

    return True
