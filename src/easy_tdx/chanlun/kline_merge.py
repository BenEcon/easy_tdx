"""K 线包含处理（合并）。

缠论 K 线合并规则：
1. 如果前一根 K 线方向向上，当前 K 线被包含时，取「高高」合并
2. 如果前一根 K 线方向向下，当前 K 线被包含时，取「低低」合并
3. 包含关系判定：K1.high >= K2.high AND K1.low <= K2.low
"""

from __future__ import annotations

from easy_tdx.chanlun.types import CLKline, Kline


def _is_included(a: CLKline, b: CLKline) -> bool:
    """判断 a 是否包含 b（a 的高低范围覆盖 b）。"""
    return a.high >= b.high and a.low <= b.low


def _to_clkline(k: Kline, index: int) -> CLKline:
    """将原始 Kline 转为 CLKline。"""
    return CLKline(
        k_index=k.index,
        date=k.date,
        open=k.open,
        close=k.close,
        high=k.high,
        low=k.low,
        amount=k.amount,
        index=index,
        merged_count=1,
        direction="",
        klines=[k],
    )


def merge_klines(klines: list[Kline]) -> list[CLKline]:
    """对原始 K 线列表进行包含处理，返回缠论 K 线列表。

    算法：
    1. 第一根 K 线直接转为缠论 K 线
    2. 后续每根 K 线与前一根缠论 K 线比较：
       a. 如果存在包含关系，根据前一根的方向合并（向上取高高，向下取低低）
       b. 如果不存在包含关系，作为新的缠论 K 线追加
    """
    if not klines:
        return []

    result: list[CLKline] = [_to_clkline(klines[0], index=0)]
    result[0].klines = [klines[0]]

    for i in range(1, len(klines)):
        k = klines[i]
        prev = result[-1]
        candidate = CLKline(
            k_index=k.index,
            date=k.date,
            open=k.open,
            close=k.close,
            high=k.high,
            low=k.low,
            amount=k.amount,
            klines=[k],
        )

        # 判断包含关系（双向判断：prev 包含 candidate 或 candidate 包含 prev）
        if _is_included(prev, candidate) or _is_included(candidate, prev):
            # 确定合并方向
            # 向上：prev.high > prev_prev.high
            if len(result) >= 2:
                direction = "up" if prev.high > result[-2].high else "down"
            else:
                # No preceding non-contained pair exists (lesson 65). Do not
                # invent direction from candle colour or backfill from future
                # bars. Restart the structural window at the current raw bar;
                # the analyser retains the complete original chart separately.
                result[0] = _to_clkline(k, index=0)
                continue

            if direction == "up":
                # 向上合并：取高高
                merged_high = max(prev.high, candidate.high)
                merged_low = max(prev.low, candidate.low)
            else:
                # 向下合并：取低低
                merged_high = min(prev.high, candidate.high)
                merged_low = min(prev.low, candidate.low)

            prev.high = merged_high
            prev.low = merged_low
            prev.k_index = k.index
            prev.date = k.date
            prev.merged_count += 1
            prev.direction = direction
            prev.klines.append(k)
            # 更新 open/close 为最后一根 K 线的值
            prev.open = k.open
            prev.close = k.close
            prev.amount += k.amount
        else:
            # 无包含关系，追加新缠论 K 线
            ck = _to_clkline(k, index=len(result))
            result.append(ck)

    return result
