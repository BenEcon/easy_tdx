# 量化因子与组合管理 — 使用指南

> 本文档覆盖 easy-tdx v1.11.1 新增的量化计算能力：因子研究、因子分析、组合管理、高级回测（滑点建模/执行仿真/归因分析）。

---

## 目录

- [1. 因子引擎](#1-因子引擎)
  - [1.1 内置因子一览](#11-内置因子一览)
  - [1.2 单股多因子计算](#12-单股多因子计算)
  - [1.3 截面因子计算](#13-截面因子计算)
  - [1.4 远期收益计算](#14-远期收益计算)
  - [1.5 自定义因子](#15-自定义因子)
- [2. 因子预处理](#2-因子预处理)
- [3. 因子分析](#3-因子分析)
- [4. 组合管理](#4-组合管理)
  - [4.1 权重优化器](#41-权重优化器)
  - [4.2 风险模型](#42-风险模型)
  - [4.3 再平衡引擎](#43-再平衡引擎)
- [5. 高级回测](#5-高级回测)
  - [5.1 滑点模型](#51-滑点模型)
  - [5.2 执行仿真](#52-执行仿真)
  - [5.3 归因分析](#53-归因分析)
- [6. CLI 命令](#6-cli-命令)
- [7. 完整工作流示例](#7-完整工作流示例)

---

## 1. 因子引擎

因子引擎（`FactorEngine`）支持单股和多股截面两种计算模式，内置 19 个因子。

### 1.1 内置因子一览

| 类别 | 因子名 | 说明 |
|------|--------|------|
| **动量** | `momentum_20d` | 20 日收益率 |
| | `momentum_60d` | 60 日收益率 |
| | `reversal_5d` | 5 日反转（负收益） |
| **波动率** | `volatility_20d` | 20 日年化波动率 |
| | `atr_14d` | 14 日平均真实波幅 |
| | `turnover_rate` | 换手率（需 vol 列） |
| **质量** | `sharpe_20d` | 20 日夏普比率 |
| | `max_drawdown_20d` | 20 日最大回撤 |
| | `win_rate_20d` | 20 日上涨天数占比 |
| **成交量** | `obv_trend` | OBV 趋势斜率 |
| | `vol_surge` | 成交量突增倍数 |
| | `amount_ma_ratio` | 成交额 / MA5 比值 |
| **技术** | `macd_hist_signal` | MACD 柱状信号 |
| | `rsi_14` | 14 日 RSI |
| | `boll_position` | 布林带位置（0~1） |
| **缠论** | `chanlun_bi_dir` | 当前笔方向（+1/-1） |
| | `chanlun_mmd` | 最近买卖点（+2/+1/-1/-2） |
| **价值** | `pe_ratio` | 市盈率（占位，返回 NaN） |
| | `pb_ratio` | 市净率（占位，返回 NaN） |

### 1.2 单股多因子计算

```python
from easy_tdx import TdxClient
from easy_tdx.factor import FactorEngine

client = TdxClient()
df = client.get_security_bars(Market.SH, "600519", KlineCategory.DAY, 0, 300)

engine = FactorEngine()

# 计算多个因子
result = engine.compute_single(df, ["momentum_20d", "volatility_20d", "rsi_14"])
print(result.tail())

# 计算所有内置因子
result = engine.compute_single(df)  # 不传因子名 = 全部
print(result.columns.tolist())
```

输出 DataFrame 在原始列基础上追加因子列（以因子名命名，前缀 `NaN` 行因窗口不足为 `NaN`）。

### 1.3 截面因子计算

```python
from easy_tdx import TdxClient
from easy_tdx.factor import FactorEngine

client = TdxClient()

# 准备多只股票数据
stock_pool = ["000001", "000858", "600519", "600036", "601318"]
data = {}
for code in stock_pool:
    market = Market.SH if code.startswith("6") else Market.SZ
    data[code] = client.get_security_bars(market, code, KlineCategory.DAY, 0, 300)

engine = FactorEngine()

# 截面计算：返回 long format（date, code, factor_name...）
factor_data = engine.compute_cross_section(
    data,
    ["momentum_20d", "volatility_20d", "rsi_14"],
)
print(factor_data.head(10))

# 指定日期：只计算某一天的截面
factor_data = engine.compute_cross_section(
    data, ["momentum_20d"], date=20240601,
)
```

### 1.4 远期收益计算

```python
# 计算未来 5 日收益率（用于因子分析）
forward_returns = engine.compute_forward_returns(data, period=5)
print(forward_returns.head())
```

### 1.5 自定义因子

继承 `Factor` 基类，用 `@register_factor` 注册即可自动发现：

```python
from easy_tdx.factor import Factor, register_factor

@register_factor
class MyMomentum(Factor):
    name = "my_momentum"
    description = "自定义动量因子"
    window = 20

    def compute(self, df):
        return df["close"].pct_change(self.window)
```

注册后直接用名字引用：

```python
result = engine.compute_single(df, ["my_momentum"])
```

---

## 2. 因子预处理

6 个纯函数，组合成管道：

```python
from easy_tdx.factor import preprocess

# 单因子预处理管道
clean = preprocess(
    factor_data,
    factor_names=["momentum_20d"],
    steps=["winsorize", "zscore", "fill_missing"],
)
```

| 函数 | 说明 |
|------|------|
| `winsorize(df, factor_names, n_sigma=3)` | MAD 去极值 |
| `zscore(df, factor_names)` | 截面标准化 |
| `rank_normalize(df, factor_names)` | 排名归一化 |
| `fill_missing(df, factor_names)` | 填充缺失值 |
| `orthogonalize(df, factor_names, by="market_cap")` | 正交化（去除市值暴露） |
| `preprocess(df, factor_names, steps)` | 组合管道 |

所有函数自动检测截面数据（有 `date` 列时按日期分组处理）。

---

## 3. 因子分析

```python
from easy_tdx.factor import FactorEngine, FactorAnalyzer, preprocess

# 1. 计算截面因子
factor_data = engine.compute_cross_section(data, ["momentum_20d", "rsi_14"])

# 2. 预处理
clean = preprocess(factor_data, ["momentum_20d", "rsi_14"])

# 3. 计算远期收益
forward_returns = engine.compute_forward_returns(data, period=5)

# 4. 分析
analyzer = FactorAnalyzer(clean, forward_returns)

# IC 分析（Spearman 秩相关）
ic_series = analyzer.compute_ic("momentum_20d")
print(f"均值 IC: {ic_series.mean():.4f}, ICIR: {ic_series.mean()/ic_series.std():.4f}")

# 分层收益（5 组）
quantile_returns = analyzer.compute_quantile_returns("momentum_20d", n_groups=5)
print(quantile_returns.head())

# 因子衰减（IC 自相关）
decay = analyzer.compute_decay("momentum_20d", max_lag=10)
print(decay)

# 完整报告
report = analyzer.full_report("momentum_20d")
print(f"IC均值={report.mean_ic:.4f} ICIR={report.icir:.4f}")
print(f"多头年化={report.long_only_annual:.2%} 空头年化={report.short_only_annual:.2%}")
print(f"多空夏普={report.long_short_sharpe:.4f} 换手率={report.turnover:.4f}")
```

---

## 4. 组合管理

### 4.1 权重优化器

4 种内置优化器：

```python
from easy_tdx.portfolio import (
    EqualWeightOptimizer,
    FactorWeightedOptimizer,
    RiskParityOptimizer,
    MeanVarianceOptimizer,
)
import pandas as pd

# 因子分数表（来自 FactorEngine）
scores_df = pd.DataFrame({
    "code": ["000001", "600519", "601318", "000858", "600036"],
    "score": [0.8, 0.6, 0.5, 0.3, 0.1],
})

# 1. 等权：选前 N 只，等权分配
opt1 = EqualWeightOptimizer()
weights1 = opt1.optimize(scores_df, n_stocks=3)
# {'000001': 0.333, '600519': 0.333, '601318': 0.333}

# 2. 因子加权：分数越高权重越大
opt2 = FactorWeightedOptimizer()
weights2 = opt2.optimize(scores_df, n_stocks=3)
# {'000001': 0.42, '600519': 0.32, '601318': 0.26}

# 3. 风险平价：按波动率倒数加权
returns_df = pd.DataFrame(...)  # 收益率矩阵
opt3 = RiskParityOptimizer(returns_df)
weights3 = opt3.optimize(scores_df, n_stocks=3)

# 4. 均值方差：scipy SLSQP 优化（无 scipy 退化为等权）
opt4 = MeanVarianceOptimizer(returns_df)
weights4 = opt4.optimize(scores_df, n_stocks=3)
```

### 4.2 风险模型

```python
from easy_tdx.portfolio import RiskModel
import pandas as pd

risk = RiskModel()

# 估计协方差矩阵（Ledoit-Wolf 收缩）
returns = pd.DataFrame(...)  # N 只股票 × T 天收益率
cov = risk.estimate_covariance(returns, method="shrinkage", window=60)

# 组合风险分解
weights = {"000001": 0.3, "600519": 0.4, "601318": 0.3}
metrics = risk.portfolio_risk(weights, cov)
print(f"年化波动率: {metrics['total_volatility']:.2%}")
print(f"最大风险贡献: {metrics['max_risk_contribution']:.2%}")
print(f"持仓数: {metrics['n_positions']}")
```

### 4.3 再平衡引擎

```python
from easy_tdx.portfolio import RebalanceEngine, FactorWeightedOptimizer
from easy_tdx import TdxClient

client = TdxClient()
stock_pool = ["000001", "000858", "600519", "600036", "601318"]
data = {c: client.get_security_bars(..., c, ...) for c in stock_pool}

# 创建引擎
engine = RebalanceEngine(
    optimizer=FactorWeightedOptimizer(),
    factor_name="momentum_20d",   # 用哪个因子选股
    n_stocks=3,                   # 持仓数量
    rebalance_freq="M",           # 调仓频率: W/M/Q
    commission=0.0003,            # 佣金率
    slippage=0.001,               # 滑点率
    cash=1_000_000,               # 初始资金
)

# 运行回测
result = engine.run(data, start_date=20230101, end_date=20240101)

# 结果
print(f"总收益: {result.performance['total_return']:.2%}")
print(f"年化: {result.performance['annual_return']:.2%}")
print(f"最大回撤: {result.performance['max_drawdown']:.2%}")
print(f"夏普: {result.performance['sharpe']:.4f}")
print(f"调仓次数: {len(result.rebalance_dates)}")
print(f"交易笔数: {len(result.trades)}")

# 权益曲线
print(result.equity_curve.head())

# 持仓历史
for state in result.states[-5:]:
    print(f"  {state.date}: 持仓{state.positions_count}只 净值{state.total_value:.0f}")
```

---

## 5. 高级回测

### 5.1 滑点模型

4 种可插拔滑点模型，替代原有固定滑点：

```python
from easy_tdx.backtest import BacktestEngine
from easy_tdx.backtest.slippage import (
    FixedSlippage,
    PercentSlippage,
    SquareRootSlippage,
    VolumeSlippage,
)

# 1. 固定每股滑点（与旧行为一致）
model1 = FixedSlippage(per_share=0.01)

# 2. 按金额百分比
model2 = PercentSlippage(rate=0.001)

# 3. 方根市场冲击模型（Almgren-Chriss 简化版）
#    impact = sigma * sqrt(participation_rate) * price * size * coeff
#    A 股量化主流：参与率 >5% 时冲击显著
model3 = SquareRootSlippage(impact_coeff=0.1)

# 4. 成交量比例滑点
model4 = VolumeSlippage(base_bps=10.0)

# 在 BacktestEngine 中使用
engine = BacktestEngine(
    MyStrategy,
    cash=1_000_000,
    slippage_model=SquareRootSlippage(impact_coeff=0.1),
)
result = engine.run(df)
```

**模型选择建议**：

| 场景 | 推荐模型 | 参数 |
|------|---------|------|
| 快速原型 | `FixedSlippage` | `per_share=0.01` |
| 中频策略 | `PercentSlippage` | `rate=0.001` |
| 大额订单 | `SquareRootSlippage` | `impact_coeff=0.1` |
| 低流动性股票 | `VolumeSlippage` | `base_bps=10.0` |

### 5.2 执行仿真

4 种执行模型，将单笔信号拆分为多笔子交易：

```python
from easy_tdx.backtest.execution import (
    ImmediateExecution,
    TWAPExecution,
    VWAPExecution,
    LimitExecution,
)

# 1. 即时成交（默认，与旧行为一致）
exec1 = ImmediateExecution()

# 2. TWAP：时间加权平均价格，N 根 K 线均匀拆单
exec2 = TWAPExecution(n_bars=5)

# 3. VWAP：成交量加权平均价格，按历史量分布拆单
exec3 = VWAPExecution(n_bars=5, volume_lookback=20)

# 4. 限价单：目标价挂单，TTL 内未触发则放弃
exec4 = LimitExecution(ttl_bars=5)

# 在 BacktestEngine 中使用
engine = BacktestEngine(
    MyStrategy,
    cash=1_000_000,
    execution_model=TWAPExecution(n_bars=3),
    slippage_model=SquareRootSlippage(),
)
result = engine.run(df)
```

**执行模型选择**：

| 场景 | 推荐模型 | 参数 |
|------|---------|------|
| 小额/快速验证 | `ImmediateExecution` | 默认 |
| 大额建仓/平仓 | `TWAPExecution` | `n_bars=3~5` |
| 追踪 VWAP 基准 | `VWAPExecution` | `n_bars=5` |
| 精确入场价位 | `LimitExecution` | `ttl_bars=5` |

**TWAP vs VWAP 示例**：

```python
# TWAP: 300 股拆成 3 笔 100 股，在 bar 1/2/3 以 close 执行
engine = BacktestEngine(
    MyStrategy, cash=100_000,
    execution_model=TWAPExecution(n_bars=3),
)

# VWAP: 按成交量分布拆 300 股 — 成交量大的 bar 分配更多
engine = BacktestEngine(
    MyStrategy, cash=100_000,
    execution_model=VWAPExecution(n_bars=3, volume_lookback=20),
)

# 限价单：在 50 元挂买入，5 根 K 线内 low <= 50 才成交
class LimitBuyStrategy(Strategy):
    def init(self): pass
    def next(self):
        if self._bar_index == 0:
            self.buy(size=100, price=50.0)  # 指定限价

engine = BacktestEngine(
    LimitBuyStrategy, cash=100_000,
    execution_model=LimitExecution(ttl_bars=5),
)
```

### 5.3 归因分析

从回测结果生成归因报告：

```python
from easy_tdx.backtest import BacktestEngine
from easy_tdx.backtest.attribution import AttributionAnalyzer

# 运行回测
engine = BacktestEngine(MyStrategy, cash=1_000_000)
result = engine.run(df)

# --- 成本归因 ---
analyzer = AttributionAnalyzer(result.trades, result.equity_curve)
cost_report = analyzer.cost_attribution()
print(f"总收益: {cost_report.total_return:.2%}")
print(f"总交易成本: {cost_report.total_trade_cost:.0f} 元")
print(f"  佣金: {cost_report.commission_cost:.0f}")
print(f"  滑点: {cost_report.slippage_cost:.0f}")
print(f"  印花税: {cost_report.stamp_tax_cost:.0f}")

# --- Brinson 归因（需要基准）---
import numpy as np
import pandas as pd
# 构造基准曲线（如沪深300）
benchmark = pd.DataFrame({
    "datetime": result.equity_curve["datetime"],
    "total": np.linspace(100000, 108000, len(result.equity_curve)),
})
analyzer = AttributionAnalyzer(result.trades, result.equity_curve, benchmark=benchmark)
brinson_report = analyzer.brinson_attribution()
print(f"配置贡献: {brinson_report.allocation_return:.2%}")
print(f"选股贡献: {brinson_report.selection_return:.2%}")
print(f"交叉效应: {brinson_report.interaction_return:.2%}")

# --- 因子归因（需要因子数据）---
exposures = pd.DataFrame({"momentum": [0.5, 0.3, 0.2], "quality": [0.1, -0.1, 0.0]})
returns = pd.DataFrame({"momentum": [0.05, 0.03, 0.02], "quality": [0.01, -0.02, 0.0]})
analyzer = AttributionAnalyzer(
    result.trades, result.equity_curve,
    factor_exposures=exposures, factor_returns=returns,
)
factor_report = analyzer.factor_attribution()
for name, ret in factor_report.factor_returns.items():
    print(f"  {name}: {ret:.4f}")
print(f"特质收益: {factor_report.specific_return:.4f}")

# --- 完整报告（自动选择最佳归因模式）---
full_report = analyzer.full_report()
```

**归因模式优先级**：因子归因 > Brinson 归因 > 成本归因。`full_report()` 自动选择数据最完整的模式。

---

## 6. CLI 命令

```bash
# 列出所有内置因子
easy-tdx factor list --table

# 因子分析（需要数据，输出示例代码）
easy-tdx factor analyze momentum_20d

# 组合因子回测（需要数据，输出示例代码）
easy-tdx pfactor backtest momentum_20d --n-stocks 10 --optimizer factor_weighted
```

CLI 命令输出 Python API 示例代码，方便复制使用。完整的因子计算和组合回测建议通过 Python API 完成。

---

## 7. 完整工作流示例

从数据获取到组合回测再到归因分析的完整管道：

```python
"""
easy-tdx 量化研究完整工作流示例。

依赖: pip install easy-tdx
"""

from easy_tdx import TdxClient, Market, KlineCategory
from easy_tdx.factor import FactorEngine, FactorAnalyzer, preprocess
from easy_tdx.portfolio import RebalanceEngine, FactorWeightedOptimizer
from easy_tdx.backtest import BacktestEngine
from easy_tdx.backtest.slippage import SquareRootSlippage
from easy_tdx.backtest.execution import TWAPExecution
from easy_tdx.backtest.attribution import AttributionAnalyzer

# ── 1. 数据获取 ──────────────────────────────────────
client = TdxClient()
stock_pool = ["000001", "000858", "600519", "600036", "601318",
              "000333", "002415", "601012", "600276", "000568"]

data = {}
for code in stock_pool:
    market = Market.SH if code.startswith("6") else Market.SZ
    data[code] = client.get_security_bars(
        market, code, KlineCategory.DAY, 0, 500
    )
print(f"获取 {len(data)} 只股票数据")

# ── 2. 因子计算 ──────────────────────────────────────
engine = FactorEngine()
factor_data = engine.compute_cross_section(
    data, ["momentum_20d", "volatility_20d", "rsi_14"]
)
print(f"截面因子数据: {len(factor_data)} 行")

# ── 3. 因子预处理 ─────────────────────────────────────
clean = preprocess(
    factor_data,
    factor_names=["momentum_20d", "volatility_20d", "rsi_14"],
    steps=["winsorize", "zscore", "fill_missing"],
)

# ── 4. 因子分析 ──────────────────────────────────────
forward_returns = engine.compute_forward_returns(data, period=5)

for factor_name in ["momentum_20d", "volatility_20d", "rsi_14"]:
    analyzer = FactorAnalyzer(clean, forward_returns)
    report = analyzer.full_report(factor_name)
    print(f"\n── {factor_name} ──")
    print(f"  IC均值: {report.mean_ic:.4f}  ICIR: {report.icir:.4f}")
    print(f"  多头年化: {report.long_only_annual:.2%}")
    print(f"  多空夏普: {report.long_short_sharpe:.4f}")

# ── 5. 组合回测 ──────────────────────────────────────
rebalancer = RebalanceEngine(
    optimizer=FactorWeightedOptimizer(),
    factor_name="momentum_20d",
    n_stocks=5,
    rebalance_freq="M",
    cash=1_000_000,
)
result = rebalancer.run(data, start_date=20230101, end_date=20240101)
print(f"\n── 组合回测 ──")
print(f"  总收益: {result.performance['total_return']:.2%}")
print(f"  年化: {result.performance['annual_return']:.2%}")
print(f"  最大回撤: {result.performance['max_drawdown']:.2%}")
print(f"  夏普: {result.performance['sharpe']:.4f}")

# ── 6. 高级单策略回测（滑点 + 执行仿真）──────
from easy_tdx.backtest import Strategy

class MomentumStrategy(Strategy):
    def init(self):
        pass
    def next(self):
        if self._bar_index < 20:
            return
        ret = (self.data.close[0] - self.data.close[-20]) / self.data.close[-20]
        if ret > 0.05 and self.position["size"] == 0:
            self.buy(size=0)
        elif ret < -0.03 and self.position["size"] > 0:
            self.sell(size=0)

bt_engine = BacktestEngine(
    MomentumStrategy,
    cash=500_000,
    slippage_model=SquareRootSlippage(impact_coeff=0.1),
    execution_model=TWAPExecution(n_bars=3),
)
# 选一只股票做回测
bt_result = bt_engine.run(data["600519"])
print(f"\n── 高级回测（600519）──")
print(f"  总收益: {bt_result.performance['total_return']:.2%}")
print(f"  夏普: {bt_result.performance['sharpe']:.4f}")

# ── 7. 归因分析 ──────────────────────────────────────
att_analyzer = AttributionAnalyzer(bt_result.trades, bt_result.equity_curve)
cost_report = att_analyzer.cost_attribution()
print(f"\n── 成本归因 ──")
print(f"  总交易成本: {cost_report.total_trade_cost:.0f} 元")
print(f"    佣金: {cost_report.commission_cost:.0f}")
print(f"    滑点: {cost_report.slippage_cost:.0f}")
print(f"    印花税: {cost_report.stamp_tax_cost:.0f}")

print("\n完成。")
client.close()
```

---

## 向后兼容

所有新功能通过可选参数启用，**现有代码零改动**：

| 现有调用 | 行为 |
|---------|------|
| `BacktestEngine(strategy, slippage=0.01)` | 与旧版完全一致 |
| `BacktestEngine(strategy)` | 无滑点，与旧版一致 |
| `OrderSimulator(df, slippage=0.01)` | 与旧版完全一致 |
| `BacktestEngine(strategy, slippage_model=...)` | 使用新滑点模型 |
| `BacktestEngine(strategy, execution_model=...)` | 使用新执行引擎 |

新增模块（`factor/`, `portfolio/`, `backtest/slippage.py`, `backtest/execution.py`, `backtest/attribution.py`）为独立新增，不修改任何现有接口。
