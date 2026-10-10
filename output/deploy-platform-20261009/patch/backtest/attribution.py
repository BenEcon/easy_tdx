"""归因分析模块。"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class AttributionReport:
    """归因分析报告。"""

    total_return: float = 0.0
    # Brinson 归因
    allocation_return: float = 0.0
    selection_return: float = 0.0
    interaction_return: float = 0.0
    # 因子归因
    factor_returns: dict[str, float] = field(default_factory=dict)
    specific_return: float = 0.0
    # 成本归因
    total_trade_cost: float = 0.0
    slippage_cost: float = 0.0
    commission_cost: float = 0.0
    stamp_tax_cost: float = 0.0


class AttributionAnalyzer:
    """收益归因分析器。

    支持三种归因视角：
    1. 成本归因：分解交易成本的来源（佣金/滑点/印花税）
    2. Brinson 归因：分解超额收益（配置 vs 选股）
    3. 因子归因：分解收益为因子贡献 + 特质收益
    """

    def __init__(
        self,
        trades: pd.DataFrame,
        equity_curve: pd.DataFrame,
        benchmark: pd.DataFrame | None = None,
        factor_exposures: pd.DataFrame | None = None,
        factor_returns: pd.DataFrame | None = None,
        groups: pd.DataFrame | None = None,
    ) -> None:
        self._trades = trades
        self._equity_curve = equity_curve
        self._benchmark = benchmark
        self._factor_exposures = factor_exposures
        self._factor_returns = factor_returns
        self._groups = groups

    def cost_attribution(self) -> AttributionReport:
        """成本归因：分解交易成本。"""
        if self._trades.empty:
            return AttributionReport()

        valid = (
            self._trades[~self._trades["rejected"]]
            if "rejected" in self._trades.columns
            else self._trades
        )

        slippage_cost = float(valid["slippage"].sum()) if "slippage" in valid.columns else 0.0
        commission_cost = float(valid["commission"].sum()) if "commission" in valid.columns else 0.0

        total_trade_cost = slippage_cost + commission_cost

        # 估算印花税（卖出交易 0.1%）
        sell_mask = (
            valid["direction"] == "SELL" if "direction" in valid.columns else pd.Series(dtype=bool)
        )
        stamp_tax_cost = 0.0
        if sell_mask.any():
            sell_trades = valid[sell_mask]
            if "price" in sell_trades.columns and "size" in sell_trades.columns:
                stamp_tax_cost = float((sell_trades["price"] * sell_trades["size"] * 0.001).sum())

        total_return = 0.0
        if not self._equity_curve.empty and "total" in self._equity_curve.columns:
            total_arr = self._equity_curve["total"].to_numpy()
            if len(total_arr) >= 2 and total_arr[0] > 0:
                total_return = float((total_arr[-1] / total_arr[0]) - 1)

        return AttributionReport(
            total_return=total_return,
            total_trade_cost=total_trade_cost,
            slippage_cost=slippage_cost,
            commission_cost=commission_cost,
            stamp_tax_cost=stamp_tax_cost,
        )

    def brinson_attribution(self) -> AttributionReport:
        """Brinson-Hood-Beebower 归因分解。"""
        cost_report = self.cost_attribution()

        if self._benchmark is None:
            return cost_report

        if self._equity_curve.empty:
            return cost_report

        total_arr = self._equity_curve["total"].to_numpy()
        if len(total_arr) < 2 or total_arr[0] <= 0:
            return cost_report

        portfolio_return = float((total_arr[-1] / total_arr[0]) - 1)

        benchmark_return = 0.0
        if "total" in self._benchmark.columns:
            bench_arr = self._benchmark["total"].to_numpy()
            if len(bench_arr) >= 2 and bench_arr[0] > 0:
                benchmark_return = float((bench_arr[-1] / bench_arr[0]) - 1)

        if self._groups is not None and not self._groups.empty:
            allocation, selection, interaction = self._compute_grouped_brinson(
                portfolio_return,
                benchmark_return,
            )
        else:
            excess_return = portfolio_return - benchmark_return
            allocation = 0.0
            selection = excess_return
            interaction = 0.0

        return AttributionReport(
            total_return=portfolio_return,
            allocation_return=allocation,
            selection_return=selection,
            interaction_return=interaction,
            total_trade_cost=cost_report.total_trade_cost,
            slippage_cost=cost_report.slippage_cost,
            commission_cost=cost_report.commission_cost,
            stamp_tax_cost=cost_report.stamp_tax_cost,
        )

    def _compute_grouped_brinson(
        self,
        portfolio_return: float,
        benchmark_return: float,
    ) -> tuple[float, float, float]:
        """按组计算 Brinson 归因。"""
        if self._groups is None or self._groups.empty:
            return 0.0, portfolio_return - benchmark_return, 0.0

        allocation = 0.0
        selection = 0.0
        interaction = 0.0

        if (
            "portfolio_weight" in self._groups.columns
            and "benchmark_weight" in self._groups.columns
        ):
            pw = self._groups["portfolio_weight"].to_numpy()
            bw = self._groups["benchmark_weight"].to_numpy()

            if (
                "portfolio_return" in self._groups.columns
                and "benchmark_return" in self._groups.columns
            ):
                pr = self._groups["portfolio_return"].to_numpy()
                br = self._groups["benchmark_return"].to_numpy()

                allocation = float(np.sum((pw - bw) * br))
                selection = float(np.sum(bw * (pr - br)))
                interaction = float(np.sum((pw - bw) * (pr - br)))

        return allocation, selection, interaction

    def factor_attribution(self) -> AttributionReport:
        """因子归因分解。"""
        cost_report = self.cost_attribution()

        if self._factor_exposures is None or self._factor_returns is None:
            return cost_report

        if self._factor_exposures.empty or self._factor_returns.empty:
            return cost_report

        factor_contributions: dict[str, float] = {}
        common_factors = set(self._factor_exposures.columns) & set(self._factor_returns.columns)
        for factor_name in common_factors:
            exposures = self._factor_exposures[factor_name].to_numpy()
            returns = self._factor_returns[factor_name].to_numpy()
            min_len = min(len(exposures), len(returns))
            if min_len > 0:
                contrib = float(np.sum(exposures[:min_len] * returns[:min_len]))
                factor_contributions[factor_name] = contrib

        total_factor_return = sum(factor_contributions.values())

        total_arr = self._equity_curve["total"].to_numpy()
        total_return = 0.0
        if len(total_arr) >= 2 and total_arr[0] > 0:
            total_return = float((total_arr[-1] / total_arr[0]) - 1)

        specific_return = total_return - total_factor_return

        return AttributionReport(
            total_return=total_return,
            factor_returns=factor_contributions,
            specific_return=specific_return,
            total_trade_cost=cost_report.total_trade_cost,
            slippage_cost=cost_report.slippage_cost,
            commission_cost=cost_report.commission_cost,
            stamp_tax_cost=cost_report.stamp_tax_cost,
        )

    def full_report(self) -> AttributionReport:
        """完整归因报告。"""
        if self._factor_exposures is not None and self._factor_returns is not None:
            return self.factor_attribution()
        if self._benchmark is not None:
            return self.brinson_attribution()
        return self.cost_attribution()
