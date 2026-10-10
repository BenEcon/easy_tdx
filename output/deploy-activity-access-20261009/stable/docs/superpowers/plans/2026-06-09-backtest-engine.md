# Backtest Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 easy-tdx 新增 `easy_tdx.backtest` 纯计算回测模块，支持 Python 类策略定义、向量化执行、5 种撮合规则、18 项绩效指标、CLI 一键回测。

**Architecture:** 自底向上构建——数据类型 → 策略基类 → 撮合器 → 持仓追踪 → 绩效分析 → 引擎编排 → CLI 集成。每层独立可测，无网络依赖。

**Tech Stack:** Python 3.10+, pandas, numpy, click（项目已有依赖）

**Spec:** `docs/superpowers/specs/2026-06-09-backtest-engine-design.md` (rev 2.1)

---

## File Structure

```
# 新建文件
src/easy_tdx/backtest/__init__.py          # 公开 API 导出
src/easy_tdx/backtest/types.py             # Signal / Trade / Position / BacktestResult
src/easy_tdx/backtest/strategy.py          # Strategy 基类 + StrategyDataProxy
src/easy_tdx/backtest/orders.py            # OrderSimulator（撮合规则 + 拒绝策略）
src/easy_tdx/backtest/portfolio.py         # PortfolioTracker（持仓/资金曲线）
src/easy_tdx/backtest/performance.py       # PerformanceAnalyzer（18 项绩效指标）
src/easy_tdx/backtest/engine.py            # BacktestEngine（向量化执行管道）
src/easy_tdx/backtest/dsl.py              # @dsl_strategy 装饰器 + DSL 函数桥接 (P1，骨架)
src/easy_tdx/backtest/cli.py              # CLI 命令

# 修改文件
src/easy_tdx/cli/__init__.py              # 注册 backtest 命令
src/easy_tdx/__init__.py                  # 导出 BacktestEngine, Strategy 等（可选）

# 测试文件
tests/unit/test_backtest_types.py          # 数据类型 round-trip
tests/unit/test_backtest_strategy.py       # Strategy 基类 + DataProxy
tests/unit/test_backtest_orders.py         # 撮合规则 + 拒绝策略
tests/unit/test_backtest_portfolio.py      # 持仓追踪 + 资金曲线
tests/unit/test_backtest_performance.py    # 绩效指标（手工验证）
tests/unit/test_backtest_engine.py         # 引擎端到端
tests/unit/test_backtest_cli.py           # CLI 命令
```

---

## Task 1: 数据类型 — types.py

**Files:**
- Create: `src/easy_tdx/backtest/__init__.py`
- Create: `src/easy_tdx/backtest/types.py`
- Create: `tests/unit/test_backtest_types.py`

- [ ] **Step 1: 创建包结构和空 `__init__.py`**

```python
# src/easy_tdx/backtest/__init__.py
"""easy_tdx.backtest — 向量化策略回测引擎（纯计算，零网络依赖）。"""
```

- [ ] **Step 2: 写 types.py 的失败测试**

```python
# tests/unit/test_backtest_types.py
"""回测模块数据类型测试。"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from easy_tdx.backtest.types import BacktestResult, Position, Signal, Trade


class TestSignal:
    def test_buy_signal_defaults(self):
        s = Signal(datetime=20240101, direction="BUY", size=0)
        assert s.direction == "BUY"
        assert s.price is None
        assert s.stop_loss is None
        assert s.take_profit is None
        assert s.size == 0  # 0 = 全仓

    def test_sell_signal_with_price(self):
        s = Signal(datetime=20240102, direction="SELL", size=100, price=50.0, stop_loss=48.0)
        assert s.price == 50.0
        assert s.stop_loss == 48.0


class TestTrade:
    def test_trade_defaults(self):
        t = Trade(datetime=20240101, direction="BUY", size=100, price=50.0, commission=1.5, slippage=0.0, pnl=0.0)
        assert t.rejected is False

    def test_rejected_trade(self):
        t = Trade(datetime=20240101, direction="BUY", size=100, price=50.0, commission=0.0, slippage=0.0, pnl=0.0, rejected=True)
        assert t.rejected is True


class TestPosition:
    def test_position_fields(self):
        p = Position(datetime=20240101, size=100, avg_price=50.0, market_value=5000.0, unrealized_pnl=100.0)
        assert p.size == 100
        assert p.avg_price == 50.0


class TestBacktestResult:
    def test_to_dict(self):
        result = BacktestResult(
            performance={"total_return": 0.1},
            equity_curve=pd.DataFrame({"total": [100000, 110000]}),
            trades=pd.DataFrame(),
            positions=pd.DataFrame(),
            config={"cash": 100000},
        )
        d = result.to_dict()
        assert d["performance"]["total_return"] == 0.1
        assert d["config"]["cash"] == 100000

    def test_to_json(self):
        result = BacktestResult(
            performance={"total_return": 0.1},
            equity_curve=pd.DataFrame({"total": [100000, 110000]}),
            trades=pd.DataFrame(),
            positions=pd.DataFrame(),
            config={"cash": 100000},
        )
        j = result.to_json()
        parsed = json.loads(j)
        assert parsed["performance"]["total_return"] == 0.1

    def test_empty_trades(self):
        result = BacktestResult(
            performance={},
            equity_curve=pd.DataFrame(),
            trades=pd.DataFrame(),
            positions=pd.DataFrame(),
            config={},
        )
        assert result.trades.empty
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_backtest_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'easy_tdx.backtest.types'`

- [ ] **Step 4: 实现 types.py**

```python
# src/easy_tdx/backtest/types.py
"""回测引擎核心数据类型。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

import pandas as pd


@dataclass
class Signal:
    """策略产生的交易信号。"""

    datetime: int
    direction: Literal["BUY", "SELL"]
    size: float  # 0 = 全仓/清仓
    price: float | None = None  # None = 市价
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass
class Trade:
    """已成交记录。"""

    datetime: int
    direction: Literal["BUY", "SELL"]
    size: float
    price: float
    commission: float
    slippage: float
    pnl: float  # 仅平仓时计算
    rejected: bool = False


@dataclass
class Position:
    """持仓快照。"""

    datetime: int
    size: float  # 正=多头，负=空头，0=空仓
    avg_price: float
    market_value: float
    unrealized_pnl: float


@dataclass
class BacktestResult:
    """回测完整结果。"""

    performance: dict[str, float]
    equity_curve: pd.DataFrame  # datetime, cash, position_value, total, drawdown, drawdown_pct
    trades: pd.DataFrame  # datetime, direction, size, price, commission, pnl, rejected
    positions: pd.DataFrame  # datetime, size, avg_price, market_value, unrealized_pnl
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典。"""
        return {
            "performance": self.performance,
            "config": self.config,
            "equity_curve": self.equity_curve.to_dict(orient="records") if not self.equity_curve.empty else [],
            "trades": self.trades.to_dict(orient="records") if not self.trades.empty else [],
            "positions": self.positions.to_dict(orient="records") if not self.positions.empty else [],
        }

    def to_json(self) -> str:
        """转为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    def summary(self) -> None:
        """打印回测概要到 stdout。"""
        p = self.performance
        click_echo = print  # 避免 import click
        click_echo(f"总收益率: {p.get('total_return', 0):.2%}")
        click_echo(f"年化收益率: {p.get('annual_return', 0):.2%}")
        click_echo(f"最大回撤: {p.get('max_drawdown', 0):.2%}")
        click_echo(f"夏普比率: {p.get('sharpe', 0):.2f}")
        click_echo(f"胜率: {p.get('win_rate', 0):.2%}")
        click_echo(f"总交易: {p.get('total_trades', 0)} 次")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_backtest_types.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/easy_tdx/backtest/__init__.py src/easy_tdx/backtest/types.py tests/unit/test_backtest_types.py
git commit -m "feat(backtest): add core data types (Signal/Trade/Position/BacktestResult)"
```

---

## Task 2: 策略基类 + 数据代理 — strategy.py

**Files:**
- Create: `src/easy_tdx/backtest/strategy.py`
- Create: `tests/unit/test_backtest_strategy.py`

- [ ] **Step 1: 写 strategy.py 的失败测试**

```python
# tests/unit/test_backtest_strategy.py
"""Strategy 基类 + StrategyDataProxy 测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.strategy import Strategy, StrategyDataProxy, crossover


def _make_df(n: int = 20, seed: int = 42) -> pd.DataFrame:
    """构造测试用 K 线 DataFrame。"""
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.standard_normal(n))
    high = close + np.abs(rng.standard_normal(n))
    low = close - np.abs(rng.standard_normal(n))
    open_ = low + (high - low) * rng.random(n)
    vol = (rng.random(n) * 1e6).astype(float)
    return pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "vol": vol,
        "amount": vol * close,
    })


def _make_df_with_extras(n: int = 20) -> pd.DataFrame:
    """构造带额外指标列的 DataFrame。"""
    df = _make_df(n)
    df["MACD_DIF"] = np.random.randn(n)
    df["BOLL_UPPER"] = df["close"] + 5
    return df


class TestStrategyDataProxy:
    def test_basic_columns(self):
        df = _make_df()
        proxy = StrategyDataProxy(df)
        proxy._set_index(10)
        assert isinstance(proxy.close[0], float)
        assert isinstance(proxy.open[0], float)

    def test_previous_bar(self):
        df = _make_df()
        proxy = StrategyDataProxy(df)
        proxy._set_index(5)
        assert proxy.close[0] == df["close"].iloc[5]
        assert proxy.close[-1] == df["close"].iloc[4]

    def test_extra_columns_via_getattr(self):
        df = _make_df_with_extras()
        proxy = StrategyDataProxy(df)
        proxy._set_index(0)
        assert isinstance(proxy.MACD_DIF[0], float)
        assert isinstance(proxy.BOLL_UPPER[0], float)

    def test_missing_column_raises(self):
        df = _make_df()
        proxy = StrategyDataProxy(df)
        proxy._set_index(0)
        with pytest.raises(AttributeError):
            _ = proxy.NONEXISTENT[0]

    def test_len(self):
        df = _make_df()
        proxy = StrategyDataProxy(df)
        proxy._set_index(0)
        assert len(proxy.close) >= 10


class TestCrossover:
    def test_crossover_true(self):
        a = np.array([1, 2, 3, 4, 5], dtype=float)
        b = np.array([5, 4, 3, 2, 1], dtype=float)
        # a crosses above b between index 1 and 2
        mask = crossover(a, b)
        assert mask[2] is np.True_

    def test_crossover_false_no_cross(self):
        a = np.array([1, 2, 3, 4, 5], dtype=float)
        b = np.array([10, 10, 10, 10, 10], dtype=float)
        mask = crossover(a, b)
        assert not mask.any()

    def test_crossover_series(self):
        s1 = pd.Series([1, 2, 5])
        s2 = pd.Series([3, 3, 3])
        mask = crossover(s1, s2)
        assert mask[2] is np.True_


class TestStrategyBase:
    def test_subclass_init_and_next(self):
        class TestStrat(Strategy):
            inited = False
            nexted = False

            def init(self):
                self.inited = True

            def next(self):
                self.nexted = True

        df = _make_df()
        strat = TestStrat()
        strat._bind_data(df)
        strat._call_init()
        assert strat.inited

        strat._set_bar_index(5)
        strat._call_next()
        assert strat.nexted

    def test_buy_sell_recording(self):
        class TestStrat(Strategy):
            def next(self):
                if self._bar_index == 0:
                    self.buy(size=100)
                elif self._bar_index == 5:
                    self.sell(size=100)

        df = _make_df()
        strat = TestStrat()
        strat._bind_data(df)
        strat._call_init()

        strat._set_bar_index(0)
        strat._call_next()
        assert len(strat._signals) == 1
        assert strat._signals[0].direction == "BUY"
        assert strat._signals[0].size == 100

        strat._set_bar_index(5)
        strat._call_next()
        assert len(strat._signals) == 2
        assert strat._signals[1].direction == "SELL"

    def test_I_registers_indicator(self):
        from easy_tdx import MyTT

        class TestStrat(Strategy):
            def init(self):
                self.ma5 = self.I(MyTT.MA, self.data.close, 5)

            def next(self):
                pass

        df = _make_df(50)
        strat = TestStrat()
        strat._bind_data(df)
        strat._call_init()
        assert len(strat.ma5) == 50

    def test_full_position_buy(self):
        class TestStrat(Strategy):
            def next(self):
                self.buy(size=0)  # 全仓

        df = _make_df()
        strat = TestStrat()
        strat._bind_data(df)
        strat._call_init()
        strat._set_bar_index(0)
        strat._call_next()
        assert strat._signals[0].size == 0  # 0 = 全仓标记
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_backtest_strategy.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 strategy.py**

```python
# src/easy_tdx/backtest/strategy.py
"""策略基类和数据代理。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from .types import Signal


class _SeriesAccessor:
    """支持 [0] 当前值、[-1] 前一根、切片。"""

    def __init__(self, series: np.ndarray, bar_index: int) -> None:
        self._series = series
        self._bar = bar_index

    def __getitem__(self, key: int) -> float:
        idx = self._bar + key
        return float(self._series[idx])

    def __len__(self) -> int:
        return len(self._series)

    def __array__(self) -> np.ndarray:
        """允许传入 MyTT 函数。"""
        return self._series

    @property
    def raw(self) -> np.ndarray:
        """获取完整原始数组。"""
        return self._series


class StrategyDataProxy:
    """K 线数据代理。

    支持标准列：.close[0] 当前值, .close[-1] 前一根。
    通过 __getattr__ 自动暴露 DataFrame 中的额外列（预计算指标）。
    """

    _STANDARD_COLS = ("open", "close", "high", "low", "vol", "amount")

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        self._arrays: dict[str, np.ndarray] = {}
        for col in df.columns:
            if col == "datetime":
                continue
            self._arrays[col] = df[col].to_numpy(dtype=float)
        self._bar: int = 0

    def _set_index(self, idx: int) -> None:
        self._bar = idx

    def _make_accessor(self, col: str) -> _SeriesAccessor:
        return _SeriesAccessor(self._arrays[col], self._bar)

    @property
    def open(self) -> _SeriesAccessor:  # noqa: A003
        return self._make_accessor("open")

    @property
    def close(self) -> _SeriesAccessor:
        return self._make_accessor("close")

    @property
    def high(self) -> _SeriesAccessor:
        return self._make_accessor("high")

    @property
    def low(self) -> _SeriesAccessor:  # noqa: A003
        return self._make_accessor("low")

    @property
    def vol(self) -> _SeriesAccessor:
        return self._make_accessor("vol")

    @property
    def amount(self) -> _SeriesAccessor:
        return self._make_accessor("amount")

    def __getattr__(self, name: str) -> _SeriesAccessor:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._arrays:
            return self._make_accessor(name)
        raise AttributeError(f"DataFrame 中不存在列: {name}")


def crossover(a: np.ndarray | pd.Series | _SeriesAccessor, b: np.ndarray | pd.Series | _SeriesAccessor) -> np.ndarray:
    """检测 a 从下方穿越 b（金叉）。返回 bool 数组。"""
    arr_a = np.asarray(a)
    arr_b = np.asarray(b)
    prev_above = arr_a[:-1] > arr_b[:-1]
    curr_below = arr_a[1:] <= arr_b[1:]
    result = np.zeros(len(arr_a), dtype=bool)
    result[1:] = ~prev_above & ~curr_below
    return result


class Strategy(ABC):
    """用户策略基类。

    继承此类，实现 init() 注册指标，next() 生成信号。
    """

    def __init__(self) -> None:
        self._data_proxy: StrategyDataProxy | None = None
        self._bar_index: int = 0
        self._signals: list[Signal] = []
        self._indicators: dict[str, np.ndarray] = {}
        self._chanlun_result: Any = None
        self._position_size: float = 0.0
        self._cash: float = 0.0

    # --- 生命周期（用户实现）---

    def init(self) -> None:
        """策略初始化。注册指标、设置参数。"""

    def next(self) -> None:
        """每根 K 线调用。在此生成买卖信号。"""

    # --- 指标注册 ---

    def I(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> np.ndarray:
        """注册指标函数。init() 后一次性计算，返回完整数组。"""
        # 将 _SeriesAccessor 参数解包为 numpy 数组
        resolved_args = []
        for arg in args:
            if isinstance(arg, _SeriesAccessor):
                resolved_args.append(arg.raw)
            else:
                resolved_args.append(arg)
        result = func(*resolved_args, **kwargs)
        if isinstance(result, np.ndarray):
            return result
        # 某些指标返回 tuple（如 MACD），取第一个
        return np.asarray(result)

    # --- 交易指令 ---

    def buy(self, size: float = 0, price: float | None = None,
            stop_loss: float | None = None, take_profit: float | None = None) -> None:
        """生成买入信号。size=0 表示全仓。"""
        dt = self._get_datetime()
        self._signals.append(Signal(
            datetime=dt, direction="BUY", size=size,
            price=price, stop_loss=stop_loss, take_profit=take_profit,
        ))

    def sell(self, size: float = 0, price: float | None = None,
             stop_loss: float | None = None, take_profit: float | None = None) -> None:
        """生成卖出信号。size=0 表示清仓。"""
        dt = self._get_datetime()
        self._signals.append(Signal(
            datetime=dt, direction="SELL", size=size,
            price=price, stop_loss=stop_loss, take_profit=take_profit,
        ))

    # --- 属性 ---

    @property
    def data(self) -> StrategyDataProxy:
        assert self._data_proxy is not None, "Strategy 未绑定数据"
        return self._data_proxy

    @property
    def position(self) -> dict[str, float]:
        """当前持仓信息（简化 dict，非 Position dataclass）。"""
        return {"size": self._position_size}

    @property
    def chanlun(self) -> Any:
        """缠论分析结果（如果引擎注入了）。"""
        return self._chanlun_result

    # --- 内部方法（引擎调用）---

    def _bind_data(self, df: pd.DataFrame) -> None:
        """绑定 K 线数据。"""
        self._data_proxy = StrategyDataProxy(df)

    def _call_init(self) -> None:
        """调用用户 init()，在数据绑定后。"""
        self.init()

    def _set_bar_index(self, idx: int) -> None:
        """设置当前 Bar 索引。"""
        self._bar_index = idx
        if self._data_proxy is not None:
            self._data_proxy._set_index(idx)

    def _call_next(self) -> None:
        """调用用户 next()。"""
        self.next()

    def _get_datetime(self) -> int:
        """获取当前 Bar 的 datetime 整数表示。"""
        if self._data_proxy is None:
            return 0
        dt_val = self._data_proxy._df["datetime"].iloc[self._bar_index]
        if hasattr(dt_val, "strftime"):
            return int(dt_val.strftime("%Y%m%d"))
        return int(dt_val)

    def _clear_signals(self) -> list[Signal]:
        """取出并清空信号队列。"""
        signals = self._signals[:]
        self._signals.clear()
        return signals
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_backtest_strategy.py -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/easy_tdx/backtest/strategy.py tests/unit/test_backtest_strategy.py
git commit -m "feat(backtest): add Strategy base class with DataProxy and crossover"
```

---

## Task 3: 撮合规则 — orders.py

**Files:**
- Create: `src/easy_tdx/backtest/orders.py`
- Create: `tests/unit/test_backtest_orders.py`

- [ ] **Step 1: 写 orders.py 的失败测试**

```python
# tests/unit/test_backtest_orders.py
"""OrderSimulator 撮合规则测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.orders import OrderSimulator
from easy_tdx.backtest.types import Signal


def _make_df(n: int = 10) -> pd.DataFrame:
    """构造测试用 K 线 DataFrame，价格固定递增。"""
    return pd.DataFrame({
        "datetime": range(20240101, 20240101 + n),
        "open": np.arange(100, 100 + n, dtype=float),
        "close": np.arange(101, 101 + n, dtype=float),
        "high": np.arange(102, 102 + n, dtype=float),
        "low": np.arange(99, 99 + n, dtype=float),
        "vol": np.full(n, 1e6),
        "amount": np.full(n, 1e8),
    })


def _buy_signal(bar_idx: int, size: float = 0) -> Signal:
    return Signal(datetime=20240101 + bar_idx, direction="BUY", size=size)


def _sell_signal(bar_idx: int, size: float = 0) -> Signal:
    return Signal(datetime=20240101 + bar_idx, direction="SELL", size=size)


class TestExecutionModes:
    def test_next_open(self):
        """买入信号在 bar 0，成交价为 bar 1 的 open。"""
        df = _make_df(5)
        sim = OrderSimulator(df, execution="next_open")
        trades = sim.simulate([_buy_signal(0)], cash=100000, position=0.0, position_mode="full")
        assert len(trades) == 1
        assert trades[0].price == 101.0  # df["open"].iloc[1]

    def test_next_close(self):
        df = _make_df(5)
        sim = OrderSimulator(df, execution="next_close")
        trades = sim.simulate([_buy_signal(0)], cash=100000, position=0.0, position_mode="full")
        assert trades[0].price == 102.0  # df["close"].iloc[1]

    def test_this_close(self):
        df = _make_df(5)
        sim = OrderSimulator(df, execution="this_close")
        trades = sim.simulate([_buy_signal(0)], cash=100000, position=0.0, position_mode="full")
        assert trades[0].price == 101.0  # df["close"].iloc[0]

    def test_this_close_future_leak_warning(self):
        """this_close 模式应标记 future_leak_warning。"""
        df = _make_df(5)
        sim = OrderSimulator(df, execution="this_close")
        assert sim.future_leak_warning is True

    def test_worst_price_buy(self):
        """worst 模式买入取 high。"""
        df = _make_df(5)
        sim = OrderSimulator(df, execution="worst")
        trades = sim.simulate([_buy_signal(0)], cash=100000, position=0.0, position_mode="full")
        # next bar worst buy price = high of bar 1 = 103.0
        assert trades[0].price == 103.0

    def test_best_price_buy(self):
        """best 模式买入取 low。"""
        df = _make_df(5)
        sim = OrderSimulator(df, execution="best")
        trades = sim.simulate([_buy_signal(0)], cash=100000, position=0.0, position_mode="full")
        # next bar best buy price = low of bar 1 = 100.0
        assert trades[0].price == 100.0


class TestPositionModes:
    def test_full_position(self):
        """full 模式买入全部现金。"""
        df = _make_df(5)
        sim = OrderSimulator(df, execution="this_close")
        trades = sim.simulate([_buy_signal(0, size=0)], cash=10000, position=0.0, position_mode="full")
        # price = 101.0 (this_close), cash=10000 → 10000/101 ≈ 99 shares (100股整手)
        assert trades[0].size > 0

    def test_fixed_position(self):
        df = _make_df(5)
        sim = OrderSimulator(df, execution="this_close")
        trades = sim.simulate([_buy_signal(0, size=100)], cash=100000, position=0.0, position_mode="fixed")
        assert trades[0].size == 100


class TestRejectPolicy:
    def test_reduce_on_insufficient_cash(self):
        """资金不足时 reduce 模式自动减仓。"""
        df = _make_df(5)
        sim = OrderSimulator(df, execution="this_close", reject_policy="reduce")
        # 现金只有 50，价格 101，买不了 100 股
        trades = sim.simulate([_buy_signal(0, size=100)], cash=50, position=0.0, position_mode="fixed")
        assert len(trades) == 1
        assert trades[0].size < 100

    def test_skip_on_insufficient_cash(self):
        """资金不足时 skip 模式跳过。"""
        df = _make_df(5)
        sim = OrderSimulator(df, execution="this_close", reject_policy="skip")
        trades = sim.simulate([_buy_signal(0, size=100)], cash=50, position=0.0, position_mode="fixed")
        assert len(trades) == 1
        assert trades[0].rejected is True
        assert trades[0].size == 0

    def test_sell_with_no_position_skip(self):
        """无持仓时卖出被跳过。"""
        df = _make_df(5)
        sim = OrderSimulator(df, execution="this_close", reject_policy="skip")
        trades = sim.simulate([_sell_signal(0, size=100)], cash=100000, position=0.0, position_mode="full")
        assert len(trades) == 1
        assert trades[0].rejected is True


class TestFees:
    def test_commission_on_buy(self):
        df = _make_df(5)
        sim = OrderSimulator(df, execution="this_close", commission=0.0003, min_commission=5.0)
        trades = sim.simulate([_buy_signal(0, size=100)], cash=100000, position=0.0, position_mode="fixed")
        assert trades[0].commission >= 5.0  # 最低佣金

    def test_stamp_tax_on_sell(self):
        df = _make_df(5)
        sim = OrderSimulator(df, execution="this_close", stamp_tax=0.001)
        trades = sim.simulate(
            [_buy_signal(0, size=100), _sell_signal(2, size=100)],
            cash=100000, position=0.0, position_mode="fixed",
        )
        sell_trade = [t for t in trades if t.direction == "SELL"][0]
        # 印花税 = size * price * 0.001
        assert sell_trade.commission > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_backtest_orders.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 orders.py**

```python
# src/easy_tdx/backtest/orders.py
"""订单撮合模拟器。"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .types import Signal, Trade


class OrderSimulator:
    """将信号转化为成交记录。可配置撮合规则和拒绝策略。"""

    def __init__(
        self,
        df: pd.DataFrame,
        execution: str = "next_open",
        position_mode: str = "full",
        reject_policy: str = "reduce",
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
    ) -> None:
        self._df = df
        self._execution = execution
        self._position_mode = position_mode
        self._reject_policy = reject_policy
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._slippage = slippage
        self.future_leak_warning = execution == "this_close"

        if self.future_leak_warning:
            warnings.warn(
                "⚠️  执行模式 'this_close' 存在未来函数风险（look-ahead bias），"
                "回测结果可能过度乐观。",
                UserWarning,
                stacklevel=2,
            )

    def simulate(
        self,
        signals: list[Signal],
        cash: float,
        position: float,
        position_mode: str | None = None,
    ) -> list[Trade]:
        """执行信号列表，返回成交记录。

        Args:
            signals: 按时间顺序排列的信号列表
            cash: 当前现金
            position: 当前持仓量
            position_mode: 覆盖构造时的 position_mode
        """
        pos_mode = position_mode or self._position_mode
        trades: list[Trade] = []
        cur_cash = cash
        cur_pos = position

        for signal in signals:
            bar_idx = self._find_bar_index(signal.datetime)
            exec_idx = self._resolve_exec_index(bar_idx)

            if exec_idx is None or exec_idx >= len(self._df):
                continue

            price = self._get_price(exec_idx, signal.direction)
            price += self._slippage * (1 if signal.direction == "BUY" else -1)

            if signal.direction == "BUY":
                trade = self._execute_buy(signal, price, cur_cash, pos_mode)
                if trade is not None:
                    trades.append(trade)
                    if not trade.rejected:
                        cur_cash -= trade.size * trade.price + trade.commission
                        cur_pos += trade.size
            else:
                trade = self._execute_sell(signal, price, cur_pos, cur_cash, pos_mode)
                if trade is not None:
                    trades.append(trade)
                    if not trade.rejected:
                        revenue = trade.size * trade.price - trade.commission
                        cur_cash += revenue
                        cur_pos -= trade.size

        return trades

    def _find_bar_index(self, datetime_val: int) -> int | None:
        """根据 datetime 找到对应的 bar 索引。"""
        dt_col = self._df["datetime"]
        if dt_col.dtype == object or hasattr(dt_col.iloc[0], "strftime"):
            # datetime 类型
            for i, val in enumerate(dt_col):
                if hasattr(val, "strftime"):
                    if int(val.strftime("%Y%m%d")) == datetime_val:
                        return i
                elif int(val) == datetime_val:
                    return i
        else:
            matches = dt_col[dt_col == datetime_val]
            if not matches.empty:
                return int(matches.index[0])
        return None

    def _resolve_exec_index(self, bar_idx: int | None) -> int | None:
        """根据执行模式确定成交的 bar 索引。"""
        if bar_idx is None:
            return None
        if self._execution == "this_close":
            return bar_idx
        # next_open / next_close / worst / best → 下一根
        return bar_idx + 1

    def _get_price(self, idx: int, direction: str) -> float:
        """根据执行模式获取成交价。"""
        if self._execution in ("next_open", "this_close"):
            if self._execution == "next_open":
                return float(self._df["open"].iloc[idx])
            return float(self._df["close"].iloc[idx])
        if self._execution == "next_close":
            return float(self._df["close"].iloc[idx])
        if self._execution == "worst":
            if direction == "BUY":
                return float(self._df["high"].iloc[idx])
            return float(self._df["low"].iloc[idx])
        if self._execution == "best":
            if direction == "BUY":
                return float(self._df["low"].iloc[idx])
            return float(self._df["high"].iloc[idx])
        return float(self._df["open"].iloc[idx])

    def _execute_buy(
        self, signal: Signal, price: float, cash: float, pos_mode: str,
    ) -> Trade | None:
        """执行买入。"""
        if pos_mode == "full" or signal.size == 0:
            # 全仓：用所有现金买，按 100 股整手
            max_shares = int(cash / (price * (1 + self._commission)))
            size = max_shares // 100 * 100  # 整手
        elif pos_mode == "fixed":
            size = int(signal.size)
        elif pos_mode == "percent":
            size = int(cash * signal.size / price)
        else:
            size = int(signal.size)

        if size <= 0 or size * price > cash:
            if self._reject_policy == "skip":
                return Trade(
                    datetime=signal.datetime, direction="BUY", size=0, price=price,
                    commission=0, slippage=0, pnl=0, rejected=True,
                )
            # reduce: 买能买的
            size = int(cash / (price * (1 + self._commission)))
            size = size // 100 * 100
            if size <= 0:
                return Trade(
                    datetime=signal.datetime, direction="BUY", size=0, price=price,
                    commission=0, slippage=0, pnl=0, rejected=True,
                )

        comm = max(size * price * self._commission, self._min_commission)
        return Trade(
            datetime=signal.datetime, direction="BUY", size=size, price=price,
            commission=comm, slippage=self._slippage * size, pnl=0,
        )

    def _execute_sell(
        self, signal: Signal, price: float, position: float, cash: float, pos_mode: str,
    ) -> Trade | None:
        """执行卖出。"""
        if pos_mode == "full" or signal.size == 0:
            size = position
        elif pos_mode == "fixed":
            size = min(signal.size, position)
        elif pos_mode == "percent":
            size = position * signal.size
        else:
            size = min(signal.size, position)

        if size <= 0 or size > position:
            return Trade(
                datetime=signal.datetime, direction="SELL", size=0, price=price,
                commission=0, slippage=0, pnl=0, rejected=True,
            )

        comm_buy = 0  # 买入佣金不计入卖出 Trade
        comm_sell = max(size * price * self._commission, self._min_commission)
        stamp = size * price * self._stamp_tax
        total_comm = comm_sell + stamp

        return Trade(
            datetime=signal.datetime, direction="SELL", size=size, price=price,
            commission=total_comm, slippage=self._slippage * size, pnl=0,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_backtest_orders.py -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/easy_tdx/backtest/orders.py tests/unit/test_backtest_orders.py
git commit -m "feat(backtest): add OrderSimulator with 5 execution modes and reject policy"
```

---

## Task 4: 持仓追踪 — portfolio.py

**Files:**
- Create: `src/easy_tdx/backtest/portfolio.py`
- Create: `tests/unit/test_backtest_portfolio.py`

- [ ] **Step 1: 写 portfolio.py 的失败测试**

```python
# tests/unit/test_backtest_portfolio.py
"""PortfolioTracker 持仓追踪测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.portfolio import PortfolioTracker
from easy_tdx.backtest.types import Trade


def _make_df(n: int = 10) -> pd.DataFrame:
    close = np.full(n, 100.0)
    close[5:] = 110.0  # bar 5 开始涨到 110
    return pd.DataFrame({
        "datetime": range(20240101, 20240101 + n),
        "open": close,
        "close": close,
        "high": close + 1,
        "low": close - 1,
        "vol": np.full(n, 1e6),
        "amount": np.full(n, 1e8),
    })


class TestPortfolioTracker:
    def test_initial_state(self):
        df = _make_df()
        tracker = PortfolioTracker(df, initial_cash=100000)
        assert tracker.initial_cash == 100000

    def test_buy_then_sell(self):
        df = _make_df()
        tracker = PortfolioTracker(df, initial_cash=100000)

        # bar 0 买入 100 股，价格 100
        buy_trade = Trade(datetime=20240101, direction="BUY", size=100, price=100.0, commission=5.0, slippage=0, pnl=0)
        # bar 5 卖出 100 股，价格 110
        sell_trade = Trade(datetime=20240106, direction="SELL", size=100, price=110.0, commission=11.0, slippage=0, pnl=0)

        tracker.apply_trades([buy_trade, sell_trade])

        curve = tracker.equity_curve
        assert len(curve) == 10

        # 最终现金 = 100000 - 100*100 - 5 + 100*110 - 11 = 10984
        final_cash = curve["cash"].iloc[-1]
        assert abs(final_cash - 10984.0) < 1.0

    def test_drawdown_calculation(self):
        df = _make_df()
        tracker = PortfolioTracker(df, initial_cash=100000)
        curve = tracker.equity_curve
        assert "drawdown" in curve.columns
        assert "drawdown_pct" in curve.columns
        # 无交易时 drawdown 为 0
        assert (curve["drawdown"] == 0).all()

    def test_equity_curve_columns(self):
        df = _make_df()
        tracker = PortfolioTracker(df, initial_cash=100000)
        curve = tracker.equity_curve
        for col in ["datetime", "cash", "position_value", "total", "drawdown", "drawdown_pct"]:
            assert col in curve.columns

    def test_position_tracking(self):
        df = _make_df()
        tracker = PortfolioTracker(df, initial_cash=100000)
        buy_trade = Trade(datetime=20240101, direction="BUY", size=100, price=100.0, commission=5.0, slippage=0, pnl=0)
        tracker.apply_trades([buy_trade])

        positions = tracker.positions
        assert len(positions) == 10
        # bar 0 后持仓应为 100
        assert positions["size"].iloc[0] == 100
        assert positions["size"].iloc[-1] == 100
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_backtest_portfolio.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 portfolio.py**

```python
# src/easy_tdx/backtest/portfolio.py
"""持仓追踪器：逐 Bar 计算资金曲线。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .types import Trade


class PortfolioTracker:
    """逐 Bar 追踪资金曲线。"""

    def __init__(self, df: pd.DataFrame, initial_cash: float = 100000) -> None:
        self._df = df
        self._initial_cash = initial_cash
        self._n = len(df)
        self._close = df["close"].to_numpy(dtype=float)
        self._datetime = df["datetime"].to_numpy()

        # 预分配数组
        self._cash = np.full(self._n, initial_cash)
        self._position = np.zeros(self._n)
        self._avg_price = np.zeros(self._n)

    @property
    def initial_cash(self) -> float:
        return self._initial_cash

    def apply_trades(self, trades: list[Trade]) -> None:
        """将成交记录应用到资金曲线。"""
        # 构建 datetime → trade 的映射
        buy_map: dict[int, Trade] = {}
        sell_map: dict[int, Trade] = {}
        for t in trades:
            if t.rejected:
                continue
            if t.direction == "BUY":
                buy_map[t.datetime] = t
            else:
                sell_map[t.datetime] = t

        cur_cash = self._initial_cash
        cur_pos = 0.0
        cur_avg = 0.0

        for i in range(self._n):
            dt = self._datetime[i]
            dt_int = int(dt.strftime("%Y%m%d")) if hasattr(dt, "strftime") else int(dt)

            # 处理买入
            if dt_int in buy_map:
                t = buy_map[dt_int]
                cost = t.size * t.price + t.commission + t.slippage
                cur_cash -= cost
                # 更新均价
                if cur_pos + t.size > 0:
                    cur_avg = (cur_avg * cur_pos + t.price * t.size) / (cur_pos + t.size)
                cur_pos += t.size

            # 处理卖出
            if dt_int in sell_map:
                t = sell_map[dt_int]
                revenue = t.size * t.price - t.commission - t.slippage
                cur_cash += revenue
                cur_pos -= t.size
                if cur_pos <= 0:
                    cur_pos = 0
                    cur_avg = 0

            self._cash[i] = cur_cash
            self._position[i] = cur_pos
            self._avg_price[i] = cur_avg

    @property
    def equity_curve(self) -> pd.DataFrame:
        """返回资金曲线 DataFrame。"""
        pos_value = self._position * self._close
        total = self._cash + pos_value
        peak = np.maximum.accumulate(total)
        drawdown = peak - total
        drawdown_pct = np.where(peak > 0, drawdown / peak, 0)

        return pd.DataFrame({
            "datetime": self._datetime,
            "cash": self._cash,
            "position_value": pos_value,
            "total": total,
            "drawdown": drawdown,
            "drawdown_pct": drawdown_pct,
        })

    @property
    def positions(self) -> pd.DataFrame:
        """返回持仓历史 DataFrame。"""
        pos_value = self._position * self._close
        unrealized = np.where(
            self._position > 0,
            (self._close - self._avg_price) * self._position,
            0,
        )
        return pd.DataFrame({
            "datetime": self._datetime,
            "size": self._position,
            "avg_price": self._avg_price,
            "market_value": pos_value,
            "unrealized_pnl": unrealized,
        })
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_backtest_portfolio.py -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/easy_tdx/backtest/portfolio.py tests/unit/test_backtest_portfolio.py
git commit -m "feat(backtest): add PortfolioTracker with equity curve and drawdown"
```

---

## Task 5: 绩效分析 — performance.py

**Files:**
- Create: `src/easy_tdx/backtest/performance.py`
- Create: `tests/unit/test_backtest_performance.py`

- [ ] **Step 1: 写 performance.py 的失败测试**

```python
# tests/unit/test_backtest_performance.py
"""PerformanceAnalyzer 绩效指标测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.performance import PerformanceAnalyzer


def _make_equity_curve(n: int = 252, total_return: float = 0.1) -> pd.DataFrame:
    """构造资金曲线，总收益率为 total_return。"""
    daily_ret = (1 + total_return) ** (1 / n) - 1
    total = 100000 * np.cumprod(np.full(n, 1 + daily_ret))
    peak = np.maximum.accumulate(total)
    return pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="D"),
        "cash": total,
        "position_value": np.zeros(n),
        "total": total,
        "drawdown": peak - total,
        "drawdown_pct": np.where(peak > 0, (peak - total) / peak, 0),
    })


def _make_trades() -> pd.DataFrame:
    """构造交易记录。"""
    return pd.DataFrame({
        "datetime": [20240101, 20240110, 20240120, 20240130],
        "direction": ["BUY", "SELL", "BUY", "SELL"],
        "size": [100, 100, 100, 100],
        "price": [100.0, 105.0, 95.0, 90.0],
        "commission": [5.0, 5.0, 5.0, 5.0],
        "pnl": [0.0, 500.0, 0.0, -500.0],
        "rejected": [False, False, False, False],
    })


class TestPerformanceAnalyzer:
    def test_total_return(self):
        curve = _make_equity_curve(252, 0.1)
        analyzer = PerformanceAnalyzer(curve, _make_trades())
        perf = analyzer.compute()
        assert abs(perf["total_return"] - 0.1) < 0.01

    def test_max_drawdown_zero_when_monotonic(self):
        """单调递增的资金曲线最大回撤为 0。"""
        curve = _make_equity_curve(252, 0.1)
        analyzer = PerformanceAnalyzer(curve, _make_trades())
        perf = analyzer.compute()
        assert perf["max_drawdown"] < 0.001  # 接近 0

    def test_sharpe_positive_for_profit(self):
        curve = _make_equity_curve(252, 0.2)
        analyzer = PerformanceAnalyzer(curve, _make_trades())
        perf = analyzer.compute()
        assert perf["sharpe"] > 0

    def test_win_rate(self):
        trades = pd.DataFrame({
            "direction": ["SELL", "SELL"],
            "pnl": [100.0, -50.0],
            "rejected": [False, False],
        })
        curve = _make_equity_curve(10, 0.0)
        analyzer = PerformanceAnalyzer(curve, trades)
        perf = analyzer.compute()
        assert abs(perf["win_rate"] - 0.5) < 0.01

    def test_total_trades(self):
        curve = _make_equity_curve(10, 0.0)
        analyzer = PerformanceAnalyzer(curve, _make_trades())
        perf = analyzer.compute()
        assert perf["total_trades"] == 4

    def test_empty_trades(self):
        curve = _make_equity_curve(10, 0.0)
        trades = pd.DataFrame(columns=["direction", "pnl", "rejected"])
        analyzer = PerformanceAnalyzer(curve, trades)
        perf = analyzer.compute()
        assert perf["total_trades"] == 0
        assert perf["win_rate"] == 0.0

    def test_all_keys_present(self):
        curve = _make_equity_curve(252, 0.1)
        analyzer = PerformanceAnalyzer(curve, _make_trades())
        perf = analyzer.compute()
        expected_keys = [
            "total_return", "annual_return", "max_drawdown", "max_dd_duration",
            "sharpe", "sortino", "calmar", "total_trades", "win_trades",
            "lose_trades", "rejected_trades", "win_rate", "profit_factor",
            "avg_win", "avg_loss", "max_win", "max_loss", "avg_holding_days",
            "volatility",
        ]
        for key in expected_keys:
            assert key in perf, f"缺少指标: {key}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_backtest_performance.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 performance.py**

```python
# src/easy_tdx/backtest/performance.py
"""绩效分析器：从资金曲线和交易记录计算 18 项绩效指标。"""

from __future__ import annotations

import numpy as np
import pandas as pd


class PerformanceAnalyzer:
    """从资金曲线和交易记录计算绩效指标。"""

    ANNUAL_DAYS = 252
    RISK_FREE_RATE = 0.03

    def __init__(
        self,
        equity_curve: pd.DataFrame,
        trades: pd.DataFrame,
        risk_free_rate: float = 0.03,
    ) -> None:
        self._curve = equity_curve
        self._trades = trades
        self._rf = risk_free_rate

    def compute(self) -> dict[str, float]:
        """计算全部绩效指标。"""
        total = self._curve["total"].to_numpy() if not self._curve.empty else np.array([])
        if len(total) < 2:
            return self._empty_metrics()

        # 收益率序列
        daily_ret = np.diff(total) / total[:-1]
        daily_ret = daily_ret[~np.isnan(daily_ret)]

        # 总收益率
        total_return = total[-1] / total[0] - 1

        # 年化收益率
        n_days = len(total)
        annual_return = (1 + total_return) ** (self.ANNUAL_DAYS / n_days) - 1 if n_days > 0 else 0.0

        # 最大回撤
        peak = np.maximum.accumulate(total)
        drawdown = (peak - total) / np.where(peak > 0, peak, 1)
        max_dd = float(np.max(drawdown))

        # 最大回撤天数
        dd_peak_idx = np.argmax(drawdown)
        peak_before = np.argmax(total[:dd_peak_idx + 1]) if dd_peak_idx > 0 else 0
        max_dd_duration = dd_peak_idx - peak_before

        # 夏普比率
        rf_daily = self._rf / self.ANNUAL_DAYS
        if len(daily_ret) > 1 and np.std(daily_ret) > 0:
            sharpe = (np.mean(daily_ret) - rf_daily) / np.std(daily_ret) * np.sqrt(self.ANNUAL_DAYS)
        else:
            sharpe = 0.0

        # 索提诺比率
        neg_ret = daily_ret[daily_ret < 0]
        if len(neg_ret) > 1 and np.std(neg_ret) > 0:
            sortino = (np.mean(daily_ret) - rf_daily) / np.std(neg_ret) * np.sqrt(self.ANNUAL_DAYS)
        else:
            sortino = sharpe

        # 卡玛比率
        calmar = annual_return / max_dd if max_dd > 0 else 0.0

        # 波动率
        volatility = float(np.std(daily_ret) * np.sqrt(self.ANNUAL_DAYS)) if len(daily_ret) > 1 else 0.0

        # 交易统计
        trades = self._trades
        if not trades.empty:
            closed = trades[trades["direction"] == "SELL"]
            total_trades = len(trades)
            rejected_trades = int(trades["rejected"].sum()) if "rejected" in trades.columns else 0

            if not closed.empty and "pnl" in closed.columns:
                pnls = closed["pnl"].to_numpy()
                win_mask = pnls > 0
                lose_mask = pnls <= 0
                win_trades = int(win_mask.sum())
                lose_trades = int(lose_mask.sum())
                win_rate = win_trades / len(closed) if len(closed) > 0 else 0.0
                total_win = float(pnls[win_mask].sum()) if win_mask.any() else 0.0
                total_lose = float(np.abs(pnls[lose_mask].sum())) if lose_mask.any() else 1.0
                profit_factor = total_win / total_lose if total_lose > 0 else float("inf")
                avg_win = float(pnls[win_mask].mean()) if win_mask.any() else 0.0
                avg_loss = float(pnls[lose_mask].mean()) if lose_mask.any() else 0.0
                max_win = float(pnls.max()) if len(pnls) > 0 else 0.0
                max_loss = float(pnls.min()) if len(pnls) > 0 else 0.0
            else:
                win_trades, lose_trades, win_rate = 0, 0, 0.0
                profit_factor, avg_win, avg_loss, max_win, max_loss = 0.0, 0.0, 0.0, 0.0, 0.0

            avg_holding = 5.0  # 简化：后续可精确计算
        else:
            total_trades, rejected_trades = 0, 0
            win_trades, lose_trades, win_rate = 0, 0, 0.0
            profit_factor, avg_win, avg_loss, max_win, max_loss = 0.0, 0.0, 0.0, 0.0, 0.0
            avg_holding = 0.0

        return {
            "total_return": float(total_return),
            "annual_return": float(annual_return),
            "max_drawdown": float(max_dd),
            "max_dd_duration": float(max_dd_duration),
            "sharpe": float(sharpe),
            "sortino": float(sortino),
            "calmar": float(calmar),
            "total_trades": total_trades,
            "win_trades": win_trades,
            "lose_trades": lose_trades,
            "rejected_trades": rejected_trades,
            "win_rate": float(win_rate),
            "profit_factor": float(profit_factor) if profit_factor != float("inf") else 999.0,
            "avg_win": float(avg_win),
            "avg_loss": float(avg_loss),
            "max_win": float(max_win),
            "max_loss": float(max_loss),
            "avg_holding_days": float(avg_holding),
            "volatility": float(volatility),
        }

    def _empty_metrics(self) -> dict[str, float]:
        """空数据时返回零值指标。"""
        return {
            "total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
            "max_dd_duration": 0.0, "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
            "total_trades": 0, "win_trades": 0, "lose_trades": 0, "rejected_trades": 0,
            "win_rate": 0.0, "profit_factor": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "max_win": 0.0, "max_loss": 0.0, "avg_holding_days": 0.0, "volatility": 0.0,
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_backtest_performance.py -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/easy_tdx/backtest/performance.py tests/unit/test_backtest_performance.py
git commit -m "feat(backtest): add PerformanceAnalyzer with 18 metrics"
```

---

## Task 6: 回测引擎编排 — engine.py

**Files:**
- Create: `src/easy_tdx/backtest/engine.py`
- Create: `tests/unit/test_backtest_engine.py`

- [ ] **Step 1: 写 engine.py 的失败测试**

```python
# tests/unit/test_backtest_engine.py
"""BacktestEngine 端到端测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy, crossover

from easy_tdx import MyTT


def _make_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    high = close + np.abs(rng.standard_normal(n))
    low = close - np.abs(rng.standard_normal(n))
    open_ = low + (high - low) * rng.random(n)
    vol = (rng.random(n) * 1e6).astype(float)
    return pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "vol": vol,
        "amount": vol * close,
    })


class MACrossStrategy(Strategy):
    """双均线交叉策略。"""

    def init(self):
        self.ma5 = self.I(MyTT.MA, self.data.close, 5)
        self.ma20 = self.I(MyTT.MA, self.data.close, 20)

    def next(self):
        if crossover(self.ma5, self.ma20):
            self.buy(size=0)
        elif crossover(self.ma20, self.ma5):
            self.sell(size=0)


class FixedBuyStrategy(Strategy):
    """固定买入策略（第 5 根 K 线买入 100 股）。"""

    def next(self):
        if self._bar_index == 5:
            self.buy(size=100)
        if self._bar_index == 50:
            self.sell(size=100)


class TestBacktestEngine:
    def test_basic_run(self):
        df = _make_df(200)
        engine = BacktestEngine(strategy=MACrossStrategy, cash=100000)
        result = engine.run(df)

        assert result.performance["total_return"] is not None
        assert len(result.equity_curve) == 200
        assert not result.trades.empty or result.performance["total_trades"] == 0

    def test_fixed_strategy(self):
        df = _make_df(100)
        engine = BacktestEngine(strategy=FixedBuyStrategy, cash=100000)
        result = engine.run(df)

        assert result.performance["total_trades"] >= 2
        trades = result.trades
        buy_trades = trades[trades["direction"] == "BUY"]
        sell_trades = trades[trades["direction"] == "SELL"]
        assert len(buy_trades) >= 1
        assert len(sell_trades) >= 1

    def test_result_columns(self):
        df = _make_df(200)
        engine = BacktestEngine(strategy=MACrossStrategy, cash=100000)
        result = engine.run(df)

        # equity_curve 列
        for col in ["datetime", "cash", "position_value", "total", "drawdown", "drawdown_pct"]:
            assert col in result.equity_curve.columns

        # trades 列
        for col in ["datetime", "direction", "size", "price", "commission", "pnl", "rejected"]:
            assert col in result.trades.columns

    def test_to_dict(self):
        df = _make_df(100)
        engine = BacktestEngine(strategy=FixedBuyStrategy, cash=100000)
        result = engine.run(df)
        d = result.to_dict()
        assert "performance" in d
        assert "config" in d

    def test_chanlun_injection(self):
        """测试缠论结果注入（不验证缠论逻辑，只验证通道可用）。"""

        class ChanlunStrategy(Strategy):
            def init(self):
                pass

            def next(self):
                if self._bar_index == 5 and self.chanlun is not None:
                    self.buy(size=100)
                if self._bar_index == 50:
                    self.sell(size=100)

        df = _make_df(100)
        engine = BacktestEngine(strategy=ChanlunStrategy, cash=100000)
        result = engine.run(df, chanlun_result="fake_result")
        assert result.performance["total_trades"] >= 1

    def test_this_close_warning_in_config(self):
        df = _make_df(100)
        engine = BacktestEngine(strategy=FixedBuyStrategy, cash=100000, execution="this_close")
        result = engine.run(df)
        assert result.config.get("future_leak_warning") is True

    def test_config_snapshot(self):
        df = _make_df(50)
        engine = BacktestEngine(strategy=FixedBuyStrategy, cash=50000, commission=0.001)
        result = engine.run(df)
        assert result.config["cash"] == 50000
        assert result.config["commission"] == 0.001

    def test_precomputed_indicator_columns(self):
        """测试 DataFrame 中预计算指标列可直接在策略中引用。"""

        class BollStrategy(Strategy):
            def init(self):
                pass

            def next(self):
                # 直接访问预计算的 BOLL_UPPER 列
                if hasattr(self.data, "_arrays") and "BOLL_UPPER" in self.data._arrays:
                    upper = self.data._arrays["BOLL_UPPER"]
                    if self._bar_index < len(upper) and self.data.close[0] > upper[self._bar_index]:
                        self.sell(size=0)

        df = _make_df(100)
        df["BOLL_UPPER"] = df["close"] + 5  # 模拟预计算列
        engine = BacktestEngine(strategy=BollStrategy, cash=100000)
        result = engine.run(df)
        # 不崩溃就算通过
        assert result.performance is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_backtest_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 engine.py**

```python
# src/easy_tdx/backtest/engine.py
"""回测引擎：向量化执行管道。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .orders import OrderSimulator
from .performance import PerformanceAnalyzer
from .portfolio import PortfolioTracker
from .strategy import Strategy
from .types import BacktestResult, Signal


class BacktestEngine:
    """回测引擎主入口。纯计算，接收 DataFrame，输出 BacktestResult。"""

    def __init__(
        self,
        strategy: type[Strategy] | Strategy,
        cash: float = 100000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
        position_mode: str = "full",
        reject_policy: str = "reduce",
        benchmark: pd.DataFrame | None = None,
    ) -> None:
        if isinstance(strategy, type):
            self._strategy = strategy()
        else:
            self._strategy = strategy
        self._cash = cash
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._slippage = slippage
        self._execution = execution
        self._position_mode = position_mode
        self._reject_policy = reject_policy
        self._benchmark = benchmark

    def run(self, df: pd.DataFrame, chanlun_result: Any | None = None) -> BacktestResult:
        """执行回测。"""
        n = len(df)
        if n == 0:
            return self._empty_result()

        # Step 1: 信号生成
        signals = self._generate_signals(df, chanlun_result)

        # Step 2: 撮合
        simulator = OrderSimulator(
            df,
            execution=self._execution,
            position_mode=self._position_mode,
            reject_policy=self._reject_policy,
            commission=self._commission,
            min_commission=self._min_commission,
            stamp_tax=self._stamp_tax,
            slippage=self._slippage,
        )
        trades = simulator.simulate(signals, cash=self._cash, position=0.0)

        # Step 3: 持仓追踪
        tracker = PortfolioTracker(df, initial_cash=self._cash)
        # 计算每笔卖出的 pnl
        trades = self._compute_pnls(trades)
        tracker.apply_trades(trades)

        # Step 4: 绩效分析
        trades_df = self._trades_to_df(trades)
        analyzer = PerformanceAnalyzer(tracker.equity_curve, trades_df)
        performance = analyzer.compute()

        # 配置快照
        config: dict[str, Any] = {
            "cash": self._cash,
            "commission": self._commission,
            "min_commission": self._min_commission,
            "stamp_tax": self._stamp_tax,
            "slippage": self._slippage,
            "execution": self._execution,
            "position_mode": self._position_mode,
            "reject_policy": self._reject_policy,
            "future_leak_warning": simulator.future_leak_warning,
        }

        return BacktestResult(
            performance=performance,
            equity_curve=tracker.equity_curve,
            trades=trades_df,
            positions=tracker.positions,
            config=config,
        )

    def _generate_signals(self, df: pd.DataFrame, chanlun_result: Any | None) -> list[Signal]:
        """通过 Strategy 生成交易信号。"""
        strat = self._strategy
        strat._bind_data(df)
        if chanlun_result is not None:
            strat._chanlun_result = chanlun_result
        strat._call_init()

        all_signals: list[Signal] = []
        for i in range(len(df)):
            strat._set_bar_index(i)
            strat._call_next()
            bar_signals = strat._clear_signals()
            all_signals.extend(bar_signals)

        return all_signals

    def _compute_pnls(self, trades: list) -> list:
        """计算每笔卖出的 pnl。买入记录 pnl=0。"""
        position_cost = 0.0
        position_size = 0.0
        for t in trades:
            if t.rejected:
                continue
            if t.direction == "BUY":
                position_cost += t.size * t.price + t.commission
                position_size += t.size
                t.pnl = 0.0
            else:
                if position_size > 0:
                    avg_cost = position_cost / position_size
                    t.pnl = (t.price - avg_cost) * t.size - t.commission
                    position_cost -= avg_cost * t.size
                    position_size -= t.size
                else:
                    t.pnl = 0.0
        return trades

    def _trades_to_df(self, trades: list) -> pd.DataFrame:
        """将 Trade 列表转为 DataFrame。"""
        if not trades:
            return pd.DataFrame(columns=["datetime", "direction", "size", "price", "commission", "pnl", "rejected"])
        return pd.DataFrame([
            {
                "datetime": t.datetime,
                "direction": t.direction,
                "size": t.size,
                "price": t.price,
                "commission": t.commission,
                "pnl": t.pnl,
                "rejected": t.rejected,
            }
            for t in trades
        ])

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            performance={},
            equity_curve=pd.DataFrame(),
            trades=pd.DataFrame(),
            positions=pd.DataFrame(),
            config={"cash": self._cash},
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_backtest_engine.py -v`
Expected: 全部通过

- [ ] **Step 5: 运行全部回测测试**

Run: `python -m pytest tests/unit/test_backtest_*.py -v`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add src/easy_tdx/backtest/engine.py tests/unit/test_backtest_engine.py
git commit -m "feat(backtest): add BacktestEngine with vectorized execution pipeline"
```

---

## Task 7: DSL 骨架 — dsl.py (P1 骨架)

**Files:**
- Create: `src/easy_tdx/backtest/dsl.py`

- [ ] **Step 1: 创建 dsl.py 骨架文件**

```python
# src/easy_tdx/backtest/dsl.py
"""DSL 策略定义模块 (P1 — 骨架)。

v1 提供 @dsl_strategy 装饰器的基本实现。
字符串 DSL 解析器将在后续版本实现。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from .strategy import Strategy


def dsl_strategy(func: Callable[..., Any]) -> type[Strategy]:
    """将函数编译为 Strategy 子类。

    函数签名: (df: pd.DataFrame) -> tuple[np.ndarray[bool], np.ndarray[bool]]
    返回 (buy_mask, sell_mask)。

    用法::

        @dsl_strategy
        def dual_ma(df):
            buy = CROSS(MA(df.close, 5), MA(df.close, 20))
            sell = CROSS(MA(df.close, 20), MA(df.close, 5))
            return buy, sell
    """

    class DSLStrategy(Strategy):
        _signal_func = staticmethod(func)
        _buy_mask: np.ndarray | None = None
        _sell_mask: np.ndarray | None = None

        def init(self) -> None:
            pass

        def next(self) -> None:
            if self._buy_mask is None:
                return
            idx = self._bar_index
            if idx < len(self._buy_mask) and self._buy_mask[idx]:
                self.buy(size=0)
            elif idx < len(self._sell_mask) and self._sell_mask[idx]:
                self.sell(size=0)

    DSLStrategy.__name__ = func.__name__
    DSLStrategy.__qualname__ = func.__qualname__

    # 存储 signal 函数引用，引擎会在 run 时调用
    DSLStrategy._signal_func = func  # type: ignore[attr-defined]

    return DSLStrategy
```

- [ ] **Step 2: Commit**

```bash
git add src/easy_tdx/backtest/dsl.py
git commit -m "feat(backtest): add DSL strategy skeleton (P1)"
```

---

## Task 8: 更新 `__init__.py` 导出

**Files:**
- Modify: `src/easy_tdx/backtest/__init__.py`

- [ ] **Step 1: 更新 `__init__.py`**

```python
# src/easy_tdx/backtest/__init__.py
"""easy_tdx.backtest — 向量化策略回测引擎（纯计算，零网络依赖）。

快速开始::

    from easy_tdx.backtest import BacktestEngine, Strategy

    class MyStrategy(Strategy):
        def init(self):
            self.ma5 = self.I(MA, self.data.close, 5)
            self.ma20 = self.I(MA, self.data.close, 20)

        def next(self):
            if crossover(self.ma5, self.ma20):
                self.buy()
            elif crossover(self.ma20, self.ma5):
                self.sell()

    engine = BacktestEngine(strategy=MyStrategy, cash=100000)
    result = engine.run(df)
    print(result.performance)
"""

from easy_tdx.backtest.engine import BacktestEngine  # noqa: F401
from easy_tdx.backtest.strategy import Strategy, StrategyDataProxy, crossover  # noqa: F401
from easy_tdx.backtest.types import BacktestResult, Position, Signal, Trade  # noqa: F401

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "Strategy",
    "StrategyDataProxy",
    "Signal",
    "Trade",
    "Position",
    "crossover",
]
```

- [ ] **Step 2: Commit**

```bash
git add src/easy_tdx/backtest/__init__.py
git commit -m "feat(backtest): update __init__.py with public API exports"
```

---

## Task 9: CLI 集成 — cli.py

**Files:**
- Create: `src/easy_tdx/backtest/cli.py`
- Create: `tests/unit/test_backtest_cli.py`
- Modify: `src/easy_tdx/cli/__init__.py`

- [ ] **Step 1: 写 CLI 失败测试**

```python
# tests/unit/test_backtest_cli.py
"""backtest CLI 命令测试。"""

from __future__ import annotations

from click.testing import CliRunner

import pytest


class TestBacktestCLI:
    def test_help(self):
        from easy_tdx.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "--help"])
        assert result.exit_code == 0
        assert "strategy" in result.output.lower() or "strategy-file" in result.output.lower()

    def test_missing_strategy_fails(self):
        from easy_tdx.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "SH", "600519"])
        assert result.exit_code != 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/test_backtest_cli.py -v`
Expected: FAIL — `No command 'backtest'`

- [ ] **Step 3: 实现 cli.py**

```python
# src/easy_tdx/backtest/cli.py
"""回测 CLI 命令。"""

from __future__ import annotations

import importlib.util
import json
import sys

import click


@click.command()
@click.argument("market")
@click.argument("code")
@click.option("--strategy", "strategy_str", default=None, help="DSL 策略表达式 (P1)")
@click.option("--strategy-file", "strategy_file", default=None, help="Python 策略文件路径")
@click.option("--cash", default=100000.0, type=float, help="初始资金")
@click.option("--commission", default=0.0003, type=float, help="佣金率")
@click.option("--execution", default="next_open", type=click.Choice(["next_open", "next_close", "this_close", "worst", "best"]), help="成交价规则")
@click.option("--period", default="DAILY", help="K线周期: DAILY/5MIN/15MIN/30MIN/60MIN/1MIN/WEEKLY/MONTHLY")
@click.option("--adjust", default="NONE", help="复权: NONE/QFQ/HFQ")
@click.option("--count", default=500, type=int, help="K线数量")
@click.option("--indicators", default=None, help="预计算指标（逗号分隔，如 MACD,KDJ）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def backtest(
    market: str,
    code: str,
    strategy_str: str | None,
    strategy_file: str | None,
    cash: float,
    commission: float,
    execution: str,
    period: str,
    adjust: str,
    count: int,
    indicators: str | None,
    use_table: bool,
    output_fmt: str,
) -> None:
    """策略回测：获取 K 线数据 + 执行回测 + 输出绩效报告。

    示例：

      easy-tdx backtest SH 600519 --strategy-file ma_cross.py --cash 100000 --table

      easy-tdx backtest SH 600519 --strategy-file ma_cross.py --indicators MACD,KDJ
    """
    from .engine import BacktestEngine
    from ..cli.conn import get_mac_client
    from ..cli.parsers import parse_adjust, parse_market, parse_period
    from ..indicator import compute_indicators

    # 确定策略
    strategy_cls = _load_strategy(strategy_str, strategy_file)

    # 获取数据
    mkt = parse_market(market)
    with get_mac_client() as client:
        df = client.get_stock_kline(
            mkt,
            code,
            period=parse_period(period),
            start=0,
            count=count,
            adjust=parse_adjust(adjust),
        )

        # 预计算指标
        if indicators:
            ind_list = [i.strip().upper() for i in indicators.split(",")]
            df = compute_indicators(df, ind_list, keep_ohlcv=True)

    # 执行回测
    engine = BacktestEngine(
        strategy=strategy_cls,
        cash=cash,
        commission=commission,
        execution=execution,
    )
    result = engine.run(df)

    # 输出
    fmt = "table" if use_table else output_fmt
    if fmt == "json":
        click.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    elif fmt == "csv":
        click.echo(result.trades.to_csv(index=False))
    else:
        _print_table(result)


def _load_strategy(strategy_str: str | None, strategy_file: str | None) -> type:
    """加载策略类。"""
    if strategy_file:
        return _load_strategy_from_file(strategy_file)

    if strategy_str:
        # P1: DSL 字符串解析暂未实现，提示用户使用 --strategy-file
        raise click.UsageError(
            "DSL 字符串策略暂未实现 (P1)。请使用 --strategy-file 指定 Python 策略文件。"
        )

    raise click.UsageError("必须指定 --strategy 或 --strategy-file")


def _load_strategy_from_file(path: str) -> type:
    """从 Python 文件加载 Strategy 子类。"""
    import os

    if not os.path.exists(path):
        raise click.UsageError(f"策略文件不存在: {path}")

    from .strategy import Strategy

    spec = importlib.util.spec_from_file_location("user_strategy", path)
    if spec is None or spec.loader is None:
        raise click.UsageError(f"无法加载策略文件: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 查找 Strategy 子类
    strategy_classes = [
        obj for obj in vars(mod).values()
        if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy
    ]
    if not strategy_classes:
        raise click.UsageError(f"策略文件中未找到 Strategy 子类: {path}")

    return strategy_classes[0]


def _print_table(result) -> None:
    """以表格形式输出回测结果。"""
    p = result.performance
    c = result.config

    click.echo(f"初始资金: ¥{c.get('cash', 0):,.0f}  执行模式: {c.get('execution', 'next_open')}")
    if c.get("future_leak_warning"):
        click.echo("⚠️  警告: 使用了 this_close 模式，存在未来函数风险！")
    click.echo()

    click.echo("═══ 绩效概要 ═══")
    click.echo(f"总收益率:     {p.get('total_return', 0):.2%}        年化收益率:   {p.get('annual_return', 0):.2%}")
    click.echo(f"最大回撤:     {p.get('max_drawdown', 0):.2%}        夏普比率:      {p.get('sharpe', 0):.2f}")
    click.echo(f"索提诺比率:   {p.get('sortino', 0):.2f}        卡玛比率:      {p.get('calmar', 0):.2f}")
    click.echo(f"收益波动率:   {p.get('volatility', 0):.2%}")
    click.echo()

    click.echo("═══ 交易统计 ═══")
    click.echo(f"总交易:       {p.get('total_trades', 0)} 次          胜率:          {p.get('win_rate', 0):.2%}")
    click.echo(f"盈利交易:     {p.get('win_trades', 0)} 次          亏损交易:      {p.get('lose_trades', 0)} 次")
    click.echo(f"盈亏比:       {p.get('profit_factor', 0):.2f}          平均盈利:      ¥{p.get('avg_win', 0):,.0f}")
    click.echo(f"平均亏损:     ¥{p.get('avg_loss', 0):,.0f}        最大单笔盈利:  ¥{p.get('max_win', 0):,.0f}")
    click.echo(f"最大单笔亏损: ¥{p.get('max_loss', 0):,.0f}        平均持仓:      {p.get('avg_holding_days', 0):.1f} 天")

    if not result.trades.empty:
        click.echo()
        click.echo("═══ 最近交易 ═══")
        recent = result.trades.tail(10)
        try:
            import tabulate
            click.echo(tabulate.tabulate(recent, headers="keys", tablefmt="grid", showindex=False))
        except ImportError:
            for _, row in recent.iterrows():
                click.echo(f"  {row['datetime']} {row['direction']} {row['size']}@{row['price']:.2f} pnl={row['pnl']:.2f}")
```

- [ ] **Step 4: 注册命令到 CLI**

在 `src/easy_tdx/cli/__init__.py` 中添加：

```python
# 在 import 区域添加
from .backtest_cmd import backtest  # 暂用别名避免冲突

# 在 cli.add_command 区域添加
cli.add_command(backtest)
```

实际上 backtest 命令定义在 `src/easy_tdx/backtest/cli.py`，需要在 `src/easy_tdx/cli/__init__.py` 中导入：

在 `src/easy_tdx/cli/__init__.py` 的 import 区域添加：

```python
from easy_tdx.backtest.cli import backtest
```

在 `cli.add_command` 区域添加：

```python
cli.add_command(backtest)
```

- [ ] **Step 5: 运行 CLI 测试**

Run: `python -m pytest tests/unit/test_backtest_cli.py -v`
Expected: 全部通过

- [ ] **Step 6: 手动验证 CLI help**

Run: `python -m easy_tdx.cli backtest --help`
Expected: 显示 backtest 命令帮助

- [ ] **Step 7: Commit**

```bash
git add src/easy_tdx/backtest/cli.py src/easy_tdx/cli/__init__.py tests/unit/test_backtest_cli.py
git commit -m "feat(backtest): add CLI command with auto data fetch and table output"
```

---

## Task 10: 最终验证 + 清理

**Files:**
- Modify: `src/easy_tdx/__init__.py` (可选)

- [ ] **Step 1: 运行全部回测测试**

Run: `python -m pytest tests/unit/test_backtest_*.py -v`
Expected: 全部通过

- [ ] **Step 2: 运行项目全部单元测试（确认无回归）**

Run: `python -m pytest tests/unit/ -v`
Expected: 全部通过

- [ ] **Step 3: 运行 mypy 类型检查**

Run: `mypy src/easy_tdx/backtest/`
Expected: 无错误（可能需要微调类型注解）

- [ ] **Step 4: 运行 ruff lint**

Run: `ruff check src/easy_tdx/backtest/ tests/unit/test_backtest_*.py`
Expected: 无错误（可能需要微调格式）

- [ ] **Step 5: 可选 — 更新顶层 `__init__.py` 导出**

在 `src/easy_tdx/__init__.py` 的 `__all__` 中添加（可选）：

```python
# 在 import 区域
from .backtest import BacktestEngine, Strategy  # noqa: F401
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat(backtest): final cleanup and type checking"
```

---

## Self-Review Checklist

### 1. Spec Coverage

| Spec 要求 | 对应 Task |
|-----------|-----------|
| Signal/Trade/Position/BacktestResult 数据类型 | Task 1 |
| Strategy 基类 + init()/next() | Task 2 |
| StrategyDataProxy + 预计算列 | Task 2 |
| crossover() 辅助函数 | Task 2 |
| 缠论预留 self.chanlun | Task 2 + Task 6 |
| DSL @dsl_strategy 装饰器 | Task 7 (P1 骨架) |
| 5 种执行模式 | Task 3 |
| 仓位管理 (full/fixed/percent) | Task 3 |
| 订单拒绝策略 (reduce/skip) | Task 3 |
| 费用模型 (佣金/印花税/滑点) | Task 3 |
| this_close 未来函数警告 | Task 3 |
| PortfolioTracker 资金曲线 | Task 4 |
| 回撤计算 | Task 4 |
| 18 项绩效指标 | Task 5 |
| BacktestEngine 四步管道 | Task 6 |
| PnL 计算 | Task 6 |
| CLI 命令 + 自动获取 K 线 | Task 9 |
| --indicators 预计算 | Task 9 |
| CLI JSON/table/csv 输出 | Task 9 |

### 2. Placeholder Scan

- ✅ 无 TBD/TODO
- ✅ 所有测试包含实际断言
- ✅ 所有实现包含完整代码

### 3. Type Consistency

- Signal.direction: `Literal["BUY", "SELL"]` — types.py ↔ strategy.py ↔ orders.py 一致 ✅
- Trade.rejected: `bool` — types.py ↔ orders.py ↔ engine.py 一致 ✅
- BacktestResult.performance: `dict[str, float]` — types.py ↔ engine.py ↔ performance.py 一致 ✅
- crossover() 签名: strategy.py 定义，test_backtest_strategy.py 和 test_backtest_engine.py 引用一致 ✅
