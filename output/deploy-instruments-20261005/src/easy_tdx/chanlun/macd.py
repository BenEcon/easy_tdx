"""MACD 指标计算（纯 numpy 实现）。

MACD 由三部分组成：
- DIF（快线）: EMA(fast) - EMA(slow)
- DEA（慢线）: EMA(DIF, signal)
- HIST（柱状图）: 2 * (DIF - DEA)
"""

from __future__ import annotations


def calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, list[float]]:
    """计算 MACD 指标。

    Args:
        closes: 收盘价序列
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期

    Returns:
        {"dif": [...], "dea": [...], "hist": [...]}
    """
    n = len(closes)
    if n == 0:
        return {"dif": [], "dea": [], "hist": []}

    # EMA 计算
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)

    # DIF = EMA(fast) - EMA(slow)
    dif = [ema_fast[i] - ema_slow[i] for i in range(n)]

    # DEA = EMA(DIF, signal)
    dea = _calc_ema(dif, signal)

    # HIST = 2 * (DIF - DEA)
    hist = [2.0 * (dif[i] - dea[i]) for i in range(n)]

    return {"dif": dif, "dea": dea, "hist": hist}


def _calc_ema(data: list[float], period: int) -> list[float]:
    """计算指数移动平均线。

    EMA(t) = price(t) * k + EMA(t-1) * (1 - k)
    k = 2 / (period + 1)
    """
    n = len(data)
    if n == 0:
        return []

    k = 2.0 / (period + 1)
    result = [0.0] * n

    # 初始值：第一个数据点
    result[0] = data[0]

    for i in range(1, n):
        result[i] = data[i] * k + result[i - 1] * (1 - k)

    return result


def calc_macd_force(
    closes: list[float],
    start_idx: int,
    end_idx: int,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, float]:
    """计算区间内的 MACD 力度（用于背驰判断）。

    Args:
        closes: 完整收盘价序列
        start_idx: 起始索引
        end_idx: 结束索引（含）
        fast, slow, signal: MACD 参数

    Returns:
        {"hist_sum": 总柱子面积, "hist_up_sum": 红柱总和, "hist_down_sum": 绿柱总和}
    """
    if start_idx > end_idx or end_idx >= len(closes):
        return {"hist_sum": 0.0, "hist_up_sum": 0.0, "hist_down_sum": 0.0}

    macd = calc_macd(closes, fast, slow, signal)
    hist_slice = macd["hist"][start_idx : end_idx + 1]

    hist_abs = [abs(h) for h in hist_slice]
    hist_up = [h for h in hist_slice if h > 0]
    hist_down = [h for h in hist_slice if h < 0]

    return {
        "hist_sum": sum(hist_abs),
        "hist_up_sum": sum(hist_up),
        "hist_down_sum": abs(sum(hist_down)),
    }
