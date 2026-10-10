"""测试多因子组合回测模块。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx import MyTT
from easy_tdx.backtest.strategy import Strategy

# ── 辅助函数 ─────────────────────────────────────────────────────────────────────


def _make_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """构造合成 OHLCV DataFrame。"""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = low + rng.uniform(0, high - low, n)
    volume = rng.integers(1_000_000, 10_000_000, n)

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


# ── 测试用策略 ─────────────────────────────────────────────────────────────────


class BuyOnBar3Strategy(Strategy):
    """在第 3 根 bar 买入，第 8 根 bar 卖出（确定性策略，方便断言）。"""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self._bar_index == 3 and self.position["size"] == 0:
            self.buy(size=0)
        elif self._bar_index == 8 and self.position["size"] > 0:
            self.sell(size=0)


class BuyOnBar5Strategy(Strategy):
    """在第 5 根 bar 买入，第 10 根 bar 卖出。"""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self._bar_index == 5 and self.position["size"] == 0:
            self.buy(size=0)
        elif self._bar_index == 10 and self.position["size"] > 0:
            self.sell(size=0)


class BuyOnBar7Strategy(Strategy):
    """在第 7 根 bar 买入，第 12 根 bar 卖出。"""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self._bar_index == 7 and self.position["size"] == 0:
            self.buy(size=0)
        elif self._bar_index == 12 and self.position["size"] > 0:
            self.sell(size=0)


class NeverTradeStrategy(Strategy):
    """从不交易的策略。"""

    def init(self) -> None:
        pass

    def next(self) -> None:
        pass


# ── extract_factor_signals 测试 ──────────────────────────────────────────────


class TestExtractFactorSignals:
    """测试因子信号提取。"""

    def test_basic_buy_sell_signals(self) -> None:
        """BuyOnBar3Strategy 应在第 3 根 bar 买入、第 8 根 bar 卖出。"""
        from easy_tdx.backtest.combo import extract_factor_signals

        df = _make_df()
        fs = extract_factor_signals(BuyOnBar3Strategy, df)

        assert fs.name == "BuyOnBar3Strategy"
        assert len(fs.buy_mask) == len(df)
        assert len(fs.sell_mask) == len(df)

        # 第 3 根 bar 买入
        assert fs.buy_mask[3] is np.True_
        # 其他 bar 不买入
        buy_count = int(np.sum(fs.buy_mask))
        assert buy_count == 1

        # 第 8 根 bar 卖出
        assert fs.sell_mask[8] is np.True_
        sell_count = int(np.sum(fs.sell_mask))
        assert sell_count == 1

    def test_never_trade_strategy(self) -> None:
        """从不交易的策略应产生全空遮罩。"""
        from easy_tdx.backtest.combo import extract_factor_signals

        df = _make_df()
        fs = extract_factor_signals(NeverTradeStrategy, df)

        assert int(np.sum(fs.buy_mask)) == 0
        assert int(np.sum(fs.sell_mask)) == 0

    def test_real_ma_strategy(self) -> None:
        """真实 MA 策略的信号提取应有交易信号。"""
        from easy_tdx.backtest.combo import extract_factor_signals

        # 用较长数据确保有交叉
        df = _make_df(n=200, seed=123)

        class MAStrategy(Strategy):
            def init(self) -> None:
                self.ma5 = self.I(MyTT.MA, self.data.close, 5)
                self.ma20 = self.I(MyTT.MA, self.data.close, 20)

            def next(self) -> None:
                if self._bar_index < 1:
                    return
                prev_ma5 = self.ma5[self._bar_index - 1]
                prev_ma20 = self.ma20[self._bar_index - 1]
                curr_ma5 = self.ma5[self._bar_index]
                curr_ma20 = self.ma20[self._bar_index]
                if prev_ma5 <= prev_ma20 and curr_ma5 > curr_ma20:
                    self.buy(size=0)
                elif prev_ma5 >= prev_ma20 and curr_ma5 < curr_ma20:
                    if self.position["size"] > 0:
                        self.sell(size=0)

        fs = extract_factor_signals(MAStrategy, df)
        # 200 bar 数据应该至少有一次买卖
        assert int(np.sum(fs.buy_mask)) >= 1
        assert int(np.sum(fs.sell_mask)) >= 0  # 可能没有卖（最后还在持仓）


# ── combine_masks 测试 ──────────────────────────────────────────────────────


class TestCombineMasks:
    """测试信号遮罩合并。"""

    def test_and_mode(self) -> None:
        """AND 模式：只有所有因子都看多才买入。"""
        from easy_tdx.backtest.combo import FactorSignals, combine_masks

        n = 20
        # 因子 A: bar 3 买入, bar 8 卖出
        fs_a = FactorSignals(
            name="A",
            buy_mask=np.array([i == 3 for i in range(n)]),
            sell_mask=np.array([i == 8 for i in range(n)]),
        )
        # 因子 B: bar 3 买入, bar 10 卖出
        fs_b = FactorSignals(
            name="B",
            buy_mask=np.array([i == 3 for i in range(n)]),
            sell_mask=np.array([i == 10 for i in range(n)]),
        )

        buy, sell = combine_masks([fs_a, fs_b], mode="AND")

        # bar 3 两因子都看多 → AND 买入
        assert buy[3] is np.True_
        # 其他 bar 不买入
        assert int(np.sum(buy)) == 1

        # 卖出：只有 bar 8 两因子都看空？不是，A 在 8 卖，B 在 10 卖 → AND 无交集
        assert int(np.sum(sell)) == 0

    def test_or_mode(self) -> None:
        """OR 模式：任一因子看多就买入。"""
        from easy_tdx.backtest.combo import FactorSignals, combine_masks

        n = 20
        fs_a = FactorSignals(
            name="A",
            buy_mask=np.array([i == 3 for i in range(n)]),
            sell_mask=np.array([i == 8 for i in range(n)]),
        )
        fs_b = FactorSignals(
            name="B",
            buy_mask=np.array([i == 5 for i in range(n)]),
            sell_mask=np.array([i == 10 for i in range(n)]),
        )

        buy, sell = combine_masks([fs_a, fs_b], mode="OR")

        # bar 3 和 bar 5 都应该买入
        assert buy[3] is np.True_
        assert buy[5] is np.True_
        assert int(np.sum(buy)) == 2

        # bar 8 和 bar 10 都应该卖出
        assert sell[8] is np.True_
        assert sell[10] is np.True_
        assert int(np.sum(sell)) == 2

    def test_majority_mode_2_factors(self) -> None:
        """MAJORITY 模式（2 因子）：过半 = >1 → 需要两个都同意（等同 AND）。"""
        from easy_tdx.backtest.combo import FactorSignals, combine_masks

        n = 20
        fs_a = FactorSignals(
            name="A",
            buy_mask=np.array([i == 3 for i in range(n)]),
            sell_mask=np.array([i == 8 for i in range(n)]),
        )
        fs_b = FactorSignals(
            name="B",
            buy_mask=np.array([i == 3 for i in range(n)]),
            sell_mask=np.array([i == 10 for i in range(n)]),
        )

        buy, sell = combine_masks([fs_a, fs_b], mode="MAJORITY")

        # 2 因子 MAJORITY: threshold = 2/2 = 1, need > 1 → need 2 个同意
        assert buy[3] is np.True_
        assert int(np.sum(buy)) == 1

    def test_majority_mode_3_factors(self) -> None:
        """MAJORITY 模式（3 因子）：过半 = >1.5 → 需要至少 2 个同意。"""
        from easy_tdx.backtest.combo import FactorSignals, combine_masks

        n = 20
        fs_a = FactorSignals(
            name="A",
            buy_mask=np.array([i == 5 for i in range(n)]),
            sell_mask=np.array([i == 10 for i in range(n)]),
        )
        fs_b = FactorSignals(
            name="B",
            buy_mask=np.array([i == 5 for i in range(n)]),
            sell_mask=np.array([i == 12 for i in range(n)]),
        )
        fs_c = FactorSignals(
            name="C",
            buy_mask=np.array([i == 7 for i in range(n)]),
            sell_mask=np.array([i == 10 for i in range(n)]),
        )

        buy, sell = combine_masks([fs_a, fs_b, fs_c], mode="MAJORITY")

        # bar 5: A 和 B 同意（2/3），满足 > 1.5 → 买入
        assert buy[5] is np.True_
        # bar 7: 只有 C 同意（1/3），不满足 → 不买入
        assert buy[7] is np.False_
        assert int(np.sum(buy)) == 1

        # bar 10: A 和 C 同意卖出（2/3），满足 → 卖出
        assert sell[10] is np.True_
        # bar 12: 只有 B 同意（1/3），不满足 → 不卖出
        assert sell[12] is np.False_
        assert int(np.sum(sell)) == 1

    def test_invalid_mode_raises(self) -> None:
        """无效合并模式应抛出 ValueError。"""
        from easy_tdx.backtest.combo import FactorSignals, combine_masks

        n = 10
        fs = FactorSignals(
            name="X",
            buy_mask=np.zeros(n, dtype=bool),
            sell_mask=np.zeros(n, dtype=bool),
        )
        with pytest.raises(ValueError, match="不支持的合并模式"):
            combine_masks([fs, fs], mode="INVALID")


# ── CombinationRunner 测试 ──────────────────────────────────────────────────


class TestCombinationRunner:
    """测试组合回测运行器。"""

    def test_run_combination_and(self) -> None:
        """运行 AND 组合：两个确定性策略在第 3 和第 5 bar 都不重叠 → AND 无交易。"""
        from easy_tdx.backtest.combo import CombinationRunner

        df = _make_df()
        runner = CombinationRunner(
            strategy_classes=[BuyOnBar3Strategy, BuyOnBar5Strategy],
            df=df,
            cash=100000.0,
        )
        result = runner.run_combination(indices=[0, 1], mode="AND")

        # BuyOnBar3 在 bar 3 买, BuyOnBar5 在 bar 5 买 → AND 无交集
        assert result.performance["total_trades"] == 0

    def test_run_combination_or(self) -> None:
        """运行 OR 组合：两个策略买入信号取并集。"""
        from easy_tdx.backtest.combo import CombinationRunner

        df = _make_df()
        runner = CombinationRunner(
            strategy_classes=[BuyOnBar3Strategy, BuyOnBar5Strategy],
            df=df,
            cash=100000.0,
        )
        result = runner.run_combination(indices=[0, 1], mode="OR")

        # OR 模式：bar 3 和 bar 5 都会触发买入信号
        # 但由于仓位管理，实际成交可能有限
        assert result.performance["total_trades"] >= 1

    def test_screen_2_factors(self) -> None:
        """screen 遍历所有 2 因子组合。"""
        from easy_tdx.backtest.combo import CombinationRunner

        df = _make_df()
        runner = CombinationRunner(
            strategy_classes=[BuyOnBar3Strategy, BuyOnBar5Strategy, BuyOnBar7Strategy],
            df=df,
            cash=100000.0,
        )
        results = runner.screen(combo_sizes=(2,), mode="OR")

        # C(3, 2) = 3 组合
        assert len(results) == 3

        # 每个结果应有名称和绩效
        for r in results:
            assert " + " in r.name
            assert r.result.performance is not None

    def test_screen_2_and_3_factors(self) -> None:
        """screen 同时遍历 2 和 3 因子组合。"""
        from easy_tdx.backtest.combo import CombinationRunner

        df = _make_df()
        runner = CombinationRunner(
            strategy_classes=[BuyOnBar3Strategy, BuyOnBar5Strategy, BuyOnBar7Strategy],
            df=df,
            cash=100000.0,
        )
        results = runner.screen(combo_sizes=(2, 3), mode="OR")

        # C(3, 2) + C(3, 3) = 3 + 1 = 4
        assert len(results) == 4

        # 应按总收益率降序排列
        returns = [r.result.performance["total_return"] for r in results]
        assert returns == sorted(returns, reverse=True)

    def test_screen_with_never_trade(self) -> None:
        """包含 NeverTradeStrategy 的组合不应崩溃。"""
        from easy_tdx.backtest.combo import CombinationRunner

        df = _make_df()
        runner = CombinationRunner(
            strategy_classes=[BuyOnBar3Strategy, NeverTradeStrategy],
            df=df,
            cash=100000.0,
        )
        results = runner.screen(combo_sizes=(2,), mode="AND", filter_zero_trades=False)

        # C(2, 2) = 1，AND 模式下无交易
        assert len(results) == 1
        assert results[0].result.performance["total_trades"] == 0

    def test_screen_with_zero_trade_filtered(self) -> None:
        """screen 默认过滤零交易组合（filter_zero_trades=True）。"""
        from easy_tdx.backtest.combo import CombinationRunner

        df = _make_df()
        runner = CombinationRunner(
            strategy_classes=[BuyOnBar3Strategy, BuyOnBar5Strategy, NeverTradeStrategy],
            df=df,
            cash=100000.0,
        )
        # AND 模式：大部分组合无交集 → 零交易
        results = runner.screen(combo_sizes=(2,), mode="AND", filter_zero_trades=True)

        # 所有 AND 组合应该都是零交易（信号不重叠），过滤后为空
        assert len(results) == 0
