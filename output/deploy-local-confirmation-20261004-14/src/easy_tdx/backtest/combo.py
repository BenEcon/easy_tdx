"""多因子组合回测引擎。

核心能力：
- extract_factor_signals: 从策略提取买入/卖出信号遮罩
- combine_masks: 合并多个因子的信号（AND / OR / MAJORITY）
- CombinationRunner: 批量遍历因子组合，自动寻找最优搭配

用法::

    from easy_tdx.backtest.combo import CombinationRunner

    runner = CombinationRunner(
        strategy_classes=[MACDStrategy, RSIStrategy, BollingerStrategy],
        df=df,
        cash=100000.0,
    )

    # 遍历所有 2/3 因子组合
    results = runner.screen(combo_sizes=(2, 3), mode="MAJORITY")
    for r in results[:5]:
        print(f"{r.name}: 收益={r.result.performance['total_return']:.2%}")
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import BacktestResult

logger = logging.getLogger(__name__)

NDArray = np.ndarray
BoolArray = npt.NDArray[np.bool_]


def bool_array(x: Any) -> BoolArray:
    """Ensure the result is a BoolArray (not a scalar bool_)."""
    return np.asarray(x, dtype=np.bool_)


# ── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass
class FactorSignals:
    """单个因子的信号遮罩。

    Attributes:
        name: 因子名称（通常为策略类名）
        buy_mask: 每根 bar 是否产生买入信号
        sell_mask: 每根 bar 是否产生卖出信号
    """

    name: str
    buy_mask: BoolArray
    sell_mask: BoolArray


@dataclass
class ComboResult:
    """因子组合的回测结果。

    Attributes:
        name: 组合名称（如 "MACDStrategy + RSIStrategy"）
        indices: 因子在原始列表中的索引
        size: 因子数量
        result: 回测结果
    """

    name: str
    indices: tuple[int, ...]
    size: int
    result: BacktestResult


# ── 信号提取 ────────────────────────────────────────────────────────────────


def extract_factor_signals(
    strategy_cls: type[Strategy],
    df: pd.DataFrame,
    cash: float = 100_000.0,
    commission: float = 0.0003,
) -> FactorSignals:
    """从策略类提取买入/卖出信号遮罩。

    运行策略的 bar-by-bar 信号生成，捕获每根 bar 的买卖意图。
    复现 BacktestEngine._generate_signals 的仓位跟踪逻辑，
    确保信号与实际运行一致。

    Args:
        strategy_cls: Strategy 子类
        df: K线 DataFrame
        cash: 初始资金（影响全仓计算）
        commission: 佣金率

    Returns:
        FactorSignals 包含 buy_mask 和 sell_mask
    """
    strat = strategy_cls()
    strat._bind_data(df)
    strat._cash = cash
    strat._position_size = 0.0
    strat._call_init()

    n = len(df)
    buy_mask = np.zeros(n, dtype=bool)
    sell_mask = np.zeros(n, dtype=bool)

    close_arr = df["close"].to_numpy()

    for i in range(n):
        strat._set_bar_index(i)
        strat._call_next()
        signals = strat._clear_signals()

        for sig in signals:
            if sig.direction == "BUY":
                buy_mask[i] = True
            else:
                sell_mask[i] = True

        # 跟踪仓位状态（与 BacktestEngine._update_strategy_position 一致）
        _update_position(strat, signals, close_arr[i], commission)

    return FactorSignals(
        name=strategy_cls.__name__,
        buy_mask=buy_mask,
        sell_mask=sell_mask,
    )


def _update_position(
    strat: Strategy,
    signals: list[Any],
    est_price: float,
    commission: float,
) -> None:
    """更新策略内部仓位状态。

    复现 BacktestEngine._update_strategy_position 的逻辑，
    使因子信号提取与实际回测行为一致。

    Args:
        strat: 策略实例
        signals: 当前 bar 的信号列表
        est_price: 估算价格（收盘价）
        commission: 佣金率
    """
    for sig in signals:
        price = sig.price or est_price
        if sig.direction == "BUY":
            if sig.size == 0:
                shares = int(strat._cash / (price * (1 + commission)) / 100) * 100
                if shares > 0:
                    strat._position_size += shares
                    strat._cash -= shares * price
            else:
                strat._position_size += sig.size
                strat._cash -= sig.size * price
        elif sig.direction == "SELL":
            if sig.size == 0:
                strat._cash += strat._position_size * price
                strat._position_size = 0.0
            else:
                strat._cash += sig.size * price
                strat._position_size = max(0.0, strat._position_size - sig.size)


# ── 信号合并 ────────────────────────────────────────────────────────────────


def combine_masks(
    signals_list: list[FactorSignals],
    mode: str = "MAJORITY",
) -> tuple[BoolArray, BoolArray]:
    """合并多个因子的信号遮罩。

    Args:
        signals_list: 因子信号列表
        mode: 合并模式
            - "AND": 所有因子都同意才触发
            - "OR": 任一因子同意即触发
            - "MAJORITY": 过半因子同意才触发

    Returns:
        (combined_buy_mask, combined_sell_mask)

    Raises:
        ValueError: 不支持的合并模式
    """
    if not signals_list:
        raise ValueError("至少需要 1 个因子信号")

    buy_arrays = [s.buy_mask for s in signals_list]
    sell_arrays = [s.sell_mask for s in signals_list]

    buy_stack = np.stack(buy_arrays)  # shape: (n_factors, n_bars)
    sell_stack = np.stack(sell_arrays)

    if mode == "AND":
        return bool_array(np.all(buy_stack, axis=0)), bool_array(np.all(sell_stack, axis=0))
    elif mode == "OR":
        return bool_array(np.any(buy_stack, axis=0)), bool_array(np.any(sell_stack, axis=0))
    elif mode == "MAJORITY":
        n_factors = len(signals_list)
        # n_factors < 3 时 MAJORITY 退化为 AND/ANY（n=2 时 threshold=1.0，
        # 需 >1.0 即两个都要，等价于 AND）。提醒用户明确指定模式（审计 #17）。
        if n_factors < 3:
            logger.warning(
                "MAJORITY 模式在因子数 < 3 时（当前 %d）退化为 AND/ANY，"
                "建议明确指定 mode='AND' 或 'OR' 以避免语义混淆",
                n_factors,
            )
        threshold = n_factors / 2
        return (
            bool_array(np.sum(buy_stack, axis=0) > threshold),
            bool_array(np.sum(sell_stack, axis=0) > threshold),
        )
    else:
        raise ValueError(f"不支持的合并模式: {mode!r}（可选: AND, OR, MAJORITY）")


# ── 组合策略包装 ─────────────────────────────────────────────────────────────


class _ComboStrategy(Strategy):
    """将合并后的信号遮罩包装为 Strategy 子类。

    与 dsl_strategy 思路一致，但增加了仓位检查，
    避免重复买入和空仓卖出。
    """

    _buy_mask: BoolArray
    _sell_mask: BoolArray

    def init(self) -> None:
        pass

    def next(self) -> None:
        idx = self._bar_index
        buy = self._buy_mask
        sell = self._sell_mask

        if idx < len(buy) and buy[idx] and self.position["size"] == 0:
            self.buy(size=0)
        elif idx < len(sell) and sell[idx] and self.position["size"] > 0:
            self.sell(size=0)


def _make_combo_strategy(
    buy_mask: BoolArray,
    sell_mask: BoolArray,
) -> type[_ComboStrategy]:
    """将信号遮罩包装为 _ComboStrategy 子类。

    Args:
        buy_mask: 合并后的买入遮罩
        sell_mask: 合并后的卖出遮罩

    Returns:
        _ComboStrategy 子类
    """

    class WrappedComboStrategy(_ComboStrategy):
        _buy_mask = buy_mask
        _sell_mask = sell_mask

    return WrappedComboStrategy


# ── 组合回测运行器 ──────────────────────────────────────────────────────────


class CombinationRunner:
    """多因子组合回测运行器。

    用法::

        runner = CombinationRunner(
            strategy_classes=[MACDStrategy, RSIStrategy, BollingerStrategy],
            df=df,
            cash=100000.0,
        )

        # 遍历所有 2 因子组合
        results = runner.screen(combo_sizes=(2,), mode="MAJORITY")
    """

    def __init__(
        self,
        strategy_classes: list[type[Strategy]],
        df: pd.DataFrame,
        cash: float = 100_000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
        position_mode: str = "full",
        reject_policy: str = "reduce",
    ) -> None:
        """初始化运行器。

        Args:
            strategy_classes: 参与组合的策略类列表
            df: K线数据（所有策略共享）
            cash: 初始资金
            commission: 佣金率
            min_commission: 最低佣金
            stamp_tax: 印花税率
            slippage: 滑点
            execution: 成交价规则
            position_mode: 持仓模式
            reject_policy: 拒单策略
        """
        self._strategy_classes = strategy_classes
        self._df = df
        self._cash = cash
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._slippage = slippage
        self._execution = execution
        self._position_mode = position_mode
        self._reject_policy = reject_policy

        # 缓存：策略类 → FactorSignals（只提取一次）
        self._signal_cache: dict[str, FactorSignals] = {}

    def _get_factor_signals(self, idx: int) -> FactorSignals:
        """获取指定策略的因子信号（带缓存）。

        Args:
            idx: 策略在列表中的索引

        Returns:
            FactorSignals
        """
        cls = self._strategy_classes[idx]
        key = cls.__name__

        if key not in self._signal_cache:
            self._signal_cache[key] = extract_factor_signals(
                cls, self._df, cash=self._cash, commission=self._commission
            )

        return self._signal_cache[key]

    def _make_engine(self, strategy: type[Strategy]) -> BacktestEngine:
        """创建配置一致的回测引擎。

        Args:
            strategy: 策略类

        Returns:
            BacktestEngine 实例
        """
        return BacktestEngine(
            strategy=strategy,
            cash=self._cash,
            commission=self._commission,
            min_commission=self._min_commission,
            stamp_tax=self._stamp_tax,
            slippage=self._slippage,
            execution=self._execution,
            position_mode=self._position_mode,
            reject_policy=self._reject_policy,
        )

    def run_combination(
        self,
        indices: list[int] | tuple[int, ...],
        mode: str = "MAJORITY",
    ) -> BacktestResult:
        """运行指定因子组合的回测。

        Args:
            indices: 要组合的因子索引（在 strategy_classes 中的位置）
            mode: 信号合并模式（AND / OR / MAJORITY）

        Returns:
            BacktestResult
        """
        # 1. 提取因子信号
        signals = [self._get_factor_signals(i) for i in indices]

        # 2. 合并信号
        buy_mask, sell_mask = combine_masks(signals, mode=mode)

        # 3. 包装为策略并运行回测
        combo_cls = _make_combo_strategy(buy_mask, sell_mask)
        engine = self._make_engine(combo_cls)
        return engine.run(self._df)

    def screen(
        self,
        combo_sizes: tuple[int, ...] = (2, 3),
        mode: str = "MAJORITY",
        filter_zero_trades: bool = True,
        top_n: int = 0,
    ) -> list[ComboResult]:
        """遍历所有因子组合，批量回测并排名。

        Args:
            combo_sizes: 要尝试的组合大小（如 (2, 3) 表示 2 因子和 3 因子组合）
            mode: 信号合并模式（AND / OR / MAJORITY）
                注意：MAJORITY 模式下 2 因子需要两个都同意（等同 AND），
                因为阈值 = 2/2 = 1.0，需 > 1.0 才触发。
            filter_zero_trades: 是否过滤零交易组合
            top_n: 只返回前 N 名（0 = 全部返回）

        Returns:
            按 total_return 降序排列的 ComboResult 列表
        """
        n_factors = len(self._strategy_classes)
        results: list[ComboResult] = []

        for size in combo_sizes:
            if size > n_factors:
                continue

            for combo in itertools.combinations(range(n_factors), size):
                result = self.run_combination(combo, mode=mode)

                signals = [self._get_factor_signals(i) for i in combo]
                name = " + ".join(s.name for s in signals)

                results.append(
                    ComboResult(
                        name=name,
                        indices=combo,
                        size=size,
                        result=result,
                    )
                )

        # 过滤零交易
        if filter_zero_trades:
            results = [r for r in results if r.result.performance["total_trades"] > 0]

        # 按总收益率降序排列
        results.sort(key=lambda r: r.result.performance["total_return"], reverse=True)

        # 截取 top_n
        if top_n > 0:
            results = results[:top_n]

        return results
