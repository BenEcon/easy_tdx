"""回测绩效分析器。

计算资金曲线和交易记录的各项绩效指标。
"""

from __future__ import annotations

import datetime as _dt
from collections import deque
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
import pandas as pd

from easy_tdx.backtest.metric_state import CONTRACT, metric_states
from easy_tdx.backtest.performance_sampling import resolve_category, sample_equity

if TYPE_CHECKING:
    NDArray = npt.NDArray[np.float64]
else:
    NDArray = np.ndarray


class PerformanceAnalyzer:
    """绩效分析器。

    从资金曲线和交易记录计算收益、风险与交易绩效指标。

    Attributes:
        ANNUAL_DAYS: 年化交易日数（默认 252）
        RISK_FREE_RATE: 无风险利率（默认 3%）
    """

    ANNUAL_DAYS = 252
    RISK_FREE_RATE = 0.03

    def __init__(
        self,
        equity_curve: pd.DataFrame,
        trades: pd.DataFrame,
        risk_free_rate: float = 0.03,
        *,
        category: str | None = None,
        source: pd.DataFrame | None = None,
        sampling_curve: pd.DataFrame | None = None,
    ) -> None:
        """初始化分析器。

        Args:
            equity_curve: 资金曲线 DataFrame，必须包含 total 和 drawdown 列
            trades: 交易记录 DataFrame，必须包含 direction, pnl, rejected 列
            risk_free_rate: 无风险利率（默认 3%）
        """
        self._equity_curve = equity_curve
        self._trades = trades
        self._risk_free_rate = risk_free_rate
        self._source = source if source is not None else equity_curve
        self._sampling_curve = sampling_curve if sampling_curve is not None else equity_curve
        self._category, self._category_source = resolve_category(self._source, category)
        self.basis: dict[str, object] = {}
        # 数据异常诊断（资金曲线不足/恒定时填充），供上层透出给用户
        self.diagnostic: str | None = None

    def compute(self) -> dict[str, float]:
        """计算绩效指标。

        Returns:
            绩效指标字典（不可计算为 NaN，无穷比率为 inf；basis 保留原因）：
            - total_return: 总收益率
            - annual_return: 年化收益率
            - max_drawdown: 最大回撤
            - max_dd_duration: 最大回撤持续时间（bar 数）
            - sharpe: 夏普比率
            - sortino: 索提诺比率
            - calmar: 卡玛比率
            - total_trades: 总交易次数
            - win_trades: 盈利交易次数
            - lose_trades: 亏损交易次数
            - breakeven_trades: 持平交易次数（不计入亏损次数）
            - rejected_trades: 被拒绝的交易次数
            - win_rate: 胜率
            - profit_factor: 盈亏比
            - avg_win: 平均盈利
            - avg_loss: 平均亏损
            - max_win: 最大盈利
            - max_loss: 最大亏损
            - avg_holding_days: FIFO 配对、按成交数量加权的实际日历天数
            - volatility: 年化波动率
        """
        sampled, basis = sample_equity(
            self._sampling_curve,
            category=self._category,
            category_source=self._category_source,
            source=self._source,
        )
        basis["risk_free_rate"] = self._risk_free_rate
        basis["metric_contract"] = CONTRACT
        basis["sortino_definition"] = "negative_excess_return_population_std"
        self.basis = basis
        self.diagnostic = None
        reasons: dict[str, str] = {}
        missing = float("nan")
        total = self._equity_curve["total"].to_numpy(dtype=float)
        drawdown = self._equity_curve["drawdown"].to_numpy(dtype=float)
        curve_valid = len(total) >= 2 and np.isfinite(total).all() and total[0] > 0
        total_return = float(total[-1] / total[0] - 1) if curve_valid else missing
        if not curve_valid:
            self.diagnostic = "资金曲线不足 2 根、初始净值非正或含非有限净值；不可计算项不以零替代"
            reasons["total_return"] = self.diagnostic

        # Annualized metrics use the declared sampling contract, not chart bars.
        # Invalid sampling must not erase valid trades, total return or drawdown.
        available = basis["unavailable_reason"] is None and curve_valid
        periods = float(basis["annual_periods"])
        if available:
            daily_ret = np.diff(sampled) / sampled[:-1]
            with np.errstate(over="ignore", invalid="ignore"):
                annual_return = float(
                    np.expm1(np.log(sampled[-1] / sampled[0]) * periods / len(daily_ret))
                )
            if not np.isfinite(annual_return):
                annual_return = float("nan")
                basis["warnings"].append("年化外推超过数值范围，年化收益和卡玛指标不可用")
        else:
            daily_ret = np.array([0.0, 0.0])
            annual_return = float("nan")
            self.diagnostic = self.diagnostic or str(basis["unavailable_reason"])

        # 3. 最大回撤（从峰值的最大跌幅百分比，0~1 之间）
        drawdown_pct = self._equity_curve["drawdown_pct"].to_numpy()
        dd_valid = (
            curve_valid
            and np.isfinite(drawdown_pct).all()
            and (drawdown_pct >= 0).all()
            and np.isfinite(drawdown).all()
            and (drawdown >= 0).all()
        )
        max_drawdown = float(np.max(drawdown_pct)) if dd_valid else missing

        # 4. 最大回撤持续时间
        max_dd_duration = self._compute_max_dd_duration(total, drawdown) if dd_valid else missing
        if not dd_valid:
            reasons["max_drawdown"] = reasons["max_dd_duration"] = "净值或回撤序列不足／无效"

        # 5. 夏普比率
        rf_daily = self._risk_free_rate / periods
        excess_ret = daily_ret - rf_daily
        sharpe = (
            np.mean(excess_ret) / np.std(daily_ret) * np.sqrt(periods)
            if np.std(daily_ret) != 0
            else missing
        )
        if np.std(daily_ret) == 0:
            reasons["sharpe"] = "收益标准差为零，夏普比率不可估计"

        # 6. 索提诺比率（分母只用负收益标准差）
        neg_ret = excess_ret[excess_ret < 0]
        if len(neg_ret) > 0 and np.std(neg_ret) != 0:
            sortino = np.mean(excess_ret) / np.std(neg_ret) * np.sqrt(periods)
        elif len(neg_ret) == 0 and np.mean(excess_ret) > 0:
            sortino = float("inf")
            reasons["sortino"] = "无负超额收益且平均超额收益为正；保留原负收益标准差口径"
        else:
            sortino = missing
            reasons["sortino"] = "负超额收益标准差为零，索提诺比率不可估计"

        # 7. 卡玛比率
        if max_drawdown > 0:
            calmar = annual_return / max_drawdown
        elif max_drawdown == 0 and annual_return > 0:
            calmar = float("inf")
            reasons["calmar"] = "年化收益为正且最大回撤为零，比率为正无穷，不代表无风险"
        else:
            calmar = missing
            reasons["calmar"] = "年化收益或回撤不可用，或零收益与零回撤不能形成比率"

        # 交易统计
        sell_trades = self._trades[
            (self._trades["direction"] == "SELL") & (self._trades["rejected"] == False)  # noqa: E712
        ]
        pnl_valid = np.isfinite(sell_trades["pnl"].to_numpy(dtype=float)).all()
        win_trades_mask = sell_trades["pnl"] > 0
        lose_trades_mask = sell_trades["pnl"] < 0

        # 单笔收益率 = pnl / cost_basis。cost_basis 由 engine._compute_pnls 填入
        # （SELL 对应的移动加权平均成本 × 卖出数量）。无 cost_basis 列或为 0 时
        # 收益率记 NaN，在后续统计里被过滤。
        # 显式转 float64：trades 列可能是 int/object dtype，导致 np.isfinite 失败。
        if "cost_basis" in sell_trades.columns:
            pnl_arr = sell_trades["pnl"].to_numpy(dtype=np.float64)
            cost_arr = sell_trades["cost_basis"].to_numpy(dtype=np.float64)
            with np.errstate(divide="ignore", invalid="ignore"):
                trade_returns = np.where(
                    (cost_arr > 0) & np.isfinite(cost_arr), pnl_arr / cost_arr, np.nan
                )
        else:
            trade_returns = np.full(len(sell_trades), np.nan)

        # 8. 总交易次数
        total_trades = len(sell_trades)

        # 9. 盈利交易次数
        win_count = float(np.sum(win_trades_mask)) if pnl_valid else missing

        # 10. 亏损交易次数
        lose_count = float(np.sum(lose_trades_mask)) if pnl_valid else missing
        breakeven_count = float(np.sum(sell_trades["pnl"] == 0)) if pnl_valid else missing

        # 11. 被拒绝的交易次数
        rejected_trades = self._trades["rejected"].sum()

        # 12. 胜率
        win_rate = win_count / total_trades if total_trades else missing

        # 13. 盈亏比
        win_pnl = sell_trades.loc[win_trades_mask, "pnl"]
        lose_pnl = sell_trades.loc[lose_trades_mask, "pnl"]

        if not pnl_valid:
            profit_factor = missing
        elif len(lose_pnl) > 0:
            profit_factor = win_pnl.sum() / abs(lose_pnl.sum())
        elif len(win_pnl) > 0:
            profit_factor = float("inf")
            reasons["profit_factor"] = "已实现总盈利为正且总亏损为零；不使用 999 哨兵值"
        else:
            profit_factor = missing
            reasons["profit_factor"] = "没有已实现盈亏，不能计算利润因子"
        if not total_trades:
            reasons["win_rate"] = "没有已成交的卖出记录，胜率不可计算"
        if not pnl_valid:
            for key in (
                "win_trades",
                "lose_trades",
                "breakeven_trades",
                "win_rate",
                "profit_factor",
            ):
                reasons[key] = "已成交卖出记录含非有限盈亏，不删除异常记录后计算"

        # 14. 平均盈利（单笔收益率口径）
        win_returns = trade_returns[win_trades_mask.to_numpy()]
        win_valid = pnl_valid and len(win_returns) > 0 and np.isfinite(win_returns).all()
        avg_win = float(np.mean(win_returns)) if win_valid else missing

        # 15. 平均亏损（单笔收益率口径）
        lose_returns = trade_returns[lose_trades_mask.to_numpy()]
        lose_valid = pnl_valid and len(lose_returns) > 0 and np.isfinite(lose_returns).all()
        avg_loss = float(np.mean(lose_returns)) if lose_valid else missing

        # 16. 最大盈利（单笔收益率口径）
        max_win = float(np.max(win_returns)) if win_valid else missing

        # 17. 最大亏损（单笔收益率口径）
        max_loss = float(np.min(lose_returns)) if lose_valid else missing
        for key in ("avg_win", "max_win"):
            if not win_valid:
                reasons[key] = "无盈利卖出，或其盈亏／成本基数不完整"
        for key in ("avg_loss", "max_loss"):
            if not lose_valid:
                reasons[key] = "无亏损卖出，或其盈亏／成本基数不完整"

        # 18. 平均持仓天数（FIFO 配对计算）
        avg_holding_days = self._compute_avg_holding_days()
        if not np.isfinite(avg_holding_days):
            reasons["avg_holding_days"] = "无完整 FIFO 平仓配对，或成交时间／数量不完整"

        # 19. 年化波动率
        volatility = np.std(daily_ret) * np.sqrt(periods)
        if not available:
            sharpe = sortino = calmar = volatility = float("nan")
            for key in ("annual_return", "sharpe", "sortino", "calmar", "volatility"):
                reasons[key] = self.diagnostic or "收盘采样不可用"
        elif not np.isfinite(annual_return):
            calmar = float("nan")

        metrics = {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "max_dd_duration": max_dd_duration,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "total_trades": total_trades,
            "win_trades": win_count,
            "lose_trades": lose_count,
            "breakeven_trades": breakeven_count,
            "rejected_trades": rejected_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_win": max_win,
            "max_loss": max_loss,
            "avg_holding_days": avg_holding_days,
            "volatility": volatility,
            # 别名键（兼容常见叫法，避免 .get('sharpe_ratio') 等误用返回 0）
            "sharpe_ratio": sharpe,
            "start_cash": float(total[0]) if len(total) else missing,
            "end_value": float(total[-1]) if len(total) else missing,
        }
        if "sharpe" in reasons:
            reasons["sharpe_ratio"] = reasons["sharpe"]
        basis["metric_status"] = metric_states(metrics, reasons)
        return metrics

    def _compute_avg_holding_days(self) -> float:
        """计算平均持仓天数（FIFO 配对）。

        遍历非 rejected 的交易记录，使用 FIFO 队列配对买入和卖出，
        按 size 加权计算平均持仓天数。

        注意：持仓天数按真实日历日计算（解析 ``YYYYMMDD`` 为 ``date`` 后相减），
        而非 YYYYMMDD 整数差——后者在跨月时会放大（如 20240201-20240131=70）。

        Returns:
            加权平均持仓天数；无完整配对或成交信息不完整时返回 NaN。
        """
        if not {"datetime", "size"}.issubset(self._trades.columns):
            return float("nan")

        # 只处理非 rejected 的交易
        valid = self._trades[~self._trades["rejected"]]
        if len(valid) == 0:
            return float("nan")

        queues: dict[str, deque[tuple[_dt.datetime, float]]] = {}
        total_days = 0.0
        total_size = 0.0

        def to_date(raw_dt: object) -> _dt.datetime | None:
            """把 datetime 列的值（int YYYYMMDD 或 pd.Timestamp）转为 date。

            无法解析时返回 None（该行将被跳过，不参与配对）。
            """
            if isinstance(raw_dt, pd.Timestamp):
                if pd.isna(raw_dt):
                    return None
                parsed: _dt.datetime = raw_dt.to_pydatetime(warn=False)
                return parsed
            try:
                # raw_dt 可能是 int/object dtype 标量；统一经 str 转 int
                n = int(str(raw_dt))
            except (TypeError, ValueError):
                return None
            # YYYYMMDD 整数 → 真实日期
            try:
                return _dt.datetime.strptime(str(n), "%Y%m%d")
            except ValueError:
                return None

        for _, row in valid.iterrows():
            d = to_date(row["datetime"])
            if d is None:
                return float("nan")
            direction = row["direction"]
            buy_queue = queues.setdefault(str(row.get("performance_slot", "single")), deque())
            size = float(row["size"])
            if not np.isfinite(size) or size <= 0:
                return float("nan")

            if direction == "BUY":
                buy_queue.append((d, size))
            elif direction == "SELL":
                remaining = size
                while remaining > 0 and buy_queue:
                    buy_d, buy_size = buy_queue[0]
                    # 消费该笔 BUY 的部分或全部
                    consumed = min(remaining, buy_size)
                    try:
                        holding_days = (d - buy_d).total_seconds() / 86400
                    except TypeError:
                        return float("nan")
                    if holding_days < 0:
                        return float("nan")
                    total_days += holding_days * consumed
                    total_size += consumed
                    remaining -= consumed
                    buy_size -= consumed
                    if buy_size <= 0:
                        buy_queue.popleft()
                    else:
                        buy_queue[0] = (buy_d, buy_size)
                if remaining > 0:
                    return float("nan")

        if total_size == 0:
            return float("nan")
        return total_days / total_size

    def _compute_max_dd_duration(self, total: NDArray, drawdown: NDArray) -> int:
        """计算最大回撤持续时间。

        找到最大回撤点，然后计算从回撤前的高点到该点的 bar 数。

        Args:
            total: 总权益数组
            drawdown: 回撤数组

        Returns:
            最大回撤持续时间（bar 数）
        """
        if len(drawdown) == 0:
            return 0

        max_dd_idx: int = int(np.argmax(drawdown))
        max_dd_value = drawdown[max_dd_idx]

        # 如果没有回撤，返回 0
        if max_dd_value == 0:
            return 0

        # 找到回撤前的高点
        peak_idx: int = max_dd_idx
        peak_value = np.max(total[: max_dd_idx + 1])
        for i in range(max_dd_idx - 1, -1, -1):
            if total[i] == peak_value:
                peak_idx = i
                break

        return int(max_dd_idx - peak_idx)
