"""执行仿真引擎单元测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from easy_tdx.backtest.execution import (
    ExecutionModel,
    ImmediateExecution,
    LimitExecution,
    TWAPExecution,
    VWAPExecution,
)
from easy_tdx.backtest.types import Signal


def _make_df(n: int = 20) -> pd.DataFrame:
    """构造测试用K线数据。"""
    data = {
        "datetime": [20240101 + i for i in range(n)],
        "open": [100.0 + i for i in range(n)],
        "close": [101.0 + i for i in range(n)],
        "high": [102.0 + i for i in range(n)],
        "low": [99.0 + i for i in range(n)],
        "volume": [10000] * n,
    }
    return pd.DataFrame(data)


class TestExecutionBase:
    """基类验证。"""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            ExecutionModel()  # type: ignore[abstract]


class TestImmediateExecution:
    """即时成交。"""

    def test_buy_signal(self) -> None:
        df = _make_df(10)
        model = ImmediateExecution()
        signal = Signal(datetime=20240101, direction="BUY", size=100)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=20000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 1
        assert trades[0].direction == "BUY"
        assert trades[0].price == 101.0

    def test_sell_signal(self) -> None:
        df = _make_df(10)
        model = ImmediateExecution()
        signal = Signal(datetime=20240101, direction="SELL", size=100)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=0,
            position=200,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 1
        assert trades[0].direction == "SELL"

    def test_signal_at_last_bar(self) -> None:
        df = _make_df(10)
        model = ImmediateExecution()
        signal = Signal(datetime=20240109, direction="BUY", size=100)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=9,
            cash=20000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 0

    def test_with_slippage_model(self) -> None:
        from easy_tdx.backtest.slippage import FixedSlippage

        df = _make_df(10)
        model = ImmediateExecution()
        signal = Signal(datetime=20240101, direction="BUY", size=100)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=20000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=FixedSlippage(per_share=0.01),
        )
        assert len(trades) == 1
        assert trades[0].slippage == pytest.approx(1.0)

    def test_commission_on_buy(self) -> None:
        df = _make_df(10)
        model = ImmediateExecution()
        signal = Signal(datetime=20240101, direction="BUY", size=100)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=20000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 1
        assert trades[0].commission >= 5.0

    def test_stamp_tax_on_sell(self) -> None:
        df = _make_df(10)
        model = ImmediateExecution()
        signal = Signal(datetime=20240101, direction="SELL", size=100)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=0,
            position=200,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 1
        assert trades[0].commission > 10.0

    def test_full_position_buy(self) -> None:
        df = _make_df(10)
        model = ImmediateExecution()
        signal = Signal(datetime=20240101, direction="BUY", size=0)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=20000,
            position=0,
            position_mode="full",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 1
        assert trades[0].size == 100


class TestTWAPExecution:
    """时间加权平均价格执行。"""

    def test_split_buy_into_3_bars(self) -> None:
        df = _make_df(20)
        model = TWAPExecution(n_bars=3)
        signal = Signal(datetime=20240101, direction="BUY", size=300)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=100000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 3
        total_size = sum(t.size for t in trades)
        assert total_size <= 300
        prices = [t.price for t in trades]
        assert prices[0] != prices[1]

    def test_split_sell_into_2_bars(self) -> None:
        df = _make_df(20)
        model = TWAPExecution(n_bars=2)
        signal = Signal(datetime=20240101, direction="SELL", size=200)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=0,
            position=500,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 2
        assert sum(t.size for t in trades) == 200.0

    def test_truncates_at_data_end(self) -> None:
        df = _make_df(5)
        model = TWAPExecution(n_bars=10)
        signal = Signal(datetime=20240101, direction="BUY", size=1000)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=100000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) <= 4

    def test_full_position_mode(self) -> None:
        df = _make_df(20)
        model = TWAPExecution(n_bars=3)
        signal = Signal(datetime=20240101, direction="BUY", size=0)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=60000,
            position=0,
            position_mode="full",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 3
        assert all(t.size > 0 for t in trades)


class TestVWAPExecution:
    """成交量加权平均价格执行。"""

    def test_basic_buy(self) -> None:
        df = _make_df(20)
        model = VWAPExecution(n_bars=3, volume_lookback=10)
        signal = Signal(datetime=20240101, direction="BUY", size=300)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=5,
            cash=100000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 3
        total_size = sum(t.size for t in trades)
        assert total_size <= 300

    def test_volume_weighted_split(self) -> None:
        df = _make_df(20)
        df.loc[6, "volume"] = 50000
        df.loc[7, "volume"] = 50000
        df.loc[8, "volume"] = 50000
        model = VWAPExecution(n_bars=3, volume_lookback=5)
        signal = Signal(datetime=20240105, direction="BUY", size=300)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=5,
            cash=100000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 3
        sizes = [t.size for t in trades]
        assert sum(sizes) <= 300

    def test_truncates_at_data_end(self) -> None:
        df = _make_df(5)
        model = VWAPExecution(n_bars=10, volume_lookback=3)
        signal = Signal(datetime=20240101, direction="BUY", size=1000)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=100000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) <= 4


class TestLimitExecution:
    """限价单执行。"""

    def test_buy_limit_filled(self) -> None:
        df = _make_df(20)
        model = LimitExecution(ttl_bars=5)
        signal = Signal(datetime=20240101, direction="BUY", size=100, price=100.0)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=20000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 1
        assert trades[0].price == 100.0
        assert trades[0].direction == "BUY"

    def test_sell_limit_filled(self) -> None:
        df = _make_df(20)
        model = LimitExecution(ttl_bars=5)
        signal = Signal(datetime=20240101, direction="SELL", size=100, price=105.0)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=0,
            position=200,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 1
        assert trades[0].price == 105.0

    def test_limit_not_triggered(self) -> None:
        df = _make_df(10)
        model = LimitExecution(ttl_bars=3)
        signal = Signal(datetime=20240101, direction="BUY", size=100, price=50.0)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=20000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 0

    def test_no_price_falls_back_to_immediate(self) -> None:
        df = _make_df(10)
        model = LimitExecution(ttl_bars=5)
        signal = Signal(datetime=20240101, direction="BUY", size=100, price=None)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=20000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 1
        assert trades[0].price == 101.0

    def test_ttl_expires(self) -> None:
        df = _make_df(20)
        model = LimitExecution(ttl_bars=2)
        signal = Signal(datetime=20240101, direction="BUY", size=100, price=98.0)
        trades = model.execute(
            signal=signal,
            df=df,
            bar_idx=0,
            cash=20000,
            position=0,
            position_mode="fixed",
            commission=0.0003,
            min_commission=5.0,
            stamp_tax=0.001,
            slippage_model=None,
        )
        assert len(trades) == 0
