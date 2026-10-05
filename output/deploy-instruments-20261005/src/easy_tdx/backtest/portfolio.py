"""回测引擎持仓追踪器。

负责应用交易记录、计算资金曲线和持仓快照。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.backtest.types import Trade


class PortfolioTracker:
    """持仓追踪器。

    预分配 numpy 数组存储每个 bar 的状态，遍历应用交易。

    Attributes:
        _close: 收盘价数组
        _datetime: 时间戳数组
        _n: bar 数量
        _cash: 每个 bar 的现金
        _position: 每个 bar 的持仓数量
        _avg_price: 每个 bar 的平均成本价
    """

    def __init__(self, df: pd.DataFrame, initial_cash: float = 100000) -> None:
        """初始化追踪器。

        Args:
            df: 必须包含 close 和 datetime 列的 DataFrame
            initial_cash: 初始现金
        """
        self._close = df["close"].to_numpy(dtype=float)
        self._datetime = df["datetime"].to_numpy()
        self._n = len(df)
        self._cash = np.full(self._n, initial_cash)
        self._position = np.zeros(self._n)
        self._avg_price = np.zeros(self._n)
        self._initial_cash = initial_cash
        # 预构建 datetime → 位置索引 映射，供 apply_trades 按"位置"匹配交易。
        # 关键：trade.datetime 与 df["datetime"] 的具体类型（Timestamp / int /
        # datetime64）必须一致才能作 dict key 命中；过去直接用原始值匹配，
        # 一旦两端类型不一致（如 datetime 列被预处理成 int、混合数据源、或
        # pandas 版本哈希差异）就静默漏掉全部交易 → 净值恒定（issue #30）。
        # 这里把匹配收敛到归一化后的位置索引，与类型无关。
        self._datetime_to_pos = self._build_datetime_index(df["datetime"])

    @staticmethod
    def _build_datetime_index(dt_col: pd.Series) -> dict[object, int]:
        """构建 datetime 值 → 位置索引 的映射。

        对 datetime 列做归一化（datetime64 → int YYYYMMDD，与 OrderSimulator
        的 _find_bar_index 同款逻辑），保证无论上游 datetime 是哪种类型，
        查询键都能命中同一张表。

        Args:
            dt_col: DataFrame 的 datetime 列

        Returns:
            {归一化后的 datetime 值: 位置索引}，重复值取首次出现位置。
        """
        if pd.api.types.is_datetime64_any_dtype(dt_col):
            keys = dt_col.dt.strftime("%Y%m%d").astype("int64").to_numpy()
        else:
            keys = dt_col.to_numpy()
        mapping: dict[object, int] = {}
        for i, k in enumerate(keys):
            if k not in mapping:
                mapping[k] = i
        return mapping

    def _find_pos(self, trade_dt: object) -> int | None:
        """把 trade.datetime 归一化后查 df 中的位置索引。

        与 _build_datetime_index 使用同一套归一化规则，保证类型无关命中。

        Args:
            trade_dt: 交易时间（int YYYYMMDD / Timestamp / datetime64）

        Returns:
            df 中的位置索引，未命中返回 None
        """
        # datetime-like（Timestamp / datetime64）→ int YYYYMMDD 再查
        if hasattr(trade_dt, "strftime"):
            try:
                key: object = int(trade_dt.strftime("%Y%m%d"))
            except (ValueError, AttributeError):
                return None
        else:
            key = trade_dt
        return self._datetime_to_pos.get(key)

    def apply_trades(self, trades: list[Trade]) -> None:
        """应用交易记录，更新内部状态数组。

        Args:
            trades: 交易列表
        """
        # 构建 位置索引 → [Trade] 映射（支持同 bar 多笔交易）。
        # 用位置索引而非原始 datetime 值作 key，与 trade.datetime 的具体类型
        # 无关，杜绝 int vs datetime64 类型不一致导致的静默漏单（issue #30）。
        trade_map: dict[int, list[Trade]] = {}
        for trade in trades:
            if trade.rejected:
                continue
            pos = self._find_pos(trade.datetime)
            if pos is None:
                continue
            trade_map.setdefault(pos, []).append(trade)

        # 遍历每个 bar
        for i in range(self._n):
            # 继承前一个 bar 的状态（除了第一个 bar）
            if i > 0:
                self._cash[i] = self._cash[i - 1]
                self._position[i] = self._position[i - 1]
                self._avg_price[i] = self._avg_price[i - 1]

            # 处理该 bar 的所有交易
            for trade in trade_map.get(i, []):
                if trade.direction == "BUY":
                    cost = trade.size * trade.price + trade.commission + trade.slippage
                    self._cash[i] -= cost

                    # 更新均价
                    if self._position[i] > 0:
                        prev_cost = self._position[i] * self._avg_price[i]
                        total_cost = prev_cost + trade.size * trade.price
                        self._position[i] += trade.size
                        self._avg_price[i] = total_cost / self._position[i]
                    else:
                        # 新开仓或从空仓开仓
                        self._position[i] = trade.size
                        self._avg_price[i] = trade.price

                elif trade.direction == "SELL":
                    proceeds = trade.size * trade.price - trade.commission - trade.slippage
                    self._cash[i] += proceeds
                    self._position[i] -= trade.size

                    # 清空持仓时归零
                    if self._position[i] <= 0:
                        self._position[i] = 0.0
                        self._avg_price[i] = 0.0

    @property
    def equity_curve(self) -> pd.DataFrame:
        """计算资金曲线。

        Returns:
            DataFrame 包含 datetime, cash, position_value, total, drawdown, drawdown_pct
        """
        position_value = self._position * self._close
        total = self._cash + position_value
        peak = np.maximum.accumulate(total)
        drawdown = peak - total
        drawdown_pct = np.divide(
            drawdown,
            peak,
            out=np.zeros_like(drawdown),
            where=(peak != 0),
        )

        return pd.DataFrame(
            {
                "datetime": self._datetime,
                "cash": self._cash,
                "position_value": position_value,
                "total": total,
                "drawdown": drawdown,
                "drawdown_pct": drawdown_pct,
            }
        )

    @property
    def positions(self) -> pd.DataFrame:
        """计算持仓快照。

        Returns:
            DataFrame 包含 datetime, size, avg_price, market_value, unrealized_pnl
        """
        market_value = self._position * self._close
        unrealized_pnl = (self._close - self._avg_price) * self._position

        return pd.DataFrame(
            {
                "datetime": self._datetime,
                "size": self._position,
                "avg_price": self._avg_price,
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
            }
        )

    @property
    def initial_cash(self) -> float:
        """初始现金。"""
        return self._initial_cash
