"""回测引擎数据类型单元测试。"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from easy_tdx.backtest.types import BacktestResult, Position, Signal, Trade

# ── Signal 测试 ─────────────────────────────────────────────────────────────


def test_signal_defaults() -> None:
    """测试 Signal 的默认值。"""
    sig = Signal(
        datetime=1715356800000,  # 2024-06-09 00:00:00 UTC
        direction="BUY",
        size=100.0,
    )
    assert sig.price is None
    assert sig.stop_loss is None
    assert sig.take_profit is None


def test_signal_with_all_fields() -> None:
    """测试 Signal 完整字段。"""
    sig = Signal(
        datetime=1715356800000,
        direction="SELL",
        size=50.0,
        price=10.5,
        stop_loss=11.0,
        take_profit=10.0,
    )
    assert sig.direction == "SELL"
    assert sig.size == 50.0
    assert sig.price == 10.5
    assert sig.stop_loss == 11.0
    assert sig.take_profit == 10.0


def test_direction_literal() -> None:
    """测试 direction 字面量类型。"""
    sig_buy = Signal(datetime=0, direction="BUY", size=1.0)
    sig_sell = Signal(datetime=0, direction="SELL", size=1.0)
    assert sig_buy.direction == "BUY"
    assert sig_sell.direction == "SELL"


# ── Trade 测试 ──────────────────────────────────────────────────────────────


def test_trade_defaults() -> None:
    """测试 Trade 的默认值。"""
    trade = Trade(
        datetime=1715356800000,
        direction="BUY",
        size=100.0,
        price=10.0,
        commission=0.3,
        slippage=0.1,
    )
    assert trade.pnl == 0.0
    assert trade.rejected is False


def test_trade_with_pnl() -> None:
    """测试带盈亏的成交记录。"""
    trade = Trade(
        datetime=1715356800000,
        direction="SELL",
        size=100.0,
        price=11.0,
        commission=0.3,
        slippage=0.1,
        pnl=50.0,
    )
    assert trade.pnl == 50.0


def test_trade_rejected() -> None:
    """测试被拒绝的成交。"""
    trade = Trade(
        datetime=1715356800000,
        direction="BUY",
        size=1000000.0,  # 超大单模拟资金不足
        price=10.0,
        commission=0.0,
        slippage=0.0,
        rejected=True,
    )
    assert trade.rejected is True


# ── Position 测试 ───────────────────────────────────────────────────────────


def test_position_long() -> None:
    """测试多头持仓。"""
    pos = Position(
        datetime=1715356800000,
        size=100.0,
        avg_price=10.0,
        market_value=1050.0,
        unrealized_pnl=50.0,
    )
    assert pos.size > 0
    assert pos.avg_price == 10.0
    assert pos.market_value == 1050.0
    assert pos.unrealized_pnl == 50.0


def test_position_short() -> None:
    """测试空头持仓。"""
    pos = Position(
        datetime=1715356800000,
        size=-100.0,
        avg_price=10.0,
        market_value=-1050.0,
        unrealized_pnl=50.0,
    )
    assert pos.size < 0


def test_position_flat() -> None:
    """测试空仓。"""
    pos = Position(
        datetime=1715356800000,
        size=0.0,
        avg_price=0.0,
        market_value=0.0,
        unrealized_pnl=0.0,
    )
    assert pos.size == 0.0


# ── BacktestResult 测试 ─────────────────────────────────────────────────────


def test_backtest_result_to_dict() -> None:
    """测试 BacktestResult.to_dict() 序列化。"""
    equity_df = pd.DataFrame(
        {
            "datetime": [1715356800000, 1715443200000],
            "equity": [10000.0, 10100.0],
            "drawdown": [0.0, -0.0099],
        }
    )
    equity_df = equity_df.set_index("datetime")

    trades_df = pd.DataFrame(
        {
            "datetime": [1715356800000],
            "direction": ["BUY"],
            "size": [100.0],
            "price": [10.0],
            "commission": [0.3],
            "slippage": [0.1],
            "pnl": [0.0],
            "rejected": [False],
        }
    )

    positions_df = pd.DataFrame(
        {
            "datetime": [1715356800000],
            "size": [100.0],
            "avg_price": [10.0],
            "market_value": [1000.0],
            "unrealized_pnl": [0.0],
        }
    )

    result = BacktestResult(
        performance={"total_return": 0.01, "sharpe_ratio": 1.5},
        equity_curve=equity_df,
        trades=trades_df,
        positions=positions_df,
        config={"initial_capital": 10000.0},
    )

    data = result.to_dict()

    assert isinstance(data, dict)
    assert data["performance"]["total_return"] == 0.01
    assert isinstance(data["equity_curve"], list)
    assert len(data["equity_curve"]) == 2
    assert isinstance(data["trades"], list)
    assert len(data["trades"]) == 1
    assert isinstance(data["positions"], list)
    assert len(data["positions"]) == 1
    assert data["config"]["initial_capital"] == 10000.0


def test_backtest_result_to_json() -> None:
    """测试 BacktestResult.to_json() 序列化。"""
    equity_df = pd.DataFrame(
        {
            "datetime": [1715356800000],
            "equity": [10000.0],
        }
    )
    equity_df = equity_df.set_index("datetime")

    result = BacktestResult(
        performance={"total_return": 0.01},
        equity_curve=equity_df,
        trades=pd.DataFrame(),
        positions=pd.DataFrame(),
        config={"initial_capital": 10000.0},
    )

    json_str = result.to_json()

    # 验证是有效 JSON
    parsed = json.loads(json_str)
    assert parsed["performance"]["total_return"] == 0.01
    assert parsed["config"]["initial_capital"] == 10000.0
    assert parsed["equity_curve"][0]["equity"] == 10000.0


def test_backtest_result_empty_dataframes() -> None:
    """测试空 DataFrame 不崩溃。"""
    result = BacktestResult(
        performance={},
        equity_curve=pd.DataFrame(),
        trades=pd.DataFrame(),
        positions=pd.DataFrame(),
        config={},
    )

    # to_dict 不崩溃
    data = result.to_dict()
    assert data["equity_curve"] == []
    assert data["trades"] == []
    assert data["positions"] == []

    # to_json 不崩溃
    json_str = result.to_json()
    parsed = json.loads(json_str)
    assert parsed["equity_curve"] == []
    assert parsed["trades"] == []
    assert parsed["positions"] == []


def test_backtest_result_summary(capsys: Any) -> None:
    """测试 summary() 打印输出。"""
    result = BacktestResult(
        performance={"total_return": 0.05, "sharpe_ratio": 1.2, "max_drawdown": -0.02},
        equity_curve=pd.DataFrame(),
        trades=pd.DataFrame(),
        positions=pd.DataFrame(),
        config={"initial_capital": 10000.0},
    )

    result.summary()
    captured = capsys.readouterr()

    assert "=== 回测绩效概要 ===" in captured.out
    assert "total_return: 0.0500" in captured.out
    assert "sharpe_ratio: 1.2000" in captured.out
    assert "max_drawdown: -0.0200" in captured.out
    assert "成交记录数: 0" in captured.out
    assert "持仓快照数: 0" in captured.out
    assert "资金曲线点数: 0" in captured.out
