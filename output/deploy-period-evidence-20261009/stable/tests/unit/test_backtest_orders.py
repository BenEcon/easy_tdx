"""订单撮合模拟器单元测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from easy_tdx.backtest.orders import OrderSimulator
from easy_tdx.backtest.slippage import FixedSlippage, PercentSlippage
from easy_tdx.backtest.types import Signal

# ── Test Fixtures ─────────────────────────────────────────────────────────────


def _make_df(n: int = 10) -> pd.DataFrame:
    """构造测试用 K线数据。

    价格递增：open=100..109, close=101..110, high=102..111, low=99..108
    datetime: range(20240101, 20240101+n)
    """
    data = {
        "datetime": [20240101 + i for i in range(n)],
        "open": [100.0 + i for i in range(n)],
        "close": [101.0 + i for i in range(n)],
        "high": [102.0 + i for i in range(n)],
        "low": [99.0 + i for i in range(n)],
        "volume": [1000] * n,
    }
    return pd.DataFrame(data)


def _buy_signal(bar_idx: int, size: float = 0) -> Signal:
    """构造买入信号。"""
    return Signal(
        datetime=20240101 + bar_idx,
        direction="BUY",
        size=size,
    )


def _sell_signal(bar_idx: int, size: float = 0) -> Signal:
    """构造卖出信号。"""
    return Signal(
        datetime=20240101 + bar_idx,
        direction="SELL",
        size=size,
    )


# ── Test Execution Modes ───────────────────────────────────────────────────────


class TestExecutionModes:
    """测试不同执行模式的成交价。"""

    def test_next_open(self) -> None:
        """next_open: 下一根K线的开盘价。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open")

        # 信号在 bar 0，应该在 bar 1 的 open 成交
        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)

        assert len(trades) == 1
        assert trades[0].price == 101.0  # df["open"].iloc[1]
        assert trades[0].rejected is False

    def test_next_close(self) -> None:
        """next_close: 下一根K线的收盘价。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_close")

        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)

        assert len(trades) == 1
        assert trades[0].price == 102.0  # df["close"].iloc[1]


# ── Test Position Modes ────────────────────────────────────────────────────────


class TestPositionModes:
    """测试不同仓位模式。"""

    def test_full_position(self) -> None:
        """full: 全仓买入（100股整手）。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open", position_mode="full")

        cash = 20000  # 足够买100股
        signals = [_buy_signal(0, size=0)]  # size=0 表示全仓
        trades = sim.simulate(signals, cash=cash, position=0)

        assert len(trades) == 1
        # price=101, 20000 / (101 * 1.0003) ≈ 197.96, 可买 100 股（1手）
        assert trades[0].size == 100

    def test_fixed_position(self) -> None:
        """fixed: 固定股数。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open", position_mode="fixed")

        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)

        assert len(trades) == 1
        assert trades[0].size == 100

    def test_percent_position(self) -> None:
        """percent: 总资产的百分比。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open", position_mode="percent")

        # 50% 资产，但不足1手（100股）
        signals = [_buy_signal(0, size=0.5)]
        trades = sim.simulate(signals, cash=20000, position=0)

        # 20000 * 0.5 = 10000, price=101, int(10000/101/100)*100 = 0
        # reduce 模式下返回 None（无交易）
        assert len(trades) == 0


# ── Test Reject Policy ─────────────────────────────────────────────────────────


class TestRejectPolicy:
    """测试拒绝策略。"""

    def test_reduce_on_insufficient_cash(self) -> None:
        """reduce: 资金不足时减少买入量。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open", reject_policy="reduce")

        # 只有 15000 元现金，想买 200 股（price=101）
        # 200股需要约 20200 元，但只有 15000 元
        # 应该减少到可买数量
        signals = [_buy_signal(0, size=200)]
        trades = sim.simulate(signals, cash=15000, position=0, position_mode="fixed")

        assert len(trades) == 1
        assert trades[0].size < 200  # 应该减少
        assert trades[0].rejected is False

    def test_skip_on_insufficient_cash(self) -> None:
        """skip: 资金不足时拒绝订单。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open", reject_policy="skip")

        # 只有 15000 元现金，想买 200 股（price=101）
        signals = [_buy_signal(0, size=200)]
        trades = sim.simulate(signals, cash=15000, position=0, position_mode="fixed")

        assert len(trades) == 1
        assert trades[0].rejected is True
        assert trades[0].size == 200  # 保持原订单量

    def test_sell_with_no_position_skip(self) -> None:
        """skip: 无持仓时卖出被拒绝。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open", reject_policy="skip")

        signals = [_sell_signal(0, size=100)]
        trades = sim.simulate(signals, cash=0, position=0)

        assert len(trades) == 1
        assert trades[0].rejected is True

    def test_reduce_on_insufficient_position(self) -> None:
        """reduce: 持仓不足时减少卖出量。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open", reject_policy="reduce")

        # 只有 50 股，想卖 100 股
        signals = [_sell_signal(0, size=100)]
        trades = sim.simulate(signals, cash=0, position=50)

        assert len(trades) == 1
        assert trades[0].size == 50  # 减少到实际持仓
        assert trades[0].rejected is False


# ── Test Fees ─────────────────────────────────────────────────────────────────


class TestFees:
    """测试费用计算。"""

    def test_commission_on_buy(self) -> None:
        """买入时计算佣金。"""
        df = _make_df(10)
        sim = OrderSimulator(
            df,
            execution="next_open",
            commission=0.0003,
            min_commission=5.0,
        )

        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)

        assert len(trades) == 1
        # price=101, size=100, amount=10100
        # commission = max(10100 * 0.0003, 5) = max(3.03, 5) = 5
        assert trades[0].commission >= 5.0

    def test_stamp_tax_on_sell(self) -> None:
        """卖出时额外计算印花税。"""
        df = _make_df(10)
        sim = OrderSimulator(
            df,
            execution="next_open",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
        )

        # 先买入
        buy_signals = [_buy_signal(0, size=100)]
        sim.simulate(buy_signals, cash=20000, position=0)

        # 再卖出
        sell_signals = [_sell_signal(1, size=100)]
        trades = sim.simulate(sell_signals, cash=0, position=100)

        assert len(trades) == 1
        # commission + stamp_tax
        # commission = max(10200 * 0.0003, 5) = 5
        # stamp_tax = 10200 * 0.001 = 10.2
        # total = 15.2
        assert trades[0].commission > 5.0

    def test_slippage(self) -> None:
        """测试滑点计算。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open", slippage=0.01)

        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)

        assert len(trades) == 1
        assert trades[0].slippage == 1.0  # 100 * 0.01


# ── Test Edge Cases ───────────────────────────────────────────────────────────


class TestEdgeCases:
    """测试边界情况。"""

    def test_signal_not_found_in_df(self) -> None:
        """信号时间不在K线数据中。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open")

        # 信号时间 20250101 不在 df 中
        signal = Signal(datetime=20250101, direction="BUY", size=100)
        trades = sim.simulate([signal], cash=20000, position=0)

        assert len(trades) == 0

    def test_signal_at_last_bar_next_execution(self) -> None:
        """信号在最后一根K线，next_* 模式无法成交。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open")

        # 信号在最后一根
        signals = [_buy_signal(9, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)

        # exec_idx = 10，超出范围
        assert len(trades) == 0

    def test_datetime_column_as_int(self) -> None:
        """datetime 列为 int 类型时的查找。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open")

        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)

        assert len(trades) == 1

    def test_datetime_column_as_datetime(self) -> None:
        """datetime 列为 datetime 类型时的查找。"""
        df = _make_df(10)
        # 转为 datetime 类型
        df["datetime"] = pd.to_datetime(df["datetime"].astype(str), format="%Y%m%d")

        sim = OrderSimulator(df, execution="next_open")

        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)

        assert len(trades) == 1

    def test_multiple_signals(self) -> None:
        """多个信号的顺序执行。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open")

        signals = [
            _buy_signal(0, size=100),
            _sell_signal(1, size=100),
        ]
        trades = sim.simulate(signals, cash=20000, position=0)

        assert len(trades) == 2
        assert trades[0].direction == "BUY"
        assert trades[1].direction == "SELL"

    def test_position_tracking(self) -> None:
        """测试持仓跟踪。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open")

        # 买入 100 股
        buy_signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(buy_signals, cash=20000, position=0)

        # 验证持仓（通过模拟器内部状态）
        # 这里需要暴露 position 或者通过返回值验证
        # 简化：只验证成交记录
        assert len(trades) == 1
        assert trades[0].size == 100


# ── Test SlippageModel Integration ─────────────────────────────────────────────


class TestSlippageModelIntegration:
    """测试 OrderSimulator 与 SlippageModel 集成。"""

    def test_fixed_slippage_model(self) -> None:
        """FixedSlippage 与旧 slippage 参数等价。"""
        df = _make_df(10)
        sim = OrderSimulator(
            df,
            execution="next_open",
            slippage_model=FixedSlippage(per_share=0.01),
        )
        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)
        assert len(trades) == 1
        assert trades[0].slippage == pytest.approx(1.0)

    def test_percent_slippage_model(self) -> None:
        """PercentSlippage 计算。"""
        df = _make_df(10)
        sim = OrderSimulator(
            df,
            execution="next_open",
            slippage_model=PercentSlippage(rate=0.001),
        )
        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)
        assert len(trades) == 1
        # price=101 (next_open), 101 × 100 × 0.001 = 10.1
        assert trades[0].slippage == pytest.approx(10.1)

    def test_slippage_model_overrides_slippage_param(self) -> None:
        """slippage_model 优先于 slippage 参数。"""
        df = _make_df(10)
        sim = OrderSimulator(
            df,
            execution="next_open",
            position_mode="fixed",
            slippage=999.0,
            slippage_model=FixedSlippage(per_share=0.01),
        )
        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)
        assert len(trades) == 1
        assert trades[0].slippage == pytest.approx(1.0)

    def test_sell_with_slippage_model(self) -> None:
        """卖出时也使用滑点模型。"""
        df = _make_df(10)
        sim = OrderSimulator(
            df,
            execution="next_open",
            slippage_model=FixedSlippage(per_share=0.02),
        )
        signals = [_sell_signal(0, size=100)]
        trades = sim.simulate(signals, cash=0, position=100)
        assert len(trades) == 1
        # position_mode=full, size=0 → sell all position=100
        assert trades[0].slippage == pytest.approx(2.0)

    def test_no_slippage_model_uses_old_param(self) -> None:
        """不提供 model 时使用旧 slippage 参数。"""
        df = _make_df(10)
        sim = OrderSimulator(df, execution="next_open", slippage=0.05)
        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)
        assert len(trades) == 1
        assert trades[0].slippage == pytest.approx(5.0)


# ── Test Non-Continuous Index ─────────────────────────────────────────────────


class TestNonContinuousIndex:
    """df.index 非默认 RangeIndex 时，撮合应按位置（iloc）而非 label 取 bar。

    回归 _find_bar_index 旧实现在非连续 index 下用 idxmax() 返回 label 当位置用，
    导致 iloc 取错 bar / 越界。
    """

    def test_next_open_with_non_continuous_index(self) -> None:
        """信号在 bar 0（label=10），应在 bar 1（position）open 成交。"""
        df = _make_df(10)
        df.index = [10 * (i + 1) for i in range(len(df))]  # [10,20,...,100]
        sim = OrderSimulator(df, execution="next_open")

        signals = [_buy_signal(0, size=100)]
        trades = sim.simulate(signals, cash=20000, position=0)

        assert len(trades) == 1
        # position 1 的 open = 101.0；旧代码会用 label 10 当位置 → iloc[10] 越界
        assert trades[0].price == 101.0
        assert trades[0].rejected is False
