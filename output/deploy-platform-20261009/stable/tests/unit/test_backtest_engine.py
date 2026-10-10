"""Test BacktestEngine orchestration."""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx import MyTT
from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.execution import TWAPExecution, VWAPExecution
from easy_tdx.backtest.slippage import FixedSlippage, SquareRootSlippage
from easy_tdx.backtest.strategy import Strategy


def _make_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = low + rng.uniform(0, high - low, n)
    volume = rng.integers(1000000, 10000000, n)

    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


class MACrossStrategy(Strategy):
    """Simple MA crossover strategy."""

    def init(self):
        self.ma5 = self.I(MyTT.MA, self.data.close, 5)
        self.ma20 = self.I(MyTT.MA, self.data.close, 20)
        self.cross_up = False
        self.cross_down = False

    def next(self):
        # Check if crossing happened on this bar
        if self._bar_index > 0:
            prev_ma5 = self.ma5[self._bar_index - 1]
            prev_ma20 = self.ma20[self._bar_index - 1]
            curr_ma5 = self.ma5[self._bar_index]
            curr_ma20 = self.ma20[self._bar_index]

            # Golden cross: ma5 crosses above ma20
            if prev_ma5 <= prev_ma20 and curr_ma5 > curr_ma20:
                self.buy(size=0)
            # Death cross: ma5 crosses below ma20
            elif prev_ma5 >= prev_ma20 and curr_ma5 < curr_ma20:
                self.sell(size=0)


class FixedBuyStrategy(Strategy):
    """Strategy with fixed buy/sell at specific bars."""

    def init(self):
        pass

    def next(self):
        if self._bar_index == 5:
            self.buy(size=100)
        if self._bar_index == 50:
            self.sell(size=100)


class ChanlunStrategy(Strategy):
    """Strategy that uses chanlun result."""

    def init(self):
        pass

    def next(self):
        if self._bar_index == 10 and hasattr(self, "chanlun"):
            # Access chanlun result
            _ = self.chanlun
            self.buy(size=50)


class PrecomputedIndicatorStrategy(Strategy):
    """Strategy that uses precomputed indicator columns."""

    def init(self):
        # Assume BOLL_UPPER already exists in df
        if hasattr(self.data, "BOLL_UPPER"):
            self.boll_upper = self.data.BOLL_UPPER
        else:
            self.boll_upper = None

    def next(self):
        if self.boll_upper is not None and self._bar_index == 20:
            _ = self.boll_upper[self._bar_index]
            self.buy(size=10)


def test_basic_run():
    """Test basic engine run with MACrossStrategy."""
    df = _make_df(n=200)
    engine = BacktestEngine(MACrossStrategy, cash=100000)
    result = engine.run(df)

    # Check performance metrics
    assert result.performance is not None
    assert "total_return" in result.performance

    # Check equity curve length
    assert len(result.equity_curve) == 200

    # Check columns
    assert "datetime" in result.equity_curve.columns
    assert "total" in result.equity_curve.columns


def test_fixed_strategy():
    """Test FixedBuyStrategy produces trades."""
    df = _make_df(n=100)
    engine = BacktestEngine(FixedBuyStrategy, cash=100000)
    result = engine.run(df)

    # Should have at least 2 trades
    assert len(result.trades) >= 2, f"Expected at least 2 trades, got {len(result.trades)}"

    # Check buy at bar 5
    buy_trades = result.trades[result.trades["direction"] == "BUY"]
    assert len(buy_trades) >= 1, "No buy trades found"

    # Check sell at bar 50
    sell_trades = result.trades[result.trades["direction"] == "SELL"]
    assert len(sell_trades) >= 1, "No sell trades found"


def test_result_columns():
    """Test BacktestResult has correct columns."""
    df = _make_df(n=100)
    engine = BacktestEngine(MACrossStrategy)
    result = engine.run(df)

    # Equity curve columns
    expected_ec_cols = ["datetime", "cash", "position_value", "total"]
    for col in expected_ec_cols:
        assert col in result.equity_curve.columns

    # Trades columns
    expected_trade_cols = ["datetime", "direction", "size", "price", "pnl"]
    for col in expected_trade_cols:
        assert col in result.trades.columns


def test_to_dict():
    """Test BacktestResult is serializable."""
    df = _make_df(n=50)
    engine = BacktestEngine(MACrossStrategy)
    result = engine.run(df)

    # to_dict should not raise
    d = result.to_dict()
    assert "performance" in d
    assert "equity_curve" in d
    assert "trades" in d

    # to_json should not raise
    json_str = result.to_json()
    assert len(json_str) > 0


def test_chanlun_injection():
    """Test chanlun result injection."""
    df = _make_df(n=50)

    # Mock chanlun result
    chanlun_result = {"test": "data"}

    engine = BacktestEngine(ChanlunStrategy)
    result = engine.run(df, chanlun_result=chanlun_result)

    # Should have trades
    assert len(result.trades) >= 1


def test_config_snapshot():
    """Test config contains correct cash and commission."""
    df = _make_df(n=50)
    engine = BacktestEngine(MACrossStrategy, cash=50000, commission=0.0005, execution="next_open")
    result = engine.run(df)

    # Check config
    assert result.config["cash"] == 50000
    assert result.config["commission"] == 0.0005
    assert result.config["execution"] == "next_open"


def test_precomputed_indicator_columns():
    """Test strategy works with precomputed indicator columns."""
    df = _make_df(n=50)
    # Add precomputed BOLL_UPPER column
    df["BOLL_UPPER"] = df["close"] * 1.05

    engine = BacktestEngine(PrecomputedIndicatorStrategy)
    result = engine.run(df)

    # Should not crash and should have trades
    assert len(result.equity_curve) == 50


def test_empty_df():
    """Test engine with empty DataFrame."""
    df = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
    engine = BacktestEngine(MACrossStrategy)
    result = engine.run(df)

    # Should return empty result
    assert len(result.equity_curve) == 0
    assert len(result.trades) == 0


def test_strategy_instance_vs_class():
    """Test engine accepts both strategy class and instance."""
    df = _make_df(n=50)

    # Test with class
    engine1 = BacktestEngine(MACrossStrategy)
    result1 = engine1.run(df)
    assert len(result1.equity_curve) == 50

    # Test with instance
    strat = MACrossStrategy()
    engine2 = BacktestEngine(strat)
    result2 = engine2.run(df)
    assert len(result2.equity_curve) == 50


def test_commission_calculation():
    """Test commission is correctly applied."""
    df = _make_df(n=100)
    engine = BacktestEngine(
        FixedBuyStrategy,
        cash=100000,
        commission=0.001,
        min_commission=10.0,
    )
    result = engine.run(df)

    # Should have trades
    assert len(result.trades) >= 2

    # Check trades have commission
    assert (result.trades["commission"] > 0).all()


def test_pnl_calculation():
    """Test PnL is calculated for sell trades."""
    df = _make_df(n=100, seed=123)  # Use specific seed for predictable prices
    engine = BacktestEngine(FixedBuyStrategy, cash=100000, commission=0.0)
    result = engine.run(df)

    # Should have trades
    assert len(result.trades) >= 2

    # Get trades - should have at least one BUY and one SELL
    buy_trades = result.trades[result.trades["direction"] == "BUY"]
    sell_trades = result.trades[result.trades["direction"] == "SELL"]

    assert len(buy_trades) >= 1
    assert len(sell_trades) >= 1

    # PnL is calculated for sell trades
    # Check that sell trades have PnL computed
    assert (sell_trades["pnl"] != 0).any() or len(sell_trades) == 0

    # For buy trades, PnL should be 0
    assert (buy_trades["pnl"] == 0).all()


class PositionAwareStrategy(Strategy):
    """Strategy that checks position before trading (the common pattern)."""

    def init(self):
        self.ma5 = self.I(MyTT.MA, self.data.close, 5)
        self.ma20 = self.I(MyTT.MA, self.data.close, 20)
        self.cross_up = False
        self.cross_down = False

    def next(self):
        if self._bar_index > 0:
            prev_ma5 = self.ma5[self._bar_index - 1]
            prev_ma20 = self.ma20[self._bar_index - 1]
            curr_ma5 = self.ma5[self._bar_index]
            curr_ma20 = self.ma20[self._bar_index]

            if prev_ma5 <= prev_ma20 and curr_ma5 > curr_ma20:
                if self.position["size"] == 0:
                    self.buy(size=0)
            elif prev_ma5 >= prev_ma20 and curr_ma5 < curr_ma20:
                if self.position["size"] > 0:
                    self.sell(size=0)


def test_position_aware_buy_sell_alternation():
    """Regression: strategy that checks position must produce alternating BUY/SELL."""
    df = _make_df(n=300, seed=42)
    engine = BacktestEngine(PositionAwareStrategy, cash=100000)
    result = engine.run(df)

    trades = result.trades[~result.trades["rejected"]]
    directions = trades["direction"].tolist()

    # Must have both BUYs and SELLs
    assert "BUY" in directions, "No BUY trades generated"
    assert "SELL" in directions, "No SELL trades generated — position feedback broken"

    # Trades must alternate: no two consecutive BUYs or SELLs
    for i in range(1, len(directions)):
        assert directions[i] != directions[i - 1], (
            f"Consecutive same-direction trades at index {i}: "
            f"{directions[i - 1]} -> {directions[i]}"
        )


def test_position_aware_no_duplicate_buys():
    """After a BUY, position['size'] > 0 so strategy should not buy again."""
    df = _make_df(n=300, seed=42)
    engine = BacktestEngine(PositionAwareStrategy, cash=100000)
    result = engine.run(df)

    buy_trades = result.trades[(result.trades["direction"] == "BUY") & (~result.trades["rejected"])]

    # Each BUY's size should be reasonable (not tiny leftover from exhausted cash)
    if len(buy_trades) > 1:
        # No consecutive buys where the second is tiny (cash leftover artifact)
        sizes = buy_trades["size"].tolist()
        for i in range(1, len(sizes)):
            # Second buy in a pair should not be tiny compared to first
            # (would indicate position wasn't tracked between bars)
            if i >= 1:
                prev_size = sizes[i - 1]
                cur_size = sizes[i]
                # Allow some variance but not orders-of-magnitude difference
                if prev_size > 0:
                    assert cur_size > prev_size * 0.1, (
                        f"Suspicious tiny buy {cur_size} after {prev_size} — "
                        f"position feedback may be broken"
                    )


# ── Stop-Loss / Take-Profit ──────────────────────────────────────────────────


def _make_flat_df(n: int = 30, base_price: float = 100.0) -> pd.DataFrame:
    """Generate flat OHLCV data at constant price for SL/TP testing."""
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": [base_price] * n,
            "high": [base_price + 2.0] * n,
            "low": [base_price - 2.0] * n,
            "close": [base_price] * n,
            "vol": [1000000] * n,
            "amount": [100000000] * n,
        }
    )


class StopLossStrategy(Strategy):
    """Strategy that buys with stop-loss."""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self._bar_index == 5 and self.position["size"] == 0:
            self.buy(size=0, stop_loss=95.0)


class TakeProfitStrategy(Strategy):
    """Strategy that buys with take-profit."""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self._bar_index == 5 and self.position["size"] == 0:
            self.buy(size=0, take_profit=110.0)


class StopLossAndTakeProfitStrategy(Strategy):
    """Strategy that buys with both stop-loss and take-profit."""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self._bar_index == 5 and self.position["size"] == 0:
            self.buy(size=0, stop_loss=95.0, take_profit=110.0)


def test_stop_loss_triggers_sell():
    """Test stop-loss triggers auto SELL when price drops below stop."""
    df = _make_flat_df(n=30)
    # Bar 12 drops low below stop_loss=95.0
    df.loc[12, "low"] = 93.0
    df.loc[12, "high"] = 96.0
    df.loc[12, "close"] = 94.0
    df.loc[12, "open"] = 97.0

    engine = BacktestEngine(StopLossStrategy, cash=100000)
    result = engine.run(df)

    trades = result.trades[~result.trades["rejected"]]
    sell_trades = trades[trades["direction"] == "SELL"]

    # Should have at least one SELL triggered by stop-loss
    assert len(sell_trades) >= 1, "Expected stop-loss sell"
    # Sell price should be at stop_loss price (95.0)
    assert sell_trades.iloc[0]["price"] == 95.0


def test_take_profit_triggers_sell():
    """Test take-profit triggers auto SELL when price rises above target.

    注意（审计 #4）：止盈信号延迟到下一根开盘成交（消除前视偏差）。
    当下一根开盘价低于触发价时（跳空回落），SELL 取更不利的实际开盘价。
    """
    df = _make_flat_df(n=30)
    # Bar 12 rises above take_profit=110.0
    df.loc[12, "high"] = 112.0
    df.loc[12, "low"] = 108.0
    df.loc[12, "close"] = 111.0
    df.loc[12, "open"] = 109.0
    # Bar 13 开盘回落到 100（跳空），止盈延迟成交应取更不利的 100 而非触发价 110
    df.loc[13, "open"] = 100.0

    engine = BacktestEngine(TakeProfitStrategy, cash=100000)
    result = engine.run(df)

    trades = result.trades[~result.trades["rejected"]]
    sell_trades = trades[trades["direction"] == "SELL"]

    # Should have at least one SELL triggered by take-profit
    assert len(sell_trades) >= 1, "Expected take-profit sell"
    # 延迟到下一根（bar 13）开盘成交，跳空回落取更不利的实际价 100（非触发价 110）
    assert sell_trades.iloc[0]["price"] == 100.0


def test_stop_loss_gap_down_fills_at_worse_price():
    """SL 信号延迟到下一根开盘成交；若跳空下跌，取更不利的开盘价（审计 #4）。

    构造当根触及止损、但下一根开盘远低于止损价的跳空场景，
    断言实际成交价取更不利的开盘价，回测净值低于"触发价成交"基线。
    """
    df = _make_flat_df(n=30)
    # Bar 12 触及 stop_loss=95（low=93）
    df.loc[12, "low"] = 93.0
    df.loc[12, "high"] = 96.0
    df.loc[12, "close"] = 94.0
    df.loc[12, "open"] = 97.0
    # Bar 13 跳空低开到 90（远低于止损价 95），应取 90 而非 95
    df.loc[13, "open"] = 90.0
    df.loc[13, "low"] = 89.0
    df.loc[13, "high"] = 91.0
    df.loc[13, "close"] = 90.5

    engine = BacktestEngine(StopLossStrategy, cash=100000)
    result = engine.run(df)

    trades = result.trades[~result.trades["rejected"]]
    sell_trades = trades[trades["direction"] == "SELL"]
    assert len(sell_trades) >= 1, "Expected stop-loss sell"
    # 跳空下跌：SELL 取 min(next_open=90, trigger=95) = 90（更不利）
    assert sell_trades.iloc[0]["price"] == 90.0


def test_stop_loss_not_triggered_when_price_stays_above():
    """Test no SL sell when price never drops to stop level."""
    df = _make_flat_df(n=30, base_price=100.0)
    # low is always 98.0 (> stop_loss=95.0), so SL never triggers

    engine = BacktestEngine(StopLossStrategy, cash=100000)
    result = engine.run(df)

    trades = result.trades[~result.trades["rejected"]]
    sell_trades = trades[trades["direction"] == "SELL"]

    # No SELL should be triggered by SL (low=98 > stop_loss=95)
    assert len(sell_trades) == 0, "SL should not trigger when price stays above"


def test_stop_loss_takes_priority_over_strategy_sell():
    """SL-triggered sell prevents duplicate strategy sell."""
    df = _make_flat_df(n=30)

    class SLThenManualSell(Strategy):
        def init(self) -> None:
            pass

        def next(self) -> None:
            if self._bar_index == 5 and self.position["size"] == 0:
                self.buy(size=0, stop_loss=95.0)
            # Manual sell at bar 15 — but SL should have fired first
            if self._bar_index == 15 and self.position["size"] > 0:
                self.sell(size=0)

    # Bar 10 triggers stop-loss
    df.loc[10, "low"] = 93.0
    df.loc[10, "close"] = 94.0

    engine = BacktestEngine(SLThenManualSell, cash=100000)
    result = engine.run(df)

    trades = result.trades[~result.trades["rejected"]]
    sell_trades = trades[trades["direction"] == "SELL"]

    # Should have exactly 1 SELL (from SL, not the manual one at bar 15)
    assert len(sell_trades) == 1, f"Expected 1 SL sell, got {len(sell_trades)}"
    assert sell_trades.iloc[0]["price"] == 95.0


# ── Chanlun Auto-Bridge ──────────────────────────────────────────────────────


class ChanlunAwareStrategy(Strategy):
    """Strategy that buys when chanlun analysis has at least one bi."""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self.chanlun is not None and self._bar_index == 15 and self.position["size"] == 0:
            # Strategy uses chanlun result to make trading decisions
            bis = self.chanlun.bis if hasattr(self.chanlun, "bis") else []
            if len(bis) > 0:
                self.buy(size=0)


def test_chanlun_auto_bridge():
    """Test chanlun_level auto-computes and injects analysis into strategy."""
    df = _make_df(n=100)
    engine = BacktestEngine(ChanlunAwareStrategy, cash=100000, chanlun_level="DAILY")
    result = engine.run(df)

    # Strategy should have received chanlun result (100 bars → at least some bis)
    trades = result.trades[~result.trades["rejected"]]
    buy_trades = trades[trades["direction"] == "BUY"]

    # With 100 bars of random data, ChanlunAnalyser should produce bis,
    # so the strategy should trigger a BUY at bar 15
    assert len(buy_trades) >= 1, "Expected chanlun-aware BUY"


def test_chanlun_manual_result_overrides_auto():
    """Test explicit chanlun_result takes priority over chanlun_level."""
    df = _make_df(n=50)

    class CheckerStrategy(Strategy):
        received: object = None

        def init(self) -> None:
            pass

        def next(self) -> None:
            if self._bar_index == 10:
                CheckerStrategy.received = self.chanlun
                self.buy(size=10)

    # Pass explicit result — should NOT auto-compute
    manual_result = {"manual": True}
    engine = BacktestEngine(CheckerStrategy, cash=100000, chanlun_level="DAILY")
    engine.run(df, chanlun_result=manual_result)

    # Strategy should have received the manual result, not auto-computed one
    assert CheckerStrategy.received == manual_result


# ── SlippageModel + ExecutionModel Integration ───────────────────────────────


class TestEngineSlippageModel:
    """BacktestEngine with SlippageModel integration."""

    def test_engine_with_slippage_model(self) -> None:
        """Engine uses SlippageModel."""

        class SimpleBuy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                if self._bar_index == 0:
                    self.buy(size=100)

        df = _make_df(20)
        engine = BacktestEngine(
            SimpleBuy,
            cash=100000,
            slippage_model=FixedSlippage(per_share=0.05),
        )
        result = engine.run(df)
        buy_trades = result.trades[result.trades["direction"] == "BUY"]
        if len(buy_trades) > 0:
            assert buy_trades.iloc[0]["slippage"] > 0


class TestEngineExecutionModel:
    """BacktestEngine with ExecutionModel integration."""

    def test_engine_with_twap(self) -> None:
        """Engine uses TWAP execution."""

        class SimpleBuy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                if self._bar_index == 0:
                    self.buy(size=300)

        df = _make_df(20)
        engine = BacktestEngine(
            SimpleBuy,
            cash=100000,
            execution_model=TWAPExecution(n_bars=3),
        )
        result = engine.run(df)
        buy_trades = result.trades[result.trades["direction"] == "BUY"]
        assert len(buy_trades) >= 1

    def test_execution_model_affects_equity(self) -> None:
        """ExecutionModel 路径的交易必须真正进入 PortfolioTracker。

        回归 datetime 类型分歧 bug：ExecutionModel 曾把 Trade.datetime 转成
        int(YYYYMMDD)，而 PortfolioTracker 用 df 原始 Timestamp 作为 trade_map
        的 key，导致 ExecutionModel 路径（TWAP/VWAP/Limit）的交易全部被静默
        跳过、权益曲线恒定、收益归零。
        """

        class BuyAndHold(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                if self._bar_index == 0:
                    self.buy(size=0)  # 全仓

        df = _make_df(30)  # Timestamp datetime（真实行情场景）
        engine = BacktestEngine(
            BuyAndHold,
            cash=100000,
            execution_model=TWAPExecution(n_bars=3),
        )
        result = engine.run(df)

        # 交易必须影响持仓与权益曲线（不能全程空仓 / 恒定）
        assert result.positions["size"].max() > 0
        assert result.equity_curve["total"].nunique() > 1

    def test_execution_model_with_vol_column(self) -> None:
        """真实行情数据使用 vol 列名，VWAP/方根滑点应能读到成交量。

        回归 volume 列名分歧 bug：回测代码曾只认 "volume"，真实数据列为
        "vol"，导致滑点模型 volume 恒为 0、退化到百分比模式，VWAP 退化为等权。
        """

        class BuyOnce(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                if self._bar_index == 0:
                    self.buy(size=0)

        df = _make_df(30).rename(columns={"volume": "vol"})
        engine = BacktestEngine(
            BuyOnce,
            cash=100000,
            execution_model=VWAPExecution(n_bars=3),
            slippage_model=SquareRootSlippage(),
        )
        result = engine.run(df)
        buy = result.trades[result.trades["direction"] == "BUY"]
        assert len(buy) > 0
        # volume 读到非 0 → 方根冲击未退化 → 滑点 > 0
        assert (buy["slippage"] > 0).all()

    def test_engine_backward_compatible(self) -> None:
        """No new params: behavior unchanged."""

        class SimpleBuy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                if self._bar_index == 0:
                    self.buy(size=100)

        df = _make_df(20)
        engine = BacktestEngine(SimpleBuy, cash=100000)
        result = engine.run(df)
        assert len(result.trades) >= 1

    def test_engine_accepts_date_column(self) -> None:
        """引擎应直接接受真实行情日线的 date 列（而非 datetime）。

        get_security_bars 日线返回 date 列，引擎在 run() 入口由 date 派生
        datetime，下游无感兼容。回归此前用户必须手动重命名才能跑日线回测的问题。
        """

        class SimpleBuy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                if self._bar_index == 0:
                    self.buy(size=0)

        # 仅 date 列、无 datetime 列 —— 模拟 get_security_bars 日线输出
        df = _make_df(30).rename(columns={"datetime": "date", "volume": "vol"})

        engine = BacktestEngine(SimpleBuy, cash=100000)
        result = engine.run(df)
        assert result.positions["size"].max() > 0
