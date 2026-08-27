"""线段计算。

线段定义：
- 由至少3笔构成
- 特征序列：将笔的高低点转化为特征序列
- 特征序列分型：判断线段的转折
- 简化实现：使用笔的方向和重叠关系判断线段
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, XD, Direction


def find_xds(
    bis: list[BI],
    config: ChanlunConfig | None = None,
) -> list[XD]:
    """从笔列表中计算线段。

    简化算法（基于中枢）：
    1. 将笔序列划分为线段，每个线段对应一个中枢的形成和离开
    2. 从第一笔开始，累积笔直到形成中枢（至少3笔有重叠）
    3. 当后续笔离开中枢时，关闭当前线段，开始新线段

    Args:
        bis: 笔列表
        config: 缠论配置

    Returns:
        线段列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(bis) < 3:
        return []

    xds: list[XD] = []

    # 简化线段划分：使用笔的重叠区域判断
    # 每个线段至少包含3笔（形成一个中枢）
    i = 0
    while i < len(bis):
        # 尝试从第 i 笔开始寻找线段
        xd_found = False

        # 从3笔开始尝试，逐步扩展
        for end_offset in range(3, len(bis) - i + 1):
            segment_bis = bis[i : i + end_offset]

            # 检查这段笔是否构成有意义的线段
            # 条件：中间的笔有价格重叠（类似中枢），且最后一笔离开重叠区
            if _forms_xd(segment_bis, config):
                xd = _create_xd(segment_bis, len(xds))
                xds.append(xd)
                # 当前线段终点是最后一笔的 end；下一条线段应从下一笔开始，
                # 其 start 正好与当前终点是同一个分型。旧逻辑回退一笔后，
                # 新线段会从“最后一笔的起点”开始，时间早于上一线段终点，
                # 不仅造成区间重叠，前端连线时也会出现明显回折。
                i += end_offset
                xd_found = True
                break

        if not xd_found:
            i += 1

    return xds


def _forms_xd(bis: list[BI], config: ChanlunConfig) -> bool:
    """判断一组笔是否构成线段。

    简化条件：
    1. 至少3笔
    2. 中间的笔有价格重叠区域（类似中枢）
    3. 最后一笔与重叠区有明确的方向性突破
    """
    if len(bis) < 3:
        return False

    # 计算中间笔的重叠区域（排除第一笔和最后一笔）
    inner_bis = bis[1:-1]
    if not inner_bis:
        return False

    # 重叠区域
    overlap_high = min(bi.high for bi in inner_bis)
    overlap_low = max(bi.low for bi in inner_bis)

    if overlap_high <= overlap_low:
        return False

    # 第一笔的方向决定线段的主方向
    main_direction = bis[0].direction

    # 最后一笔应该离开重叠区域
    last_bi = bis[-1]
    if main_direction == Direction.UP:
        # 向上线段：最后一笔应向上突破
        return last_bi.high > overlap_high
    else:
        # 向下线段：最后一笔应向下跌破
        return last_bi.low < overlap_low


def _create_xd(bis: list[BI], index: int) -> XD:
    """从一组笔创建线段。"""
    start_bi = bis[0]
    end_bi = bis[-1]

    # 线段方向由第一笔的方向决定
    direction = start_bi.direction

    # 但如果第一笔向下，最后一笔向上，需要根据整体走势判断
    if end_bi.direction == Direction.UP and end_bi.high > start_bi.high:
        direction = Direction.UP
    elif end_bi.direction == Direction.DOWN and end_bi.low < start_bi.low:
        direction = Direction.DOWN

    high = max(bi.high for bi in bis)
    low = min(bi.low for bi in bis)

    return XD(
        start=start_bi.start,
        end=end_bi.end,
        direction=direction,
        index=index,
        high=high,
        low=low,
    )
