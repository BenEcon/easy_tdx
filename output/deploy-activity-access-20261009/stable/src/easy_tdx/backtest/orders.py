"""订单撮合模拟器。

将策略信号转换为成交记录，支持多种执行模式、仓位管理和拒绝策略。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from easy_tdx.backtest.bar_time import BarTimeIndex, SignalTime
from easy_tdx.backtest.phase_checkpoint import PhaseCheckpoint, restore_order_state
from easy_tdx.backtest.types import Signal, Trade
from easy_tdx.checkpoints import calculation_journal
from easy_tdx.computation import computation_checkpoint

if TYPE_CHECKING:
    from easy_tdx.backtest.slippage import SlippageModel


@dataclass
class OrderSimulator:
    """订单撮合模拟器。

    将策略信号（Signal）转换为成交记录（Trade），支持多种执行模式、
    仓位管理和拒绝策略。

    Attributes:
        df: K线数据 DataFrame
        execution: 成交价规则 (next_open/next_close)
        position_mode: 仓位模式 (full/fixed/percent)
        reject_policy: 拒绝策略 (reduce/skip)
        commission: 佣金费率
        min_commission: 最低佣金
        stamp_tax: 印花税率（仅卖出）
        slippage: 滑点（每股）
    """

    df: pd.DataFrame
    execution: str = "next_open"
    position_mode: str = "full"
    reject_policy: str = "reduce"
    commission: float = 0.0003
    min_commission: float = 5.0
    stamp_tax: float = 0.001
    slippage: float = 0.0
    slippage_model: SlippageModel | None = None

    def simulate(
        self,
        signals: list[Signal],
        cash: float,
        position: float,
        position_mode: str | None = None,
        *,
        checkpoint_key: str | None = None,
    ) -> list[Trade]:
        """模拟订单撮合过程。

        Args:
            signals: 交易信号列表
            cash: 初始现金
            position: 初始持仓（股数）
            position_mode: 仓位模式（覆盖初始化参数）

        Returns:
            成交记录列表
        """
        if position_mode is None:
            position_mode = self.position_mode

        trades: list[Trade] = []
        current_cash = cash
        current_position = position
        start = 0
        processed: list[dict[str, Any] | None] = []
        checkpoint = None
        journal = calculation_journal() if checkpoint_key is not None else None
        # A user supplied slippage model/subclass may carry hidden mutable state.
        # Preserve its ordinary execution, never silently assume it is stateless.
        if (
            journal is not None
            and checkpoint_key is not None
            and self.slippage_model is None
            and type(self) is OrderSimulator
        ):
            inputs = [asdict(item) for item in signals]
            checkpoint = PhaseCheckpoint(
                journal,
                checkpoint_key,
                "backtest-order-signals-v1",
                self.df,
                inputs,
                {
                    "cash": cash,
                    "position": position,
                    "position_mode": position_mode,
                    "execution": self.execution,
                    "reject_policy": self.reject_policy,
                    "commission": self.commission,
                    "min_commission": self.min_commission,
                    "stamp_tax": self.stamp_tax,
                    "slippage": self.slippage,
                },
                len(signals),
            )
            start, saved = checkpoint.restore()
            if saved is not None:
                current_cash, current_position, trades, processed = restore_order_state(
                    saved, start, inputs, self.df, cash, position
                )
                checkpoint.used(start)

        # Per-run only: callers may replace/reorder df between simulations, and
        # user models/subclasses may mutate it while matching. Never cache those.
        bar_positions = None
        if (
            start < len(signals)
            and type(self) is OrderSimulator
            and self.slippage_model is None
            and all(
                isinstance(item.datetime, int | np.integer | pd.Timestamp)
                for item in signals[start:]
            )
        ):
            bar_positions = self._build_bar_positions()
        for index in range(start, len(signals)):
            computation_checkpoint()
            signal = signals[index]
            if bar_positions is None:
                trade = self._simulate_signal(signal, current_cash, current_position, position_mode)
            else:
                trade = self._simulate_signal(
                    signal,
                    current_cash,
                    current_position,
                    position_mode,
                    bar_positions=bar_positions,
                )
            if trade is not None:
                trades.append(trade)
                if not trade.rejected:
                    if signal.direction == "BUY":
                        current_cash -= trade.size * trade.price + trade.commission + trade.slippage
                        current_position += trade.size
                    elif signal.direction == "SELL":
                        current_cash += trade.size * trade.price - trade.commission - trade.slippage
                        current_position -= trade.size
            if checkpoint is not None:
                processed.append(asdict(trade) if trade is not None else None)
                if (index + 1) % 64 == 0 or index + 1 == len(signals):
                    checkpoint.save(
                        index + 1,
                        {
                            "cash": current_cash,
                            "position": current_position,
                            "processed": processed,
                        },
                    )

        return trades

    def _simulate_signal(
        self,
        signal: Signal,
        cash: float,
        position: float,
        position_mode: str,
        *,
        bar_positions: BarTimeIndex | None = None,
    ) -> Trade | None:
        """Existing matching semantics for one signal, including no-fill paths."""
        bar_idx = (
            self._find_bar_index(signal.datetime)
            if bar_positions is None
            else bar_positions.get(signal.datetime)
        )
        if bar_idx is None:
            return None
        if signal.source == "stop":
            exec_idx_raw = self._resolve_exec_index(bar_idx)
            # Preserve the existing last-bar fallback and adverse-gap price.
            next_price: float
            if exec_idx_raw is None or exec_idx_raw >= len(self.df):
                exec_idx = bar_idx
                row = self.df.iloc[bar_idx] if bar_idx < len(self.df) else None
                if row is None:
                    return None
                next_price = float(row["close"])
            else:
                exec_idx = exec_idx_raw
                price_raw = self._get_price(exec_idx, signal.direction)
                if price_raw is None:
                    return None
                next_price = price_raw
            trigger = signal.price if signal.price is not None else next_price
            if signal.direction == "SELL":
                price: float = min(next_price, trigger)
            else:
                price = max(next_price, trigger)
        elif signal.price is not None:
            exec_idx = bar_idx
            price = signal.price
        else:
            exec_idx_raw = self._resolve_exec_index(bar_idx)
            if exec_idx_raw is None or exec_idx_raw >= len(self.df):
                return None
            exec_idx = exec_idx_raw
            price_raw = self._get_price(exec_idx, signal.direction)
            if price_raw is None:
                return None
            price = price_raw
        if signal.direction == "BUY":
            return self._execute_buy(
                signal=signal,
                bar_idx=bar_idx,
                exec_idx=exec_idx,
                price=price,
                cash=cash,
                position=position,
                position_mode=position_mode,
            )
        if signal.direction == "SELL":
            return self._execute_sell(
                signal=signal,
                bar_idx=bar_idx,
                exec_idx=exec_idx,
                price=price,
                cash=cash,
                position=position,
                position_mode=position_mode,
            )
        return None

    def _build_bar_positions(self) -> BarTimeIndex | None:
        """Index only known integer/date columns, retaining first *positions*.

        Full timestamp identity is retained; ambiguous date-only queries fail.
        Object/float/missing inputs keep their direct comparison behavior.
        The map belongs to one simulate() call, not the simulator or a checkpoint.
        """
        dt_col = self.df["datetime"]
        if dt_col.isna().any():
            return None
        if not (
            pd.api.types.is_datetime64_any_dtype(dt_col) or pd.api.types.is_integer_dtype(dt_col)
        ):
            return None
        return BarTimeIndex(dt_col)

    def _find_bar_index(self, datetime_val: SignalTime) -> int | None:
        """查找 datetime 对应的 K 线索引。

        Args:
            datetime_val: 日线整数日期或完整时间戳。

        Returns:
            K 线索引，未找到返回 None
        """
        positions = self._build_bar_positions()
        if positions is not None:
            return positions.get(datetime_val)
        # Unsupported/missing legacy columns retain their direct comparison path.
        dt_col = self.df["datetime"]

        # 尝试直接比较（如果是 int 类型）
        # 注意：用 to_numpy().argmax() 取位置索引，而非 idxmax()（返回 label），
        # 因为后续 self.df.iloc[...] 按位置取行；若 df.index 非默认 RangeIndex，
        # label != position 会导致撮合取错 bar。
        try:
            mask = (dt_col == datetime_val).to_numpy()
            if mask.any():
                return int(mask.argmax())
        except (TypeError, ValueError):
            pass

        # 如果是 datetime 对象，转为 int 比较
        if pd.api.types.is_datetime64_any_dtype(dt_col):
            dt_ints = dt_col.dt.strftime("%Y%m%d").astype(int)
            mask_arr = (dt_ints == datetime_val).to_numpy()
            if mask_arr.any():
                return int(mask_arr.argmax())
            return None

        return None

    def _resolve_exec_index(self, bar_idx: int) -> int | None:
        """根据执行模式确定成交的 K 线索引。

        开盘价 / 收盘价模式均在信号后一根 K 线成交（next_open 取次根开盘价，
        next_close 取次根收盘价），避免使用信号当根的未完成/未来数据。

        Args:
            bar_idx: 信号对应的 K 线索引

        Returns:
            成交 K 线索引
        """
        return bar_idx + 1

    def _get_price(self, exec_idx: int, direction: str) -> float | None:
        """根据执行模式获取成交价。

        Args:
            exec_idx: 成交 K 线索引
            direction: 交易方向（仅作保留，当前两种模式均不依赖方向）

        Returns:
            成交价格
        """
        if exec_idx >= len(self.df):
            return None

        row = self.df.iloc[exec_idx]

        if self.execution == "next_open":
            return float(row["open"])
        elif self.execution == "next_close":
            return float(row["close"])
        else:
            return None

    def _calculate_buy_size(
        self,
        signal_size: float,
        price: float,
        cash: float,
        position_mode: str,
    ) -> float:
        """计算买入数量。

        Args:
            signal_size: 信号指定的数量
            price: 成交价格
            cash: 可用现金
            position_mode: 仓位模式

        Returns:
            买入数量（股）
        """
        if position_mode == "full" or signal_size == 0:
            # 全仓：计算可用现金能买多少（100股整手）
            # 先计算最大股数，然后向下取整到100的倍数
            max_cost_per_share = price * (1 + self.commission) + self.slippage
            max_shares_raw = cash / max_cost_per_share
            max_shares = int(max_shares_raw / 100) * 100
            return float(max_shares)
        elif position_mode == "fixed":
            # 固定股数
            return signal_size
        elif position_mode == "percent":
            # 总资产的百分比
            total_value = cash  # 简化：假设现金=总资产
            target_value = total_value * signal_size
            max_shares = int(target_value / price / 100) * 100
            return float(max_shares)
        else:
            return signal_size

    def _calculate_sell_size(
        self,
        signal_size: float,
        position: float,
        position_mode: str,
    ) -> float:
        """计算卖出数量。

        Args:
            signal_size: 信号指定的数量
            position: 当前持仓
            position_mode: 仓位模式

        Returns:
            卖出数量（股）
        """
        if position_mode == "full" or signal_size == 0:
            # 全部卖出
            return position
        elif position_mode == "fixed":
            # 固定股数
            return signal_size
        elif position_mode == "percent":
            # 持仓的百分比
            return position * signal_size
        else:
            return signal_size

    def _calculate_commission(self, size: float, price: float, is_sell: bool = False) -> float:
        """计算手续费。

        Args:
            size: 成交数量
            price: 成交价格
            is_sell: 是否为卖出

        Returns:
            手续费总额
        """
        # 佣金
        commission = max(size * price * self.commission, self.min_commission)

        # 印花税（仅卖出）
        if is_sell:
            stamp = size * price * self.stamp_tax
            commission += stamp

        return commission

    def _compute_slippage(self, size: float, price: float, is_sell: bool) -> float:
        """计算滑点成本。"""
        if self.slippage_model is not None:
            volume = self._get_current_volume()
            volatility = self._estimate_volatility()
            return self.slippage_model.compute(
                price=price,
                size=size,
                volume=volume,
                volatility=volatility,
                direction="SELL" if is_sell else "BUY",
            )
        return size * self.slippage

    def _get_current_volume(self) -> float:
        """获取最后一根K线的成交量，兼容 vol/volume 列名。"""
        if len(self.df) == 0:
            return 0.0
        for col in ("vol", "volume"):
            if col in self.df.columns:
                return float(self.df[col].iloc[-1])
        return 0.0

    def _estimate_volatility(self) -> float:
        """从收盘价估计年化波动率。"""
        if "close" not in self.df.columns or len(self.df) < 2:
            return 0.0
        close = self.df["close"].to_numpy()
        returns = np.diff(close) / close[:-1]
        if len(returns) < 2:
            return 0.0
        daily_vol = float(np.std(returns))
        return float(daily_vol * np.sqrt(252))

    def _execute_buy(
        self,
        signal: Signal,
        bar_idx: int,
        exec_idx: int,
        price: float,
        cash: float,
        position: float,
        position_mode: str,
    ) -> Trade | None:
        """执行买入。

        Args:
            signal: 交易信号
            bar_idx: 信号 K 线索引
            exec_idx: 成交 K 线索引
            price: 成交价格
            cash: 可用现金
            position: 当前持仓
            position_mode: 仓位模式

        Returns:
            成交记录
        """
        # 保存原始信号数量
        original_size = signal.size

        # 计算买入数量
        size = self._calculate_buy_size(signal.size, price, cash, position_mode)

        if size <= 0:
            # 资金不足或计算结果为0
            if self.reject_policy == "skip":
                # 对于 percent 模式，original_size 是百分比（如 0.5），不是股数
                # 对于 fixed/full 模式，original_size 就是股数
                display_size = original_size if position_mode == "fixed" else 100
                return Trade(
                    datetime=self.df.iloc[exec_idx]["datetime"],
                    direction="BUY",
                    size=display_size,
                    price=price,
                    commission=0.0,
                    slippage=0.0,
                    pnl=0.0,
                    rejected=True,
                )
            return None

        # 计算费用
        commission = self._calculate_commission(size, price, is_sell=False)
        slippage = self._compute_slippage(size, price, is_sell=False)

        # 检查资金是否足够
        total_cost = size * price + commission + slippage
        if total_cost > cash:
            if self.reject_policy == "skip":
                return Trade(
                    datetime=self.df.iloc[exec_idx]["datetime"],
                    direction="BUY",
                    size=original_size,
                    price=price,
                    commission=commission,
                    slippage=slippage,
                    pnl=0.0,
                    rejected=True,
                )
            elif self.reject_policy == "reduce":
                # reduce 模式：重新计算可买数量
                available_cash = cash - self.min_commission - slippage
                if available_cash > price:
                    reduced_size = int(available_cash / price / 100) * 100
                    if reduced_size > 0:
                        commission = self._calculate_commission(reduced_size, price, is_sell=False)
                        slippage = self._compute_slippage(reduced_size, price, is_sell=False)
                        return Trade(
                            datetime=self.df.iloc[exec_idx]["datetime"],
                            direction="BUY",
                            size=reduced_size,
                            price=price,
                            commission=commission,
                            slippage=slippage,
                            pnl=0.0,
                            rejected=False,
                        )
                # 无法买任何数量
                return None

        return Trade(
            datetime=self.df.iloc[exec_idx]["datetime"],
            direction="BUY",
            size=size,
            price=price,
            commission=commission,
            slippage=slippage,
            pnl=0.0,
            rejected=False,
        )

    def _execute_sell(
        self,
        signal: Signal,
        bar_idx: int,
        exec_idx: int,
        price: float,
        cash: float,
        position: float,
        position_mode: str,
    ) -> Trade | None:
        """执行卖出。

        Args:
            signal: 交易信号
            bar_idx: 信号 K 线索引
            exec_idx: 成交 K 线索引
            price: 成交价格
            cash: 可用现金
            position: 当前持仓
            position_mode: 仓位模式

        Returns:
            成交记录
        """
        # 计算卖出数量
        size = self._calculate_sell_size(signal.size, position, position_mode)

        if size <= 0:
            # 无持仓
            if self.reject_policy == "skip":
                return Trade(
                    datetime=self.df.iloc[exec_idx]["datetime"],
                    direction="SELL",
                    size=0,
                    price=price,
                    commission=0.0,
                    slippage=0.0,
                    pnl=0.0,
                    rejected=True,
                )
            return None

        # 检查持仓是否足够
        if size > position:
            if self.reject_policy == "skip":
                return Trade(
                    datetime=self.df.iloc[exec_idx]["datetime"],
                    direction="SELL",
                    size=size,
                    price=price,
                    commission=0.0,
                    slippage=0.0,
                    pnl=0.0,
                    rejected=True,
                )
            # reduce 模式：减少到实际持仓
            size = position

        # 计算费用
        commission = self._calculate_commission(size, price, is_sell=True)
        slippage = self._compute_slippage(size, price, is_sell=True)

        return Trade(
            datetime=self.df.iloc[exec_idx]["datetime"],
            direction="SELL",
            size=size,
            price=price,
            commission=commission,
            slippage=slippage,
            pnl=0.0,
            rejected=False,
        )
