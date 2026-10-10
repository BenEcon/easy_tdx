"""归因分析单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.attribution import AttributionAnalyzer


def _make_trades(
    n_buys: int = 2,
    n_sells: int = 2,
    commission: float = 10.0,
    slippage: float = 5.0,
) -> pd.DataFrame:
    trades: list[dict[str, object]] = []
    for i in range(n_buys):
        trades.append(
            {
                "datetime": 20240101 + i,
                "direction": "BUY",
                "size": 100,
                "price": 100.0 + i,
                "commission": commission,
                "slippage": slippage,
                "pnl": 0.0,
                "rejected": False,
            }
        )
    for i in range(n_sells):
        trades.append(
            {
                "datetime": 20240110 + i,
                "direction": "SELL",
                "size": 100,
                "price": 110.0 + i,
                "commission": commission,
                "slippage": slippage,
                "pnl": 500.0,
                "rejected": False,
            }
        )
    return pd.DataFrame(trades)


def _make_equity(
    initial: float = 100000.0,
    final: float = 110000.0,
    n: int = 20,
) -> pd.DataFrame:
    total = np.linspace(initial, final, n)
    return pd.DataFrame(
        {
            "datetime": [20240101 + i for i in range(n)],
            "total": total,
            "cash": total * 0.5,
            "position_value": total * 0.5,
        }
    )


def _make_benchmark(
    initial: float = 100000.0,
    final: float = 105000.0,
    n: int = 20,
) -> pd.DataFrame:
    total = np.linspace(initial, final, n)
    return pd.DataFrame(
        {
            "datetime": [20240101 + i for i in range(n)],
            "total": total,
        }
    )


class TestCostAttribution:
    def test_basic_cost_breakdown(self) -> None:
        trades = _make_trades(n_buys=2, n_sells=2, commission=10.0, slippage=5.0)
        eq = _make_equity()
        analyzer = AttributionAnalyzer(trades, eq)
        report = analyzer.cost_attribution()
        assert report.commission_cost == pytest.approx(40.0)
        assert report.slippage_cost == pytest.approx(20.0)
        assert report.total_trade_cost == pytest.approx(60.0)

    def test_total_return(self) -> None:
        trades = _make_trades()
        eq = _make_equity(100000.0, 110000.0)
        analyzer = AttributionAnalyzer(trades, eq)
        report = analyzer.cost_attribution()
        assert report.total_return == pytest.approx(0.1)

    def test_empty_trades(self) -> None:
        trades = pd.DataFrame(
            columns=["datetime", "direction", "size", "price", "commission", "slippage"]
        )
        eq = _make_equity()
        analyzer = AttributionAnalyzer(trades, eq)
        report = analyzer.cost_attribution()
        assert report.total_trade_cost == 0.0

    def test_stamp_tax_estimation(self) -> None:
        trades = _make_trades(n_buys=0, n_sells=1, commission=0.0, slippage=0.0)
        eq = _make_equity()
        analyzer = AttributionAnalyzer(trades, eq)
        report = analyzer.cost_attribution()
        assert report.stamp_tax_cost == pytest.approx(11.0)


class TestBrinsonAttribution:
    def test_no_benchmark_returns_only_total(self) -> None:
        trades = _make_trades()
        eq = _make_equity()
        analyzer = AttributionAnalyzer(trades, eq, benchmark=None)
        report = analyzer.brinson_attribution()
        assert report.total_return == pytest.approx(0.1)
        assert report.allocation_return == 0.0

    def test_with_benchmark_selection(self) -> None:
        trades = _make_trades()
        eq = _make_equity(100000.0, 110000.0)
        bench = _make_benchmark(100000.0, 105000.0)
        analyzer = AttributionAnalyzer(trades, eq, benchmark=bench)
        report = analyzer.brinson_attribution()
        assert report.total_return == pytest.approx(0.1)
        assert report.selection_return == pytest.approx(0.05)

    def test_with_groups_decomposition(self) -> None:
        trades = _make_trades()
        eq = _make_equity(100000.0, 110000.0)
        bench = _make_benchmark(100000.0, 105000.0)
        groups = pd.DataFrame(
            {
                "portfolio_weight": [0.6, 0.4],
                "benchmark_weight": [0.5, 0.5],
                "portfolio_return": [0.15, 0.05],
                "benchmark_return": [0.10, 0.0],
            }
        )
        analyzer = AttributionAnalyzer(trades, eq, benchmark=bench, groups=groups)
        report = analyzer.brinson_attribution()
        assert report.allocation_return == pytest.approx(0.01)
        assert report.selection_return == pytest.approx(0.05)
        assert report.interaction_return == pytest.approx(0.0)


class TestFactorAttribution:
    def test_no_factors_returns_only_cost(self) -> None:
        trades = _make_trades()
        eq = _make_equity()
        analyzer = AttributionAnalyzer(trades, eq)
        report = analyzer.factor_attribution()
        assert report.factor_returns == {}

    def test_basic_factor_decomposition(self) -> None:
        trades = _make_trades()
        eq = _make_equity(100000.0, 110000.0)
        exposures = pd.DataFrame({"momentum": [0.5, 0.3, 0.2], "volatility": [0.1, -0.1, 0.0]})
        returns = pd.DataFrame({"momentum": [0.05, 0.03, 0.02], "volatility": [0.01, -0.02, 0.0]})
        analyzer = AttributionAnalyzer(
            trades,
            eq,
            factor_exposures=exposures,
            factor_returns=returns,
        )
        report = analyzer.factor_attribution()
        assert report.factor_returns["momentum"] == pytest.approx(0.038)
        assert report.factor_returns["volatility"] == pytest.approx(0.003)
        assert report.specific_return == pytest.approx(0.059)

    def test_empty_factor_data(self) -> None:
        trades = _make_trades()
        eq = _make_equity()
        analyzer = AttributionAnalyzer(
            trades,
            eq,
            factor_exposures=pd.DataFrame(),
            factor_returns=pd.DataFrame(),
        )
        report = analyzer.factor_attribution()
        assert report.factor_returns == {}


class TestFullReport:
    def test_prefers_factor_over_brinson(self) -> None:
        trades = _make_trades()
        eq = _make_equity(100000.0, 110000.0)
        bench = _make_benchmark(100000.0, 105000.0)
        exposures = pd.DataFrame({"momentum": [0.5]})
        returns = pd.DataFrame({"momentum": [0.05]})
        analyzer = AttributionAnalyzer(
            trades,
            eq,
            benchmark=bench,
            factor_exposures=exposures,
            factor_returns=returns,
        )
        report = analyzer.full_report()
        assert "momentum" in report.factor_returns
        assert report.specific_return != 0.0

    def test_falls_back_to_cost_only(self) -> None:
        trades = _make_trades()
        eq = _make_equity()
        analyzer = AttributionAnalyzer(trades, eq)
        report = analyzer.full_report()
        assert report.total_trade_cost > 0
        assert report.factor_returns == {}
        assert report.allocation_return == 0.0
