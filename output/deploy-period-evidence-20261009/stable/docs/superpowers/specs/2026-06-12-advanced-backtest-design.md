# 高级回测增强 — 设计文档

> **日期**: 2026-06-12
> **版本**: v1.0
> **前置**: 方案 A（v1.11.0–v1.13.0）已完成
> **范围**: 方案 B — 滑点建模、执行仿真、归因分析
> **目标市场**: 纯 A 股

## 1. 背景与目标

easy-tdx 的回测引擎（`BacktestEngine` + `OrderSimulator`）已支持基础信号→撮合→绩效管道，但成本建模过于简单（固定每股滑点），执行假设过于理想（瞬间成交），且无收益归因能力。

本设计在**不破坏现有 API** 的前提下，新增三个核心能力：

1. **可插拔滑点模型** — 从固定滑点升级为市场冲击模型（方根模型、成交量比例等）
2. **执行仿真引擎** — 支持大额订单拆分（TWAP/VWAP）、限价单等真实执行方式
3. **归因分析** — Brinson 归因（配置 vs 选股）、因子归因（收益分解为因子贡献）

## 2. 模块总览

```
src/easy_tdx/backtest/
├── slippage.py       # 新增：可插拔滑点模型（4 种）
├── execution.py      # 新增：执行仿真引擎（4 种）
├── attribution.py    # 新增：归因分析（Brinson + 因子 + 成本）
├── engine.py         # 修改：接入 slippage_model / execution_model
├── orders.py         # 修改：用 SlippageModel 替代固定滑点
├── performance.py    # 不变
├── strategy.py       # 不变
├── types.py          # 修改：新增 AttributionReport
├── portfolio.py      # 不变
├── portfolio_engine.py  # 不变
└── combo.py          # 不变
```

### 依赖关系

```
Signal → ExecutionModel → SlippageModel → Trade
                                         ↓
                              AttributionAnalyzer → AttributionReport
```

## 3. 滑点建模（`slippage.py`）

### 3.1 基类

```python
class SlippageModel(ABC):
    """滑点模型基类。"""

    @abstractmethod
    def compute(
        self,
        price: float,
        size: float,
        volume: float,
        volatility: float,
        direction: str,
    ) -> float:
        """返回总滑点成本（金额）。

        Args:
            price: 成交价
            size: 订单数量（股）
            volume: 当日成交量（股），0 表示无数据
            volatility: 近期年化波动率，0 表示无数据
            direction: BUY / SELL
        """
        ...
```

### 3.2 四种内置模型

| 模型 | 公式 | 适用场景 |
|------|------|---------|
| `FixedSlippage(per_share=0.01)` | `size × per_share` | 向后兼容，快速原型 |
| `PercentSlippage(rate=0.001)` | `price × size × rate` | 按成交金额百分比 |
| `SquareRootSlippage(impact_coeff=0.1)` | `σ × √(Q/V) × price × Q × coeff` | A 股量化主流，参与率高时冲击大 |
| `VolumeSlippage(base_bps=10.0)` | `base_bps/10000 × (size/volume) × price × size` | 基于成交量比例，流动性差时成本高 |

### 3.3 SquareRootSlippage 详解

```
participation_rate = size / volume        # 参与率
impact = volatility × √(participation_rate) × price × size × impact_coeff
```

- 当 `volume=0` 或 `volatility=0` 时，退化为 `PercentSlippage(rate=0.001)`
- `impact_coeff` 默认 0.1，对应 A 股中小盘股的经验值
- 参与率 > 5% 时冲击成本显著增大（√ 函数的自然效果）

### 3.4 集成点

`OrderSimulator` 新增参数：

```python
slippage_model: SlippageModel | None = None
```

当 `slippage_model` 非空时，忽略原有 `self.slippage` 参数，调用 `slippage_model.compute()` 计算滑点。

`BacktestEngine` 透传：

```python
BacktestEngine(strategy, slippage_model=SquareRootSlippage())
```

当同时提供 `slippage_model` 和 `slippage` 时，`slippage_model` 优先。

## 4. 执行仿真（`execution.py`）

### 4.1 基类

```python
class ExecutionModel(ABC):
    """执行仿真基类。"""

    @abstractmethod
    def execute(
        self,
        signal: Signal,
        df: pd.DataFrame,
        bar_idx: int,
        cash: float,
        position: float,
        position_mode: str,
        commission: float,
        min_commission: float,
        stamp_tax: float,
        slippage_model: SlippageModel | None,
    ) -> list[Trade]:
        """将信号转换为一笔或多笔成交记录。"""
        ...
```

### 4.2 四种内置模型

| 模型 | 行为 | 适用场景 |
|------|------|---------|
| `ImmediateExecution` | 现有行为，下一 bar 即时成交 | 向后兼容 |
| `TWAPExecution(n_bars=5)` | 将订单均匀拆分为 N 份，在连续 N bar 执行 | 大额订单分批建仓 |
| `VWAPExecution(n_bars=5, volume_lookback=20)` | 按历史成交量分布比例拆分 | 追踪 VWAP 基准 |
| `LimitExecution(ttl_bars=5)` | 限价挂单，仅当价格触及才成交 | 精确入场价位控制 |

### 4.3 TWAPExecution 详解

```python
class TWAPExecution(ExecutionModel):
    def __init__(self, n_bars: int = 5) -> None:
        self.n_bars = n_bars

    def execute(self, signal, df, bar_idx, ...):
        sub_size = total_size / n_bars
        trades = []
        for i in range(n_bars):
            exec_bar = bar_idx + 1 + i
            if exec_bar >= len(df):
                break  # 超出数据范围，剩余未执行
            price = df["close"].iloc[exec_bar]  # 按 close 执行
            trade = self._make_trade(signal, sub_size, price, exec_bar, ...)
            trades.append(trade)
        return trades
```

- 买入时使用 `position_mode` 确定总数量，然后均匀拆分
- 卖出时直接拆分持仓
- 每笔子交易独立计算佣金和滑点
- 100 股整手约束：每笔子交易向下取整到 100 的倍数

### 4.4 VWAPExecution 详解

```python
class VWAPExecution(ExecutionModel):
    def __init__(self, n_bars: int = 5, volume_lookback: int = 20) -> None: ...

    def execute(self, signal, df, bar_idx, ...):
        # 取最近 volume_lookback 根 K 线的成交量分布
        lookback = df.iloc[max(0, bar_idx - volume_lookback):bar_idx + 1]
        avg_volumes = []
        for i in range(n_bars):
            offset = i % len(lookback)
            avg_volumes.append(float(lookback["volume"].iloc[-(offset + 1)]))
        total_vol = sum(avg_volumes)
        weights = [v / total_vol for v in avg_volumes]
        # 按 weights 拆分订单
        ...
```

### 4.5 LimitExecution 详解

```python
class LimitExecution(ExecutionModel):
    def __init__(self, ttl_bars: int = 5) -> None:
        self.ttl_bars = ttl_bars  # 限价单有效期（bar 数）

    def execute(self, signal, df, bar_idx, ...):
        if signal.price is None:
            # 无限价，退化为即时执行
            return ImmediateExecution().execute(...)
        target_price = signal.price
        trades = []
        for i in range(self.ttl_bars):
            exec_bar = bar_idx + 1 + i
            if exec_bar >= len(df):
                break
            row = df.iloc[exec_bar]
            if signal.direction == "BUY" and row["low"] <= target_price:
                trades.append(self._make_trade(signal, size, target_price, exec_bar, ...))
                break
            elif signal.direction == "SELL" and row["high"] >= target_price:
                trades.append(self._make_trade(signal, size, target_price, exec_bar, ...))
                break
        return trades  # 可能返回空列表（限价未触发）
```

### 4.6 集成点

`BacktestEngine` 新增参数：

```python
execution_model: ExecutionModel | None = None
```

当 `execution_model` 非空时，信号处理从执行模型走，不走原有 `_resolve_exec_index` / `_get_price`。

**关键：执行模型产生多笔 Trade，需要修正 `BacktestEngine._generate_signals` 的信号循环逻辑**。

现有逻辑：

```python
for signal in signals:
    trades = simulator.simulate([signal], cash, position)
```

新逻辑（当 execution_model 存在时）：

```python
for signal in signals:
    sub_trades = execution_model.execute(signal, df, bar_idx, cash, position, ...)
    all_trades.extend(sub_trades)
```

## 5. 归因分析（`attribution.py`）

### 5.1 数据结构

```python
@dataclass
class AttributionReport:
    """归因分析报告。"""
    # 总收益
    total_return: float
    # Brinson 归因
    allocation_return: float
    selection_return: float
    interaction_return: float
    # 因子归因
    factor_returns: dict[str, float]
    specific_return: float
    # 成本归因
    total_trade_cost: float
    slippage_cost: float
    commission_cost: float
    stamp_tax_cost: float
```

### 5.2 AttributionAnalyzer

```python
class AttributionAnalyzer:
    """收益归因分析器。"""

    def __init__(
        self,
        trades: pd.DataFrame,
        equity_curve: pd.DataFrame,
        benchmark: pd.DataFrame | None = None,
        factor_exposures: pd.DataFrame | None = None,
        factor_returns: pd.DataFrame | None = None,
        groups: pd.DataFrame | None = None,
    ) -> None: ...

    def brinson_attribution(self) -> AttributionReport:
        """Brinson-Hood-Beebower 归因分解。

        Total = Allocation + Selection + Interaction
        R_p = Σ(w_pi × R_pi)   # 组合收益
        R_b = Σ(w_bi × R_bi)   # 基准收益
        Allocation = Σ((w_pi - w_bi) × R_bi)
        Selection = Σ(w_bi × (R_pi - R_bi))
        Interaction = Σ((w_pi - w_bi) × (R_pi - R_bi))
        """

    def factor_attribution(self) -> AttributionReport:
        """因子归因分解。

        R = Σ(β_i × f_i) + α
        β_i: 因子暴露度
        f_i: 因子收益率
        α: 特质收益
        """

    def cost_attribution(self) -> AttributionReport:
        """成本归因：分解佣金/滑点/印花税。"""

    def full_report(self) -> AttributionReport:
        """完整归因报告。"""
```

### 5.3 与现有模块衔接

- `trades` 参数直接来自 `BacktestResult.trades`
- `equity_curve` 来自 `BacktestResult.equity_curve`
- `factor_exposures` / `factor_returns` 来自 `FactorEngine`（v1.11.0 已实现）
- `groups` 可用于 Brinson 分组（如行业分类），可选

## 6. 向后兼容策略

| 现有调用 | 行为 |
|---------|------|
| `BacktestEngine(strategy, slippage=0.01)` | 与现有行为完全一致 |
| `BacktestEngine(strategy)` | 无滑点，与现有行为一致 |
| `BacktestEngine(strategy, slippage_model=SquareRootSlippage())` | 使用新滑点模型 |
| `BacktestEngine(strategy, execution_model=TWAPExecution())` | 使用新执行引擎 |
| `OrderSimulator(df, slippage=0.01)` | 与现有行为完全一致 |
| `OrderSimulator(df, slippage_model=FixedSlippage(0.01))` | 等价 |

**不变更的文件**: `strategy.py`, `performance.py`, `portfolio.py`, `combo.py`

## 7. 版本计划

### v1.14.0 — 滑点 + 执行

- `slippage.py`: SlippageModel ABC + 4 种模型
- `execution.py`: ExecutionModel ABC + 4 种模型
- `orders.py`: 集成 SlippageModel
- `engine.py`: 集成 SlippageModel + ExecutionModel
- `types.py`: 无变更（Trade/Signal 已够用）
- 测试: ~35 个

### v1.15.0 — 归因分析

- `attribution.py`: AttributionAnalyzer + AttributionReport
- `types.py`: 新增 AttributionReport
- `performance.py`: 可选集成 AttributionAnalyzer
- CLI: `easy-tdx backtest attribution` 命令
- 测试: ~20 个

## 8. 不做的事

- **订单簿仿真**：A 股 Level-2 数据获取困难，回测中用成交量比例代理
- **融资融券**：需要额外保证金模型，超出当前范围
- **期指/期权对冲**：超出纯 A 股范围
- **高频仿真**：当前是日线级别回测，微秒级仿真不适用
