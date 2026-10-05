"""笔计算。

笔的定义：
- 由相邻的顶底分型连接而成
- 顶→底 = 向下笔，底→顶 = 向上笔
- 新笔规则：两组三根分型之间至少有 1 根独立缠论 K 线（中间 K 线序号差 >= 4）
- 老笔规则：分型之间至少有 3 根缠论 K 线
- 简单笔规则：只要顶底交替即可
"""

from __future__ import annotations

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, FX, Direction, FXType


def _first_observable(fx: FX) -> int:
    """A right-hand merged candle establishes the fractal on its first raw bar.

    Later containment can extend that candle's k_index without postponing the
    already observable turn. Synthetic candles without provenance use k_index.
    """
    right = fx.klines[-1]
    return right.klines[0].index if right.klines else right.k_index


def _can_form_bi(
    start: FX,
    end: FX,
    config: ChanlunConfig,
) -> bool:
    """判断两个分型是否可以构成一笔。"""
    # 顶底必须交替
    if start.fx_type == end.fx_type:
        return False

    # A top must lie above the bottom, not merely occur later in time.
    top, bottom = (start, end) if start.fx_type == FXType.DING else (end, start)
    if top.k.high <= bottom.k.high or top.k.low <= bottom.k.low:
        return False
    if end.k.index <= start.k.index:
        return False

    # 分型之间缠论 K 线的间距
    # 分型由三根 K 线组成：[left, mid, right]
    # 两侧分型的端点不计入独立 K 线；共享 K 线时结果为负。
    gap = end.klines[0].index - start.klines[2].index - 1

    if config.bi_type == "new":
        # 新笔：至少1根独立K线
        return gap >= 1
    elif config.bi_type == "old":
        # 老笔：至少3根缠论K线在分型之间
        return gap >= 3
    else:
        # simple：只要顶底交替即可
        return True


def find_bis(
    fxs: list[FX],
    config: ChanlunConfig | None = None,
) -> list[BI]:
    """从分型列表中计算笔。

    维护交替的有效端点，再统一构造连接。未成笔的反向分型不冻结
    当前极值；更极端的同类分型替换共享端点时，前后笔同步更新。

    Args:
        fxs: 分型列表
        config: 缠论配置

    Returns:
        笔列表
    """
    if config is None:
        config = ChanlunConfig()

    if len(fxs) < 2:
        return []

    anchors = [fxs[0]]
    first_seen = [_first_observable(fxs[0])]
    for current in fxs[1:]:
        last = anchors[-1]
        if current.fx_type == last.fx_type:
            stronger = (current.val > last.val if current.fx_type == FXType.DING
                        else current.val < last.val)
            if stronger and (len(anchors) == 1 or _can_form_bi(anchors[-2], current, config)):
                anchors[-1] = current
        elif _can_form_bi(last, current, config):
            anchors.append(current)
            first_seen.append(_first_observable(current))

    return [BI(start=start, end=end,
               direction=Direction.UP if start.fx_type == FXType.DI else Direction.DOWN,
               index=i, high=max(start.val, end.val), low=min(start.val, end.val),
               confirmed_index=first_seen[i + 2] if i + 2 < len(first_seen) else None)
            for i, (start, end) in enumerate(zip(anchors, anchors[1:]))]
