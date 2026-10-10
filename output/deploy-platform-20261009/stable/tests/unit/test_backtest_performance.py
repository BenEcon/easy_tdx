"""单元测试：绩效分析器。

测试 PerformanceAnalyzer 的各项指标计算。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.performance import PerformanceAnalyzer


def _make_equity_curve(n: int = 252, total_return: float = 0.1) -> pd.DataFrame:
    """创建测试用资金曲线。

    Args:
        n: bar 数量
        total_return: 总收益率（例如 0.1 表示 10%）

    Returns:
        包含 datetime, total, drawdown 的 DataFrame
    """
    # 计算每日收益率
    daily_ret = (1 + total_return) ** (1 / n) - 1

    # 生成权益曲线
    initial = 100000
    total = initial * np.cumprod(np.full(n, 1 + daily_ret))

    # 计算回撤
    peak = np.maximum.accumulate(total)
    drawdown = peak - total
    drawdown_pct = np.divide(drawdown, peak, out=np.zeros_like(drawdown), where=(peak != 0))

    return pd.DataFrame(
        {
            "datetime": np.arange(n),
            "total": total,
            "drawdown": drawdown,
            "drawdown_pct": drawdown_pct,
        }
    )


def _make_trades() -> pd.DataFrame:
    """创建测试用交易记录。

    Returns:
        包含 datetime, direction, pnl, cost_basis, rejected 的 DataFrame
        4 条交易: BUY@20240101, SELL@20240106(pnl=500), BUY@20240110, SELL@20240115(pnl=-500)

    注意：avg_win/avg_loss/max_win/max_loss 现为「单笔收益率」口径
    （= pnl / cost_basis）。此处 cost_basis=10000，故收益率 = pnl/10000。
    """
    return pd.DataFrame(
        {
            "datetime": [20240101, 20240106, 20240110, 20240115],
            "size": [100, 100, 100, 100],
            "direction": ["BUY", "SELL", "BUY", "SELL"],
            "pnl": [0, 500, 0, -500],
            "cost_basis": [0.0, 10000.0, 0.0, 10000.0],
            "rejected": [False, False, False, False],
        }
    )


def test_total_return() -> None:
    """测试总收益率计算。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 总收益率应接近 0.1（10%）
    assert abs(metrics["total_return"] - 0.1) < 0.01


def test_max_drawdown_never_exceeds_100_pct() -> None:
    """测试最大回撤永远不超过 100%（从峰值的跌幅）。"""
    # 模拟先涨 5 倍再腰斩的资金曲线
    total = np.concatenate(
        [
            np.linspace(100000, 600000, 126),  # 涨到 60 万
            np.linspace(600000, 300000, 126),  # 跌到 30 万
        ]
    )
    peak = np.maximum.accumulate(total)
    drawdown = peak - total
    drawdown_pct = np.divide(drawdown, peak, out=np.zeros_like(drawdown), where=(peak != 0))

    equity = pd.DataFrame(
        {
            "datetime": np.arange(252),
            "total": total,
            "drawdown": drawdown,
            "drawdown_pct": drawdown_pct,
        }
    )
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 最大回撤 = 从峰值跌 50%（30万 / 60万），不应超过 1.0
    assert 0.0 <= metrics["max_drawdown"] <= 1.0, (
        f"max_drawdown = {metrics['max_drawdown']:.2%}, should be in [0, 100%]"
    )
    assert abs(metrics["max_drawdown"] - 0.5) < 0.01


def test_max_drawdown_zero_when_monotonic() -> None:
    """测试单调递增时最大回撤接近 0。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 单调递增时回撤应很小（浮点误差）
    assert metrics["max_drawdown"] < 0.01


def test_sharpe_positive_for_profit() -> None:
    """测试正收益时夏普比率为正。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 正收益时夏普比率应大于 0
    assert metrics["sharpe"] > 0


def test_win_rate() -> None:
    """测试胜率计算。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 1 赢 1 输，胜率应接近 0.5
    assert abs(metrics["win_rate"] - 0.5) < 0.01


def test_total_trades() -> None:
    """测试总交易次数。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 只有 SELL 交易才算完整交易
    assert metrics["total_trades"] == 2


def test_empty_trades() -> None:
    """测试空交易记录。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = pd.DataFrame({"direction": [], "pnl": [], "rejected": []})

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 确认没有成交与无法计算成交比率是不同状态。
    assert metrics["total_trades"] == 0
    assert metrics["win_trades"] == 0
    assert metrics["lose_trades"] == 0
    assert np.isnan(metrics["win_rate"])
    assert np.isnan(metrics["profit_factor"])


def test_all_keys_present() -> None:
    """测试所有核心指标 + 别名键都存在。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    expected_keys = {
        "total_return",
        "annual_return",
        "max_drawdown",
        "max_dd_duration",
        "sharpe",
        "sortino",
        "calmar",
        "total_trades",
        "win_trades",
        "lose_trades",
        "rejected_trades",
        "win_rate",
        "profit_factor",
        "avg_win",
        "avg_loss",
        "max_win",
        "max_loss",
        "avg_holding_days",
        "volatility",
        # 别名键（issue #22：兼容 .get('sharpe_ratio') 等常见叫法）
        "sharpe_ratio",
        "start_cash",
        "end_value",
    }

    assert expected_keys.issubset(set(metrics.keys()))


def test_alias_keys_match_canonical() -> None:
    """issue #22: 别名键与标准键值一致。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    metrics = PerformanceAnalyzer(equity, trades).compute()

    assert metrics["sharpe_ratio"] == metrics["sharpe"]
    assert metrics["start_cash"] == pytest.approx(equity["total"].iloc[0])
    assert metrics["end_value"] == pytest.approx(equity["total"].iloc[-1])


def test_empty_equity_curve() -> None:
    """空资金曲线不能抹掉已知成交，也不能伪造零收益。"""
    equity = pd.DataFrame({"total": [], "drawdown": [], "drawdown_pct": []})
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    for key in ("total_return", "annual_return", "max_drawdown", "start_cash", "end_value"):
        assert np.isnan(metrics[key])
    assert metrics["total_trades"] == 2
    assert metrics["win_rate"] == 0.5
    assert metrics["avg_holding_days"] == 5
    # issue #22：数据不全时给出诊断提示（analyzer.diagnostic），而非静默全 0
    assert analyzer.diagnostic is not None
    assert isinstance(analyzer.diagnostic, str)


def test_single_point_equity_curve() -> None:
    """单点保留本金和成交，但不声称有收益区间。"""
    equity = pd.DataFrame({"total": [100000], "drawdown": [0], "drawdown_pct": [0.0]})
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    assert np.isnan(metrics["total_return"])
    assert metrics["start_cash"] == metrics["end_value"] == 100000
    assert metrics["total_trades"] == 2
    assert analyzer.diagnostic is not None


def test_profit_factor() -> None:
    """测试盈亏比计算。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 盈利 500，亏损 500，盈亏比应为 1.0
    assert abs(metrics["profit_factor"] - 1.0) < 0.01


def test_avg_win_and_loss() -> None:
    """测试平均盈亏计算（单笔收益率口径 = pnl / cost_basis）。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 1 笔盈利 500 / cost_basis 10000 = 0.05（5%）
    assert abs(metrics["avg_win"] - 0.05) < 0.001

    # 1 笔亏损 -500 / cost_basis 10000 = -0.05（-5%）
    assert abs(metrics["avg_loss"] - (-0.05)) < 0.001


def test_max_win_and_loss() -> None:
    """测试最大盈亏计算（单笔收益率口径 = pnl / cost_basis）。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 最大盈利收益率 = 500 / 10000 = 0.05
    assert abs(metrics["max_win"] - 0.05) < 0.001

    # 最大亏损收益率 = -500 / 10000 = -0.05
    assert abs(metrics["max_loss"] - (-0.05)) < 0.001


def test_annual_return() -> None:
    """测试年化收益率计算。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 252 天 10% 收益，年化收益率应接近 0.1
    assert abs(metrics["annual_return"] - 0.1) < 0.01


def test_volatility() -> None:
    """测试年化波动率计算。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 波动率应大于 0
    assert metrics["volatility"] > 0


def test_rejected_trades() -> None:
    """测试被拒绝交易计数。"""
    equity = _make_equity_curve(n=252, total_return=0.1)

    # 创建包含被拒绝交易的记录
    trades = pd.DataFrame(
        {
            "direction": ["BUY", "SELL", "SELL", "SELL"],
            "pnl": [0, 500, 0, -500],
            "rejected": [False, False, True, False],
        }
    )

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 应有 1 笔被拒绝的交易
    assert metrics["rejected_trades"] == 1


def test_win_trades_and_lose_trades_count() -> None:
    """测试盈亏交易计数。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 1 笔盈利，1 笔亏损
    assert metrics["win_trades"] == 1
    assert metrics["lose_trades"] == 1


def test_avg_holding_days_fifo() -> None:
    """测试平均持仓天数（FIFO 配对计算）。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # BUY@20240101 → SELL@20240106: 5 天
    # BUY@20240110 → SELL@20240115: 5 天
    # 平均 = (5 + 5) / 2 = 5.0
    assert metrics["avg_holding_days"] == 5.0


def test_avg_holding_days_weighted() -> None:
    """测试加权平均持仓天数（不同持仓期）。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = pd.DataFrame(
        {
            "datetime": [20240101, 20240111, 20240120, 20240123],
            "size": [100, 100, 100, 100],
            "direction": ["BUY", "SELL", "BUY", "SELL"],
            "pnl": [0, 500, 0, -200],
            "rejected": [False, False, False, False],
        }
    )

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # BUY@20240101 → SELL@20240111: 10 天
    # BUY@20240120 → SELL@20240123: 3 天
    # 平均 = (10 + 3) / 2 = 6.5
    assert metrics["avg_holding_days"] == 6.5


def test_avg_holding_days_no_datetime() -> None:
    """缺少成交时间不可伪造零天持仓。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    # 不含 datetime 列的交易记录
    trades = pd.DataFrame(
        {
            "direction": ["BUY", "SELL"],
            "pnl": [0, 500],
            "rejected": [False, False],
        }
    )

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    assert np.isnan(metrics["avg_holding_days"])


def test_avg_holding_days_only_buys() -> None:
    """没有平仓样本时持仓统计不可用。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = pd.DataFrame(
        {
            "datetime": [20240101, 20240105],
            "direction": ["BUY", "BUY"],
            "pnl": [0, 0],
            "rejected": [False, False],
        }
    )

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    assert np.isnan(metrics["avg_holding_days"])


def test_max_dd_duration() -> None:
    """测试最大回撤持续时间计算。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 单调递增时最大回撤持续时间应为 0
    assert metrics["max_dd_duration"] == 0


def test_sortino() -> None:
    """测试索提诺比率计算。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 正收益时索提诺比率应大于 0
    assert metrics["sortino"] > 0


def test_calmar() -> None:
    """测试卡玛比率计算。"""
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = _make_trades()

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 卡玛比率 = annual_return / max_drawdown
    # 由于 max_drawdown 很小，calmar 会很大
    assert metrics["calmar"] > 0


# ---------------------------------------------------------------------------
# 除零边界回归（审计复审 N2 / 首轮 #11）
#
# performance.py 在计算日收益率时对 total[:-1]==0 的位置做了 safe_prev 守卫
# （记为 NaN 后 np.isfinite 过滤），并对 total[0]==0 的总收益率做了 0.0 兜底。
# 若有人不慎改回旧的 np.diff(total)/total[:-1]，这些测试应当红灯。
# ---------------------------------------------------------------------------


def _metrics_from_total(values: list[float]) -> dict[str, float]:
    """从一组 total 值构造最小资金曲线并计算指标。"""
    total = np.array(values, dtype=float)
    peak = np.maximum.accumulate(total)
    # 与生产回测一致：drawdown = peak - total；drawdown_pct = drawdown / peak
    drawdown = peak - total
    drawdown_pct = np.divide(drawdown, peak, out=np.zeros_like(drawdown), where=(peak != 0))
    equity = pd.DataFrame(
        {
            "datetime": np.arange(len(total)),
            "total": total,
            "drawdown": drawdown,
            "drawdown_pct": drawdown_pct,
        }
    )
    return PerformanceAnalyzer(equity, _make_trades()).compute()


def test_metrics_handles_zero_intermediate_equity() -> None:
    """中间净值出现 0 时，日收益率除零不抛异常、返回有限值（审计复审 N2）。

    total=[100, 0, 105, 0, 110]：第 1、3 根前值为 0，旧实现 diff/total[:-1]
    会得到 inf，进而污染均值/方差计算或触发 RuntimeWarning。修复后这些位置
    被 safe_prev 记为 NaN 并由 isfinite 过滤。
    """
    metrics = _metrics_from_total([100, 0, 105, 0, 110])

    # 有效总收益/回撤/交易统计保留；净值归零后不能以删除收益样本的方式年化。
    finite_keys = {
        "total_return",
        "max_drawdown",
        "win_rate",
        "profit_factor",
    }
    for key in finite_keys:
        val = metrics[key]
        assert np.isfinite(val), f"{key} 不是有限值: {val}"
    for key in ("annual_return", "sharpe", "sortino", "calmar", "volatility"):
        assert np.isnan(metrics[key])


def test_metrics_handles_zero_first_equity() -> None:
    """首根净值为 0 时 total_return 兜底为 0.0 而非除零（审计复审 N2）。

    total[0]==0 时 (total[-1]/total[0]) - 1 会除零；修复后直接记 0.0。
    """
    metrics = _metrics_from_total([0, 100, 105, 110, 115])

    assert np.isnan(metrics["total_return"])
    assert np.isnan(metrics["max_drawdown"])
    assert metrics["total_trades"] == 2


def test_metrics_all_zero_equity_does_not_raise() -> None:
    """全 0 资金曲线不应产生 inf/nan，也不应抛异常（审计复审 N2 极端场景）。"""
    # total 全 0 → safe_prev 全 NaN → daily_ret 过滤后为空 → 走 _empty_metrics
    metrics = _metrics_from_total([0, 0, 0, 0, 0])

    assert np.isnan(metrics["total_return"])
    assert np.isnan(metrics["max_drawdown"])
    assert np.isnan(metrics["sharpe"])
    assert metrics["win_rate"] == 0.5


# ── 回归测试：交易统计语义修复 ───────────────────────────────────────────────


def test_avg_holding_days_crosses_month_boundary() -> None:
    """跨月持仓天数必须用真实日历日计算，而非 YYYYMMDD 整数差。

    回归守卫：旧实现 ``20240201 - 20240131 = 70``（整数差，错误），
    新实现解析为 date 后相减 = 1 天。
    """
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = pd.DataFrame(
        {
            "datetime": [20240131, 20240201],
            "size": [100, 100],
            "direction": ["BUY", "SELL"],
            "pnl": [0, 100],
            "cost_basis": [0.0, 10000.0],
            "rejected": [False, False],
        }
    )

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 1月31日 → 2月1日 = 1 个真实日历日（旧 bug 会得到 70）
    assert metrics["avg_holding_days"] == 1.0


def test_profit_factor_no_losing_trades_is_infinite() -> None:
    """全部盈利、无亏损交易时利润因子为正无穷，另存状态。

    回归守卫：旧实现在 ``len(lose_pnl)==0`` 时直接返回 0.0，
    与 100% 胜率并列显示时自相矛盾（胜率 100% 却盈亏比 0）。
    """
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = pd.DataFrame(
        {
            "datetime": [20240101, 20240106, 20240110, 20240115],
            "direction": ["BUY", "SELL", "BUY", "SELL"],
            "pnl": [0, 500, 0, 300],
            "cost_basis": [0.0, 10000.0, 0.0, 10000.0],
            "rejected": [False, False, False, False],
        }
    )

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    assert metrics["win_trades"] == 2
    assert metrics["lose_trades"] == 0
    assert np.isposinf(metrics["profit_factor"])
    assert analyzer.basis["metric_status"]["profit_factor"]["state"] == "positive_infinity"


def test_avg_win_unavailable_when_no_cost_basis_column() -> None:
    """trades 无 cost_basis 列时 avg_win/avg_loss/max_win/max_loss 应回退为 0.0。

    回归守卫：engine._trades_to_df 现会输出 cost_basis 列，但若上游构造的
    trades DataFrame 缺该列（如旧式直接拼装），不应抛 KeyError，应记 0.0。
    """
    equity = _make_equity_curve(n=252, total_return=0.1)
    trades = pd.DataFrame(
        {
            "datetime": [20240101, 20240106],
            "direction": ["BUY", "SELL"],
            "pnl": [0, 500],
            "rejected": [False, False],
        }
    )

    analyzer = PerformanceAnalyzer(equity, trades)
    metrics = analyzer.compute()

    # 缺成本基数不可伪造零收益。
    assert np.isnan(metrics["avg_win"])
    assert np.isnan(metrics["max_win"])
