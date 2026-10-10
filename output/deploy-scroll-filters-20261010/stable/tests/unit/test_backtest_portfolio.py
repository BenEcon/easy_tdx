"""回测引擎持仓追踪器单元测试。"""

from __future__ import annotations

import pandas as pd

from easy_tdx.backtest.portfolio import PortfolioTracker
from easy_tdx.backtest.types import Trade


def _make_df(n: int = 10) -> pd.DataFrame:
    """创建测试用 DataFrame。

    Args:
        n: bar 数量

    Returns:
        包含 close 和 datetime 列的 DataFrame
    """
    close = [100.0] * 5 + [110.0] * 5
    close = close[:n]
    datetime = list(range(20240101, 20240101 + n))

    return pd.DataFrame({"close": close, "datetime": datetime})


def test_initial_state() -> None:
    """测试初始状态。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df, initial_cash=100000)

    assert tracker.initial_cash == 100000


def test_buy_then_sell() -> None:
    """测试买入再卖出。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df, initial_cash=100000)

    # bar 0 买入 100 股 @100，手续费 5
    buy_trade = Trade(
        datetime=20240101,
        direction="BUY",
        size=100,
        price=100.0,
        commission=5.0,
        slippage=0.0,
    )

    # bar 5 卖出 100 股 @110，手续费 11
    sell_trade = Trade(
        datetime=20240106,
        direction="SELL",
        size=100,
        price=110.0,
        commission=11.0,
        slippage=0.0,
    )

    tracker.apply_trades([buy_trade, sell_trade])

    equity = tracker.equity_curve
    final_cash = equity["cash"].iloc[-1]

    # 最终现金 = 100000 - 10000 - 5 + 11000 - 11 = 100984
    expected = 100984.0
    assert abs(final_cash - expected) < 1.0, f"Expected {expected}, got {final_cash}"


def test_drawdown_calculation() -> None:
    """测试回撤计算（无交易时回撤全为 0）。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df, initial_cash=100000)

    tracker.apply_trades([])

    equity = tracker.equity_curve

    # 无交易时，总资产应保持不变，回撤为 0
    assert (equity["drawdown"] == 0).all()
    assert (equity["drawdown_pct"] == 0).all()


def test_equity_curve_columns() -> None:
    """测试资金曲线列名。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df)

    tracker.apply_trades([])
    equity = tracker.equity_curve

    expected_cols = {"datetime", "cash", "position_value", "total", "drawdown", "drawdown_pct"}
    assert set(equity.columns) == expected_cols


def test_position_tracking() -> None:
    """测试持仓追踪。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df)

    # bar 0 买入 100 股
    buy_trade = Trade(
        datetime=20240101,
        direction="BUY",
        size=100,
        price=100.0,
        commission=5.0,
        slippage=0.0,
    )

    tracker.apply_trades([buy_trade])
    positions = tracker.positions

    # 买入后持仓应为 100，并持续到最后
    assert positions["size"].iloc[0] == 100
    assert positions["size"].iloc[-1] == 100
    assert (positions["size"].iloc[1:] == 100).all()


def test_avg_price_update() -> None:
    """测试均价更新。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df)

    # bar 0 买入 100 股 @100
    buy1 = Trade(
        datetime=20240101,
        direction="BUY",
        size=100,
        price=100.0,
        commission=0.0,
        slippage=0.0,
    )

    # bar 1 再买入 50 股 @110
    buy2 = Trade(
        datetime=20240102,
        direction="BUY",
        size=50,
        price=110.0,
        commission=0.0,
        slippage=0.0,
    )

    tracker.apply_trades([buy1, buy2])
    positions = tracker.positions

    # 均价 = (100*100 + 50*110) / 150 = 103.33
    expected_avg = (100 * 100 + 50 * 110) / 150
    assert abs(positions["avg_price"].iloc[1] - expected_avg) < 0.01


def test_sell_clears_position() -> None:
    """测试卖出清空持仓。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df)

    buy = Trade(
        datetime=20240101,
        direction="BUY",
        size=100,
        price=100.0,
        commission=0.0,
        slippage=0.0,
    )

    sell = Trade(
        datetime=20240102,
        direction="SELL",
        size=100,
        price=110.0,
        commission=0.0,
        slippage=0.0,
    )

    tracker.apply_trades([buy, sell])
    positions = tracker.positions

    # 卖出后持仓应为 0
    assert positions["size"].iloc[0] == 100
    assert positions["size"].iloc[1] == 0
    assert positions["avg_price"].iloc[1] == 0


def test_position_market_value() -> None:
    """测试持仓市值计算。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df)

    buy = Trade(
        datetime=20240101,
        direction="BUY",
        size=100,
        price=100.0,
        commission=0.0,
        slippage=0.0,
    )

    tracker.apply_trades([buy])
    positions = tracker.positions

    # 前 5 个 bar 价格 100，后 5 个 bar 价格 110
    assert positions["market_value"].iloc[0] == 100 * 100
    assert positions["market_value"].iloc[5] == 100 * 110


def test_unrealized_pnl() -> None:
    """测试未实现盈亏计算。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df)

    buy = Trade(
        datetime=20240101,
        direction="BUY",
        size=100,
        price=100.0,
        commission=0.0,
        slippage=0.0,
    )

    tracker.apply_trades([buy])
    positions = tracker.positions

    # 前 5 个 bar 价格 100，盈亏为 0
    assert positions["unrealized_pnl"].iloc[0] == 0

    # 后 5 个 bar 价格 110，盈亏为 (110-100)*100 = 1000
    assert positions["unrealized_pnl"].iloc[5] == 1000


def test_rejected_trade_ignored() -> None:
    """测试被拒绝的交易不产生影响。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df, initial_cash=100000)

    rejected_buy = Trade(
        datetime=20240101,
        direction="BUY",
        size=100,
        price=100.0,
        commission=0.0,
        slippage=0.0,
        rejected=True,
    )

    tracker.apply_trades([rejected_buy])
    equity = tracker.equity_curve

    # 现金应保持不变
    assert (equity["cash"] == 100000).all()
    assert (tracker.positions["size"] == 0).all()


def test_commission_and_slippage() -> None:
    """测试手续费和滑点扣减。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df, initial_cash=10000)

    buy = Trade(
        datetime=20240101,
        direction="BUY",
        size=100,
        price=100.0,
        commission=10.0,
        slippage=5.0,
    )

    tracker.apply_trades([buy])
    equity = tracker.equity_curve

    # 现金 = 10000 - 100*100 - 10 - 5 = -15
    expected_cash = 10000 - 10000 - 10 - 5
    assert equity["cash"].iloc[0] == expected_cash


def test_empty_trades() -> None:
    """测试空交易列表不崩溃。"""
    df = _make_df(10)
    tracker = PortfolioTracker(df)

    tracker.apply_trades([])

    equity = tracker.equity_curve
    positions = tracker.positions

    # 所有 bar 现金应等于初始现金
    assert (equity["cash"] == 100000).all()
    # 所有 bar 持仓应为 0
    assert (positions["size"] == 0).all()


def test_apply_trades_int_datetime_vs_datetime64_df() -> None:
    """issue #30：trade.datetime(int) 与 df datetime(datetime64) 类型不一致时，
    交易仍应被正确应用，而非静默漏单导致净值恒定。

    复现：过去 apply_trades 用 trade.datetime 作 dict key、用
    df["datetime"].to_numpy()[i] 查找；两端类型不一致（int vs datetime64）
    时 trade_map.get(dt) 永不命中，全部交易被丢弃 → 净值恒等于初始资金，
    但 trades 表里仍有 PnL（_compute_pnls 不依赖 df 查找）。
    """
    # df 的 datetime 列为 datetime64（真实 get_stock_kline 路径）
    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=10, freq="D"),
            "close": [10, 11, 12, 11, 10, 13, 14, 13, 15, 16],
        }
    )
    # trade.datetime 为 int YYYYMMDD（类型与 df 不一致）
    buy = Trade(
        datetime=20240101,
        direction="BUY",
        size=100,
        price=10.0,
        commission=5.0,
        slippage=0.0,
    )
    sell = Trade(
        datetime=20240106,
        direction="SELL",
        size=100,
        price=13.0,
        commission=6.0,
        slippage=0.0,
    )

    tracker = PortfolioTracker(df, initial_cash=100000)
    tracker.apply_trades([buy, sell])

    equity = tracker.equity_curve
    # 卖出后现金 = 100000 - 100*10 - 5 + 100*13 - 6 = 100289
    # 修复前此处为 100000（交易被静默丢弃）
    assert equity["cash"].iloc[-1] == 100289.0
    # 净值不应恒等于初始资金（交易生效）
    assert equity["total"].iloc[-1] != 100000.0


def test_apply_trades_timestamp_vs_int_df() -> None:
    """issue #30 反向：trade.datetime(Timestamp) 与 df datetime(int) 不一致。"""
    df = pd.DataFrame(
        {
            "datetime": [
                int(d.strftime("%Y%m%d")) for d in pd.date_range("2024-01-01", periods=10, freq="D")
            ],
            "close": [10, 11, 12, 11, 10, 13, 14, 13, 15, 16],
        }
    )
    buy = Trade(
        datetime=pd.Timestamp("2024-01-01"),
        direction="BUY",
        size=100,
        price=10.0,
        commission=5.0,
        slippage=0.0,
    )

    tracker = PortfolioTracker(df, initial_cash=100000)
    tracker.apply_trades([buy])

    # 修复前交易被丢弃、持仓为 0
    assert tracker.positions["size"].iloc[0] == 100
