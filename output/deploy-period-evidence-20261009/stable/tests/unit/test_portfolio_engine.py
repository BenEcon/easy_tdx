"""单元测试：多标的组合回测引擎."""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.backtest.portfolio_engine import (
    PortfolioBacktestEngine,
    StockData,
)
from easy_tdx.backtest.strategy import Strategy


class SimpleBuyStrategy(Strategy):
    """简单策略：bar 5 买入，bar 30 卖出."""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self._bar_index == 5 and self.position["size"] == 0:
            self.buy(size=0)
        elif self._bar_index == 30 and self.position["size"] > 0:
            self.sell(size=0)


def _make_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """生成随机 OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = low + rng.uniform(0, high - low, n)
    vol = rng.integers(1000000, 10000000, n).astype(float)

    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=n, freq="D"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": vol * close,
        }
    )


class TestPortfolioBacktest:
    """测试组合回测引擎."""

    def test_basic_portfolio_run(self) -> None:
        """基本组合回测应正常完成."""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("600000", "SH", _make_df(100, seed=99)),
        ]

        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=200000,
        )
        result = engine.run()

        assert result.total_performance is not None
        assert "total_return" in result.total_performance
        assert len(result.individual_results) == 2
        assert result.total_performance["total_stocks"] == 2

    def test_equal_allocation(self) -> None:
        """均等分配：每只标的资金应为总资金/标的数."""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("000002", "SZ", _make_df(100, seed=99)),
        ]

        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=100000,
            allocation="equal",
        )
        result = engine.run()

        # 每只标的分配 50000
        assert result.equity_allocation["SZ000001"] == 0.5
        assert result.equity_allocation["SZ000002"] == 0.5

    def test_empty_stocks(self) -> None:
        """空标的列表无收益区间，收益不可用，不能伪造零收益。"""
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=[],
            total_cash=100000,
        )
        result = engine.run()

        assert np.isnan(result.total_performance["total_return"])
        assert result.total_performance["total_trades"] == 0
        assert result.performance_basis["metric_status"]["total_return"]["state"] == "unavailable"
        assert len(result.individual_results) == 0

    def test_to_dict_serializable(self) -> None:
        """结果应可序列化为字典."""
        stocks = [StockData("000001", "SZ", _make_df(100))]
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=100000,
        )
        result = engine.run()
        d = result.to_dict()

        assert "total_performance" in d
        assert "individual_results" in d
        assert "equity_allocation" in d
        assert "combined_equity" in d


class TestStrategyInstanceParams:
    """测试策略实例（带参数）的透传——Phase 3 引擎改造的核心."""

    def test_strategy_instance_params_passed_through(self) -> None:
        """传策略实例时，参数应透传到每个标的（而非用默认值）."""
        from easy_tdx.backtest.strategies import get_registry

        entry = get_registry().get("ma_cross")
        strategy_instance = entry.build({"fast": 10, "slow": 30})

        stocks = [
            StockData("000001", "SZ", _make_df(120, seed=1)),
            StockData("000002", "SZ", _make_df(120, seed=2)),
        ]
        engine = PortfolioBacktestEngine(
            strategy=strategy_instance,
            stocks=stocks,
            total_cash=200000,
        )
        result = engine.run()

        assert len(result.individual_results) == 2
        for res in result.individual_results.values():
            assert res.performance is not None


class TestCombinedEquity:
    """测试组合净值曲线生成."""

    def test_combined_equity_generated(self) -> None:
        """组合净值曲线应生成且含 total/drawdown/drawdown_pct 列."""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("600000", "SH", _make_df(100, seed=99)),
        ]
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=200000,
        )
        result = engine.run()

        assert len(result.combined_equity) > 0
        cols = set(result.combined_equity.columns)
        assert {"datetime", "total", "drawdown", "drawdown_pct"} <= cols
        assert result.combined_equity["total"].iloc[0] > 0

    def test_combined_equity_date_alignment(self) -> None:
        """日期范围不同的标的应正确对齐（forward-fill）."""
        stocks = [
            StockData("000001", "SZ", _make_df(80, seed=1)),
            StockData("000002", "SZ", _make_df(100, seed=2)),
        ]
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=200000,
        )
        result = engine.run()

        assert len(result.combined_equity) >= 100

    def test_combined_equity_empty(self) -> None:
        """空标的列表应返回空净值曲线（带表头）."""
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=[],
            total_cash=100000,
        )
        result = engine.run()

        assert len(result.combined_equity) == 0
        assert set(result.combined_equity.columns) == {
            "datetime",
            "total",
            "drawdown",
            "drawdown_pct",
        }
