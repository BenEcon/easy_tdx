"""多期调仓回测引擎。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.factor.engine import FactorEngine
from easy_tdx.portfolio.optimizer import WeightOptimizer
from easy_tdx.portfolio.types import PortfolioState, RebalanceResult


class RebalanceEngine:
    """多期调仓回测引擎。"""

    def __init__(
        self,
        optimizer: WeightOptimizer,
        factor_name: str = "momentum_20d",
        n_stocks: int = 50,
        rebalance_freq: str = "M",
        commission: float = 0.0003,
        slippage: float = 0.001,
        cash: float = 1_000_000,
    ) -> None:
        self._optimizer = optimizer
        self._factor_name = factor_name
        self._n_stocks = n_stocks
        self._rebalance_freq = rebalance_freq
        self._commission = commission
        self._slippage = slippage
        self._cash = cash

    def _get_rebalance_dates(self, dates: pd.DatetimeIndex) -> list[int]:
        freq_map = {"W": "W-MON", "M": "M", "Q": "Q"}
        freq = freq_map.get(self._rebalance_freq, "M")
        series = pd.Series(dates, index=dates)
        grouped = series.groupby(series.dt.to_period(freq))
        rebalance_dates = [group.iloc[-1] for _, group in grouped if len(group) > 0]
        return [int(d.strftime("%Y%m%d")) for d in rebalance_dates]

    def run(
        self,
        data: dict[str, pd.DataFrame],
        start_date: int | None = None,
        end_date: int | None = None,
    ) -> RebalanceResult:
        """执行多期回测。"""
        if not data:
            return self._empty_result()
        factor_engine = FactorEngine()

        all_dates: list[pd.Timestamp] = []
        for df in data.values():
            if "datetime" in df.columns:
                all_dates.extend(df["datetime"].tolist())
        if not all_dates:
            return self._empty_result()
        all_dates = sorted(set(all_dates))

        if start_date:
            all_dates = [d for d in all_dates if int(d.strftime("%Y%m%d")) >= start_date]
        if end_date:
            all_dates = [d for d in all_dates if int(d.strftime("%Y%m%d")) <= end_date]
        if not all_dates:
            return self._empty_result()

        rebalance_dates = self._get_rebalance_dates(pd.DatetimeIndex(all_dates))
        rebalance_set = set(rebalance_dates)

        cash = self._cash
        holdings: dict[str, float] = {}
        states: list[PortfolioState] = []
        trades_list: list[dict[str, object]] = []
        equity_records: list[dict[str, object]] = []
        # 已持仓标的的最近已知收盘价。当某标的当日缺 K 线（停牌/上市晚/日历
        # 错位）时，用上一已知价估值，避免持仓市值被错误记为 0 而造成净值单日
        # 假崩塌（issue #31：159915 在 20210208 缺一天数据 → -92% 假回撤）。
        last_known_price: dict[str, float] = {}

        for dt in all_dates:
            date_int = int(dt.strftime("%Y%m%d"))
            is_rebalance = date_int in rebalance_set

            prices: dict[str, float] = {}
            for code, df in data.items():
                if "datetime" in df.columns:
                    row = df[df["datetime"] == dt]
                    if not row.empty:
                        prices[code] = float(row["close"].iloc[0])

            # forward-fill：当日无数据的标的沿用最近已知价（仅对已持仓标的有影响）
            for code in holdings:
                if code not in prices and code in last_known_price:
                    prices[code] = last_known_price[code]
            # 记录本日出现的最新价，供后续缺失日沿用
            last_known_price.update(prices)

            position_value = sum(holdings.get(c, 0) * prices.get(c, 0) for c in holdings)
            total_value = cash + position_value

            if is_rebalance and total_value > 0:
                scores_df = factor_engine.compute_cross_section(
                    data, [self._factor_name], date=date_int
                )
                if not scores_df.empty and scores_df[self._factor_name].notna().any():
                    scores_df = scores_df.rename(columns={self._factor_name: "score"})
                    scores_df = scores_df[["code", "score"]].dropna(subset=["score"])
                    target_weights = self._optimizer.optimize(scores_df, n_stocks=self._n_stocks)
                else:
                    target_weights = {}

                if target_weights:
                    trades_list, cash, holdings = self._rebalance(
                        target_weights, prices, total_value, date_int, trades_list, cash, holdings
                    )

            position_value = sum(holdings.get(c, 0) * prices.get(c, 0) for c in holdings)
            total_value = cash + position_value
            weights: dict[str, float] = {}
            if total_value > 0:
                for c in holdings:
                    if holdings[c] > 0 and c in prices:
                        weights[c] = holdings[c] * prices[c] / total_value

            states.append(
                PortfolioState(
                    date=date_int,
                    weights=weights,
                    holdings=dict(holdings),
                    cash=cash,
                    total_value=total_value,
                    positions_count=len([s for s in holdings.values() if s > 0]),
                )
            )
            equity_records.append(
                {
                    "datetime": date_int,
                    "total": total_value,
                    "cash": cash,
                    "position_value": position_value,
                }
            )

        equity_curve = pd.DataFrame(equity_records)
        trades_df = (
            pd.DataFrame(trades_list)
            if trades_list
            else pd.DataFrame(columns=["datetime", "direction", "code", "shares", "price", "cost"])
        )
        performance = self._compute_performance(equity_curve, trades_df)
        return RebalanceResult(
            rebalance_dates=rebalance_dates,
            states=states,
            trades=trades_df,
            equity_curve=equity_curve,
            performance=performance,
        )

    def _rebalance(
        self,
        target_weights: dict[str, float],
        prices: dict[str, float],
        total_value: float,
        date_int: int,
        trades_list: list[dict[str, object]],
        cash: float,
        holdings: dict[str, float],
    ) -> tuple[list[dict[str, object]], float, dict[str, float]]:
        for code in list(holdings.keys()):
            if code not in target_weights and holdings[code] > 0:
                price = prices.get(code, 0)
                if price > 0:
                    sell_value = holdings[code] * price
                    cost = sell_value * (self._commission + self._slippage)
                    cash += sell_value - cost
                    trades_list.append(
                        {
                            "datetime": date_int,
                            "direction": "SELL",
                            "code": code,
                            "shares": holdings[code],
                            "price": price,
                            "cost": cost,
                        }
                    )
                del holdings[code]

        new_holdings: dict[str, float] = {}
        for code, weight in target_weights.items():
            price = prices.get(code, 0)
            if price <= 0:
                continue
            target_value = total_value * weight
            shares = int(target_value / price / 100) * 100
            if shares > 0:
                new_holdings[code] = shares
                trade_value = shares * price
                cost = trade_value * (self._commission + self._slippage)
                trades_list.append(
                    {
                        "datetime": date_int,
                        "direction": "BUY",
                        "code": code,
                        "shares": shares,
                        "price": price,
                        "cost": cost,
                    }
                )

        cash = total_value - sum(new_holdings.get(c, 0) * prices.get(c, 0) for c in new_holdings)
        holdings.clear()
        holdings.update(new_holdings)
        return trades_list, cash, holdings

    def _compute_performance(
        self, equity_curve: pd.DataFrame, trades_df: pd.DataFrame
    ) -> dict[str, float]:
        if len(equity_curve) < 2:
            return {"total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}
        total = equity_curve["total"].to_numpy()
        total_return = (total[-1] / total[0]) - 1
        n_days = len(total)
        annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1
        peak = np.maximum.accumulate(total)
        # 与 BacktestEngine.PerformanceAnalyzer 一致的正值口径：
        # drawdown_pct = (peak - total) / peak ∈ [0,1]，max_drawdown 取最大值。
        # 此前用 (total-peak)/peak + np.min 返回负值，与 CLI/文档约定不符。
        drawdown_pct = np.divide(
            peak - total,
            peak,
            out=np.zeros_like(peak),
            where=(peak != 0),
        )
        max_drawdown = float(np.max(drawdown_pct))
        daily_ret = np.diff(total) / total[:-1]
        daily_ret = daily_ret[~np.isnan(daily_ret)]
        sharpe = (
            float(np.mean(daily_ret) / np.std(daily_ret) * np.sqrt(252))
            if len(daily_ret) > 1 and np.std(daily_ret) > 0
            else 0.0
        )
        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe": sharpe,
            "total_trades": len(trades_df),
        }

    def _empty_result(self) -> RebalanceResult:
        return RebalanceResult(
            rebalance_dates=[],
            states=[],
            trades=pd.DataFrame(
                columns=["datetime", "direction", "code", "shares", "price", "cost"]
            ),
            equity_curve=pd.DataFrame(columns=["datetime", "total", "cash", "position_value"]),
            performance={
                "total_return": 0.0,
                "annual_return": 0.0,
                "max_drawdown": 0.0,
                "sharpe": 0.0,
                "total_trades": 0,
            },
        )
