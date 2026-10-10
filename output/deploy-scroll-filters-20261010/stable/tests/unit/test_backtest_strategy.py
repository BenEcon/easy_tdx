"""测试策略基类和数据代理。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.strategy import (
    Strategy,
    StrategyDataProxy,
    _SeriesAccessor,
    crossover,
)

# ── 辅助函数 ─────────────────────────────────────────────────────────────────────


def _make_df(n: int = 20, seed: int = 42) -> pd.DataFrame:
    """构造随机 OHLCV DataFrame。

    Args:
        n: K线数量
        seed: 随机种子

    Returns:
        DataFrame with columns: datetime, open, close, high, low, vol, amount
    """
    rng = np.random.default_rng(seed)
    base = 10.0
    prices = base + rng.random(n) * 5

    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=n, freq="D"),
            "open": prices,
            "close": prices + rng.random(n) - 0.5,
            "high": prices + rng.random(n),
            "low": prices - rng.random(n),
            "vol": rng.integers(1000, 10000, n),
            "amount": rng.integers(100000, 1000000, n),
        }
    )
    # 确保 high >= max(open, close), low <= min(open, close)
    df["high"] = df[["open", "close", "high"]].max(axis=1)
    df["low"] = df[["open", "close", "low"]].min(axis=1)
    return df


def _make_df_with_extras(n: int = 20) -> pd.DataFrame:
    """构造带额外列的 DataFrame（MACD_DIF, BOLL_UPPER）。

    Args:
        n: K线数量

    Returns:
        DataFrame with standard OHLCV columns + MACD_DIF, BOLL_UPPER
    """
    df = _make_df(n)
    rng = np.random.default_rng(42)

    # 添加额外列
    df["MACD_DIF"] = rng.random(n) * 2 - 1
    df["BOLL_UPPER"] = df["close"] + rng.random(n) * 2

    return df


# ── TestSeriesAccessor ────────────────────────────────────────────────────────────


class TestSeriesAccessor:
    """测试 _SeriesAccessor 数据访问器。"""

    def test_current_value(self) -> None:
        """测试获取当前值 [0]。"""
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        acc = _SeriesAccessor(arr, bar_index=2)
        assert acc[0] == 3.0

    def test_previous_value(self) -> None:
        """测试获取前一根 [-1]。"""
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        acc = _SeriesAccessor(arr, bar_index=2)
        assert acc[-1] == 2.0

    def test_previous_two(self) -> None:
        """测试获取前两根 [-2]。"""
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        acc = _SeriesAccessor(arr, bar_index=2)
        assert acc[-2] == 1.0

    def test_index_out_of_bounds_negative(self) -> None:
        """测试索引越界（负方向）返回 NaN，而非抛 IndexError。

        回测早期 bar_index=0 时 close[-1] 等回溯访问不应崩溃（见 issue #23），
        返回 NaN 让策略自然跳过预热期。
        """
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        acc = _SeriesAccessor(arr, bar_index=0)
        val = acc[-1]
        assert np.isnan(val)

    def test_len(self) -> None:
        """测试 __len__ 返回数组长度。"""
        arr = np.array([1.0, 2.0, 3.0])
        acc = _SeriesAccessor(arr, bar_index=1)
        assert len(acc) == 3

    def test_array_conversion(self) -> None:
        """测试 __array__ 转为 numpy 数组。"""
        arr = np.array([1.0, 2.0, 3.0])
        acc = _SeriesAccessor(arr, bar_index=1)
        result = np.asarray(acc)
        np.testing.assert_array_equal(result, arr)

    def test_raw_property(self) -> None:
        """测试 raw 属性返回原始数组。"""
        arr = np.array([1.0, 2.0, 3.0])
        acc = _SeriesAccessor(arr, bar_index=1)
        np.testing.assert_array_equal(acc.raw, arr)


# ── TestStrategyDataProxy ─────────────────────────────────────────────────────────


class TestStrategyDataProxy:
    """测试 StrategyDataProxy 数据代理。"""

    def test_basic_columns(self) -> None:
        """测试标准 OHLCV 列访问。"""
        df = _make_df(n=10)
        proxy = StrategyDataProxy(df)
        proxy._set_index(5)

        assert isinstance(proxy.open[0], float)
        assert isinstance(proxy.close[0], float)
        assert isinstance(proxy.high[0], float)
        assert isinstance(proxy.low[0], float)
        assert isinstance(proxy.vol[0], float)
        assert isinstance(proxy.amount[0], float)

    def test_previous_bar(self) -> None:
        """测试访问前一根 bar 的数据。"""
        df = _make_df(n=10)
        proxy = StrategyDataProxy(df)
        proxy._set_index(5)

        # close[0] 应该等于 df["close"].iloc[5]
        assert proxy.close[0] == pytest.approx(df["close"].iloc[5])
        # close[-1] 应该等于 df["close"].iloc[4]
        assert proxy.close[-1] == pytest.approx(df["close"].iloc[4])

    def test_extra_columns_via_getattr(self) -> None:
        """测试通过 __getattr__ 访问额外列。"""
        df = _make_df_with_extras(n=10)
        proxy = StrategyDataProxy(df)
        proxy._set_index(5)

        # MACD_DIF 和 BOLL_UPPER 应该可以访问
        assert isinstance(proxy.MACD_DIF[0], float)
        assert isinstance(proxy.BOLL_UPPER[0], float)

        # 验证值正确
        assert proxy.MACD_DIF[0] == pytest.approx(df["MACD_DIF"].iloc[5])
        assert proxy.BOLL_UPPER[0] == pytest.approx(df["BOLL_UPPER"].iloc[5])

    def test_missing_column_raises(self) -> None:
        """测试访问不存在的列抛出 AttributeError。"""
        df = _make_df(n=10)
        proxy = StrategyDataProxy(df)
        proxy._set_index(5)

        with pytest.raises(AttributeError, match="列 'NONEXISTENT' 不存在"):
            _ = proxy.NONEXISTENT[0]


# ── TestCrossover ───────────────────────────────────────────────────────────────


class TestCrossover:
    """测试 crossover 金叉检测函数。"""

    def test_crossover_true(self) -> None:
        """测试金叉检测（a 上穿 b）。"""
        a = np.array([1, 2, 3, 4, 5])
        b = np.array([5, 4, 3, 2, 1])
        mask = crossover(a, b)

        # 索引 3 处：a[2]=3 <= b[2]=3, a[3]=4 > b[3]=2 → 金叉
        assert mask[3]
        # 其他位置无金叉
        assert not mask[0]
        assert not mask[1]
        assert not mask[2]
        assert not mask[4]

    def test_crossover_false_no_cross(self) -> None:
        """测试无金叉情况（a 全在 b 下方）。"""
        a = np.array([1, 2, 3, 4, 5])
        b = np.array([6, 7, 8, 9, 10])
        mask = crossover(a, b)

        # 全部 False
        assert not np.any(mask)

    def test_crossover_series(self) -> None:
        """测试接受 pd.Series 参数。"""
        a = pd.Series([1, 2, 3, 4, 5])
        b = pd.Series([5, 4, 3, 2, 1])
        mask = crossover(a, b)

        assert mask[3]

    def test_crossover_with_accessor(self) -> None:
        """测试接受 _SeriesAccessor 参数。"""
        arr_a = np.array([1, 2, 3, 4, 5])
        arr_b = np.array([5, 4, 3, 2, 1])
        acc_a = _SeriesAccessor(arr_a, bar_index=4)
        acc_b = _SeriesAccessor(arr_b, bar_index=4)

        mask = crossover(acc_a, acc_b)
        assert mask[3]


# ── TestStrategyBase ──────────────────────────────────────────────────────────────


class TestStrategyBase:
    """测试 Strategy 策略基类。"""

    def test_subclass_init_and_next(self) -> None:
        """测试子类 init() 和 next() 被调用。"""

        class SimpleStrategy(Strategy):
            init_called = False
            next_called_count = 0

            def init(self) -> None:
                SimpleStrategy.init_called = True

            def next(self) -> None:
                SimpleStrategy.next_called_count += 1

        df = _make_df(n=10)
        strategy = SimpleStrategy()
        strategy._bind_data(df)
        strategy._call_init()

        assert SimpleStrategy.init_called is True

        # 模拟引擎遍历所有 bar
        for i in range(len(df)):
            strategy._set_bar_index(i)
            strategy._call_next()

        assert SimpleStrategy.next_called_count == 10

    def test_buy_sell_recording(self) -> None:
        """测试 buy() 和 sell() 创建 Signal。"""

        class SignalStrategy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                if self._bar_index == 5:
                    self.buy(size=100, price=10.0, stop_loss=9.0, take_profit=11.0)
                elif self._bar_index == 8:
                    self.sell(size=100, price=10.5)

        df = _make_df(n=10)
        strategy = SignalStrategy()
        strategy._bind_data(df)
        strategy._call_init()

        for i in range(len(df)):
            strategy._set_bar_index(i)
            strategy._call_next()

        signals = strategy._clear_signals()

        assert len(signals) == 2
        assert signals[0].direction == "BUY"
        assert signals[0].size == 100
        assert signals[0].price == 10.0
        assert signals[0].stop_loss == 9.0
        assert signals[0].take_profit == 11.0

        assert signals[1].direction == "SELL"
        assert signals[1].size == 100
        assert signals[1].price == 10.5

    def test_I_registers_indicator(self) -> None:
        """测试 self.I() 注册指标。"""
        from easy_tdx.MyTT import MA

        class IndicatorStrategy(Strategy):
            def init(self) -> None:
                self.ma5 = self.I(MA, self.data.close, 5)
                self.ma20 = self.I(MA, self.data.close, 20)

            def next(self) -> None:
                pass

        df = _make_df(n=50)
        strategy = IndicatorStrategy()
        strategy._bind_data(df)
        strategy._call_init()

        # 验证指标长度正确（MA 会产生 nan，但长度不变）
        assert len(strategy.ma5) == 50
        assert len(strategy.ma20) == 50

        # 验证指标已注册
        assert "MA" in strategy._indicators

    def test_full_position_buy(self) -> None:
        """测试全仓买入（size=0）。"""

        class FullPositionStrategy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                if self._bar_index == 5:
                    self.buy(size=0)  # 全仓

        df = _make_df(n=10)
        strategy = FullPositionStrategy()
        strategy._bind_data(df)
        strategy._call_init()

        for i in range(len(df)):
            strategy._set_bar_index(i)
            strategy._call_next()

        signals = strategy._clear_signals()

        assert len(signals) == 1
        assert signals[0].direction == "BUY"
        assert signals[0].size == 0  # 0 表示全仓

    def test_data_property(self) -> None:
        """测试 self.data 属性返回 StrategyDataProxy。"""
        df = _make_df(n=10)

        class DataAccessStrategy(Strategy):
            def init(self) -> None:
                # 验证 data 可访问
                assert hasattr(self.data, "close")
                assert hasattr(self.data, "open")

            def next(self) -> None:
                # 验证 next() 中也可访问
                assert self.data.close[0] > 0

        strategy = DataAccessStrategy()
        strategy._bind_data(df)
        strategy._call_init()

        for i in range(len(df)):
            strategy._set_bar_index(i)
            strategy._call_next()

    def test_position_property(self) -> None:
        """测试 self.position 属性。"""
        df = _make_df(n=10)

        class PositionStrategy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                # 初始状态无持仓
                assert self.position["size"] == 0.0

        strategy = PositionStrategy()
        strategy._bind_data(df)
        strategy._call_init()

        for i in range(len(df)):
            strategy._set_bar_index(i)
            strategy._call_next()

    def test_get_datetime(self) -> None:
        """测试 _get_datetime() 方法。"""
        df = _make_df(n=10)

        class DateTimeStrategy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                # 验证 datetime 正确（YYYYMMDD 格式）
                dt = self._get_datetime()
                assert isinstance(dt, int)
                assert 20240101 <= dt <= 20241231

        strategy = DateTimeStrategy()
        strategy._bind_data(df)
        strategy._call_init()

        for i in range(len(df)):
            strategy._set_bar_index(i)
            strategy._call_next()

    def test_clear_signals(self) -> None:
        """测试 _clear_signals() 清空信号列表。"""

        class ClearSignalStrategy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                self.buy(size=100)

        df = _make_df(n=10)
        strategy = ClearSignalStrategy()
        strategy._bind_data(df)
        strategy._call_init()

        # 第一轮
        for i in range(len(df)):
            strategy._set_bar_index(i)
            strategy._call_next()
        signals1 = strategy._clear_signals()
        assert len(signals1) == 10

        # 第二轮（无新信号）
        signals2 = strategy._clear_signals()
        assert len(signals2) == 0

    def test_buy_without_bind_raises(self) -> None:
        """测试未绑定数据时调用 buy() 抛出错误。"""

        class BadStrategy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                self.buy(size=100)

        strategy = BadStrategy()
        # 未调用 _bind_data()

        with pytest.raises(RuntimeError, match="策略未绑定数据"):
            strategy._call_init()
            strategy._set_bar_index(0)
            strategy._call_next()

    def test_chanlun_property(self) -> None:
        """测试 chanlun 属性（预留）。"""
        df = _make_df(n=10)

        class ChanlunStrategy(Strategy):
            def init(self) -> None:
                assert self.chanlun is None

            def next(self) -> None:
                pass

        strategy = ChanlunStrategy()
        strategy._bind_data(df)
        strategy._call_init()

        for i in range(len(df)):
            strategy._set_bar_index(i)
            strategy._call_next()


class TestWarmupAndLookback:
    """issue #23: close[-1] 在首根 bar 不应崩溃；warmup 期不产生信号。"""

    def test_lookback_negative_returns_nan_at_bar_zero(self) -> None:
        """_SeriesAccessor 负向越界返回 NaN（非 IndexError）。"""
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        acc = _SeriesAccessor(arr, bar_index=0)
        assert np.isnan(acc[-1])
        assert np.isnan(acc[-2])

    def test_engine_no_crash_on_close_minus_one(self) -> None:
        """文档示例：next() 里访问 close[-1]/close[-2] 不应抛 IndexError。

        回归 issue #23：DualMAStrategy 在首根 bar 访问 close[-1] 崩溃。
        """
        from easy_tdx.backtest.engine import BacktestEngine

        class LookbackStrategy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                # 文档记录的访问方式
                _ = self.data.close[0]
                _ = self.data.close[-1]
                _ = self.data.close[-2]

        df = _make_df(n=50)
        engine = BacktestEngine(LookbackStrategy, cash=100000)
        # 修复前：抛 IndexError；修复后：正常跑完
        result = engine.run(df)
        assert len(result.equity_curve) == 50

    def test_warmup_bars_skips_early_next(self) -> None:
        """warmup_bars=N 时前 N 根不调用 next()、不产生信号。"""
        from easy_tdx.backtest.engine import BacktestEngine

        next_bars: list[int] = []

        class TrackingStrategy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                next_bars.append(self._bar_index)
                self.buy(size=100)

        df = _make_df(n=20)
        engine = BacktestEngine(TrackingStrategy, cash=100000, warmup_bars=5)
        engine.run(df)
        # warmup 期（bar 0~4）不被调用
        assert next_bars == list(range(5, 20))

    def test_warmup_bars_default_zero_backward_compat(self) -> None:
        """默认 warmup_bars=0：每根 bar 都调用 next()（向后兼容）。"""
        from easy_tdx.backtest.engine import BacktestEngine

        next_count = 0

        class CountStrategy(Strategy):
            def init(self) -> None:
                pass

            def next(self) -> None:
                nonlocal next_count
                next_count += 1

        df = _make_df(n=15)
        BacktestEngine(CountStrategy, cash=100000).run(df)
        assert next_count == 15
