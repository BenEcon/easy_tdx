# 量化因子引擎 + 组合管理 — 设计文档

> **日期**: 2026-06-12
> **版本**: v1.0
> **范围**: 方案 A（因子引擎优先），后续接方案 B（高级回测增强）
> **目标市场**: 纯 A 股（主板 + 创业板 + 科创板）

## 1. 背景与目标

easy-tdx 已具备完整的市场数据接入、32+ 技术指标、缠论分析、向量回测引擎和离线扫描能力。本设计在现有基础上新增 **因子研究基础设施** 和 **组合管理系统**，补齐从「策略想法」到「组合执行」的关键链路。

**核心目标**：

- 让任何人写一个 Python 类就能产出可注册、可分析、可组合的因子
- 提供因子有效性评估的完整分析管道（IC / 分层 / 衰减）
- 支持从因子信号到组合权重的闭环（优化器 → 再平衡 → 绩效）

## 2. 模块总览

```
src/easy_tdx/
├── factor/                    # 新增：因子研究与因子库
│   ├── __init__.py           # 公开 API
│   ├── base.py               # Factor 基类、注册表
│   ├── engine.py             # FactorEngine（单股 + 截面批量计算）
│   ├── analysis.py           # FactorAnalyzer（IC/分层/衰减分析）
│   ├── transform.py          # 预处理（去极值/标准化/正交化）
│   └── builtin/              # 内置因子（6 大类 15-20 个）
│       ├── __init__.py       # 自动导入触发注册
│       ├── momentum.py       # 动量类
│       ├── volatility.py     # 波动率类
│       ├── quality.py        # 质量类
│       ├── volume.py         # 成交量类
│       ├── technical.py      # 技术指标因子（桥接 MyTT）
│       ├── chanlun.py        # 缠论因子（桥接 chanlun 模块）
│       └── value.py          # 价值因子（可选，依赖财务数据）
├── portfolio/                 # 新增：组合管理
│   ├── __init__.py           # 公开 API
│   ├── optimizer.py          # 权重优化器（等权/因子加权/风险平价/均值方差）
│   ├── risk.py               # 风险模型（协方差估计/组合风险分解）
│   ├── rebalance.py          # 再平衡引擎（多期调仓回测）
│   └── types.py              # PortfolioState / RebalanceResult
```

### 依赖关系

```
MyTT 指标库 ──┐                    （已有）
chanlun 模块 ─┤
              ▼ 桥接
        factor/base ─── factor/engine
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
builtin/  transform   analysis
    │         │          │
    └─────────┼──────────┘
              ▼
        portfolio/
              │
              ▼
        backtest/（方案 B，后续增强）
```

## 3. 因子引擎（factor/）

### 3.1 核心抽象层（factor/base.py）

```python
class Factor(ABC):
    """因子基类 — 所有因子的抽象契约。"""

    name: str                    # 唯一标识，如 "momentum_20d"
    category: str                # 分类：momentum / value / quality / volatility / technical / chanlun
    description: str             # 人类可读描述
    inputs: tuple[str, ...]      # 需要的列：("close", "vol") 等

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """接收 OHLCV DataFrame，返回因子值序列（与 df 等长）。"""
        ...
```

**注册机制**（与 `indicator.py` 的 `_REGISTRY` 模式一致）：

```python
FACTORY_REGISTRY: dict[str, type[Factor]] = {}

def register_factor(cls: type[Factor]) -> type[Factor]:
    """类装饰器，自动注册到全局表。"""
    FACTORY_REGISTRY[cls.name] = cls
    return cls
```

**用户自定义因子**：

```python
@register_factor
class MyMomentum(Factor):
    name = "my_momentum"
    category = "momentum"
    description = "自定义动量因子"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change(10)
```

### 3.2 因子计算引擎（factor/engine.py）

```python
class FactorEngine:
    """批量因子计算引擎。"""

    def compute_single(
        self,
        df: pd.DataFrame,
        factors: list[str | Factor],
    ) -> pd.DataFrame:
        """单股票多因子计算 → 返回原 DataFrame + 因子列。"""
        ...

    def compute_cross_section(
        self,
        data: dict[str, pd.DataFrame],    # {code: ohlcv}
        factors: list[str | Factor],
        date: int | None = None,          # None = 最新日期
    ) -> pd.DataFrame:
        """多股票截面计算 → 返回长格式 DataFrame。

        输出 columns=[date, code, factor_1, factor_2, ...]。
        与 FactorAnalyzer 和 preprocess() 的输入格式完全对齐。
        """
        ...

    def compute_forward_returns(
        self,
        data: dict[str, pd.DataFrame],
        period: int = 5,
    ) -> pd.DataFrame:
        """计算远期收益率 → 返回 columns=[date, code, forward_{period}d]。"""
        ...
```

**与现有模块桥接**：

- **MyTT → 因子**：`TechnicalFactor` 包装器，将已注册的 `IndicatorSpec` 自动转为 `Factor`
- **缠论 → 因子**：`ChanlunFactor` 将买卖点、笔方向、背驰状态编码为数值因子
- **回测引擎**：`BacktestEngine` 新增 `factors=` 参数，计算结果自动注入 `StrategyDataProxy`

### 3.3 内置因子库（factor/builtin/）

第一版交付 **6 大类 15-20 个因子**：

| 类别 | 因子名 | 计算逻辑 | 数据需求 |
|------|--------|----------|----------|
| **动量** | `momentum_20d` | 20 日收益率 | close |
| | `momentum_60d` | 60 日收益率 | close |
| | `reversal_5d` | 5 日反转（负收益率） | close |
| **波动率** | `volatility_20d` | 20 日收益率标准差 | close |
| | `atr_14d` | 14 日平均真实波幅 | high, low, close |
| | `turnover_rate` | 换手率代理 | amount, close |
| **质量** | `sharpe_20d` | 20 日收益/波动比 | close |
| | `max_drawdown_20d` | 20 日最大回撤 | close |
| | `win_rate_20d` | 20 日上涨天数占比 | close |
| **成交量** | `obv_trend` | OBV 的 20 日斜率 | close, vol |
| | `vol_surge` | 当日量比（当日 / 20日均量） | vol |
| | `amount_ma_ratio` | 成交额 MA5/MA20 比值 | amount |
| **技术形态** | `macd_hist_signal` | MACD 柱状线符号 + 趋势 | close |
| | `rsi_14` | RSI(14) 归一化到 [-1, 1] | close |
| | `boll_position` | 价格在布林带中的位置 (0-1) | close |
| **缠论** | `chanlun_bi_dir` | 当前笔方向（+1/-1） | OHLCV |
| | `chanlun_mmd` | 最近买卖点类型（编码值） | OHLCV |
| **价值（可选）** | `pe_ratio` | 市盈率 | close + 财务数据 |
| | `pb_ratio` | 市净率 | close + 财务数据 |

**设计要点**：

- 纯 numpy 向量化，不依赖网络
- 每个因子类约 5-15 行实现
- `technical.py` 桥接 `indicator.py`，`chanlun.py` 桥接 `ChanlunAnalyser`，不重复实现
- 价值因子标记为可选，第一版可能只有接口占位

### 3.4 因子分析（factor/analysis.py）

```python
@dataclass
class FactorReport:
    """单因子分析报告。"""
    name: str
    ic_mean: float              # 均值 IC
    ic_std: float               # IC 标准差
    ir: float                   # 信息比率 = ic_mean / ic_std
    ic_positive_rate: float     # IC > 0 的占比
    quantile_returns: dict[str, float]  # {"q1": 0.01, "q2": 0.02, ..., "q5": 0.05}
    top_minus_bottom: float     # 多空收益（Q5 - Q1）
    turnover_rate: float        # 因子换手率
    autocorr: float             # 自相关系数
    ic_series: pd.Series        # 逐期 IC 序列
```

```python
class FactorAnalyzer:
    """因子有效性分析引擎。"""

    def __init__(
        self,
        factor_data: pd.DataFrame,     # columns: [date, code, factor_value]
        return_data: pd.DataFrame,     # columns: [date, code, forward_return]
        n_quantiles: int = 5,
    ): ...

    def compute_ic(self, method: str = "spearman") -> pd.Series: ...
    def compute_quantile_returns(self) -> pd.DataFrame: ...
    def compute_turnover(self) -> float: ...
    def compute_decay(self, max_lag: int = 10) -> pd.DataFrame: ...
    def full_report(self) -> FactorReport: ...
```

**输入格式**：长格式 DataFrame（`FactorEngine.compute_cross_section()` 的输出直接对接）。

- `factor_data`: columns=[date, code, factor_value_1, factor_value_2, ...]
- `return_data`: columns=[date, code, forward_5d]（由 `FactorEngine.compute_forward_returns()` 生成）

### 3.5 因子预处理（factor/transform.py）

所有函数均为纯函数（输入 DataFrame → 输出 DataFrame），可自由组合。

| 函数 | 用途 | 核心参数 |
|------|------|----------|
| `winsorize()` | 截面去极值 | method: "mad" / "percentile" / "sigma" |
| `zscore()` | 截面/时序标准化 | cross_section: bool |
| `rank_normalize()` | 排名归一化 [0, 1] | — |
| `fill_missing()` | 缺失值填充 | method: "industry_mean" / "cross_mean" / "forward_fill" |
| `orthogonalize()` | 因子正交化（回归残差） | target, by |
| `preprocess()` | 一键管道 | steps: ["winsorize", "zscore", "fill_missing"] |

**关键设计**：

- MAD 去极值对 A 股偏态分布更稳健，作为默认方法
- 正交化用纯 numpy 线性回归，不引入 sklearn
- 行业填充第一版 fallback 到全市场均值，后续加 SW 行业分类

## 4. 组合管理（portfolio/）

### 4.1 数据结构（portfolio/types.py）

```python
@dataclass
class PortfolioState:
    """组合状态快照。"""
    date: int
    weights: dict[str, float]       # {code: weight}
    holdings: dict[str, float]      # {code: shares}
    cash: float
    total_value: float
    positions_count: int

@dataclass
class RebalanceResult:
    """再平衡结果。"""
    rebalance_dates: list[int]
    states: list[PortfolioState]
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    performance: dict[str, float]   # 复用 PerformanceAnalyzer
```

### 4.2 权重优化器（portfolio/optimizer.py）

| 优化器 | 算法 | 依赖 | 适用场景 |
|--------|------|------|----------|
| `EqualWeightOptimizer` | 取 top-N 等权 | numpy | 基准 |
| `FactorWeightedOptimizer` | 按因子得分加权 | numpy | 单因子选股 |
| `RiskParityOptimizer` | 风险平价（迭代法） | numpy | 波动率差异大 |
| `MeanVarianceOptimizer` | Markowitz 模型 | scipy（可选） | 追求最优配置 |

注册机制：`@register_optimizer("name")`，通过名称查找。

**scipy 可选降级**：`MeanVarianceOptimizer` 在 scipy 缺失时降级为等权，不报错。

### 4.3 风险模型（portfolio/risk.py）

```python
class RiskModel:
    """简化风险模型 — A 股够用。"""

    def estimate_covariance(
        self,
        returns: pd.DataFrame,
        method: str = "shrinkage",       # Ledoit-Wolf 收缩估计
        shrinkage_intensity: float = 0.5,
        window: int = 60,
    ) -> pd.DataFrame: ...

    def portfolio_risk(
        self,
        weights: dict[str, float],
        cov_matrix: pd.DataFrame,
    ) -> dict[str, float]:
        """返回 total_volatility / marginal_risk / risk_contribution。"""
        ...
```

**不做完整 Barra**——提供个股波动率、收缩协方差矩阵、组合风险分解三个核心功能。

### 4.4 再平衡引擎（portfolio/rebalance.py）

```python
class RebalanceEngine:
    """多期调仓回测引擎。

    管道：FactorEngine → 截面得分 → Optimizer → 目标权重 → 交易成本 → 持仓跟踪
    """

    def __init__(
        self,
        optimizer: WeightOptimizer,
        factor_name: str,
        n_stocks: int = 50,
        rebalance_freq: str = "M",      # W / M / Q
        commission: float = 0.0003,
        slippage: float = 0.001,
        cash: float = 1_000_000,
    ): ...

    def run(
        self,
        data: dict[str, pd.DataFrame],
        start_date: int,
        end_date: int,
    ) -> RebalanceResult: ...
```

## 5. 依赖策略

### 核心依赖（无新增）

因子引擎的核心功能只依赖 numpy + pandas，已是 easy-tdx 的核心依赖。

### 可选依赖

```toml
[project.optional-dependencies]
factor = ["scipy>=1.10"]   # MeanVariance 优化器 + 协方差收缩估计
```

scipy 缺失时：`MeanVarianceOptimizer` 降级为等权，`RiskModel.estimate_covariance` 的 shrinkage 方法降级为样本协方差。

**不引入**：cvxpy、sklearn、statsmodels。

## 6. 公开 API

```python
# factor/__init__.py
from easy_tdx.factor.base import Factor, register_factor, FACTORY_REGISTRY
from easy_tdx.factor.engine import FactorEngine
from easy_tdx.factor.analysis import FactorAnalyzer, FactorReport
from easy_tdx.factor.transform import preprocess, winsorize, zscore, rank_normalize
from easy_tdx.factor.builtin import list_factors, get_factor

# portfolio/__init__.py
from easy_tdx.portfolio.optimizer import (
    WeightOptimizer, EqualWeightOptimizer, FactorWeightedOptimizer,
    RiskParityOptimizer, MeanVarianceOptimizer,
)
from easy_tdx.portfolio.rebalance import RebalanceEngine
from easy_tdx.portfolio.risk import RiskModel
```

## 7. 使用示例

```python
# ── 单因子研究 ──
from easy_tdx import TdxClient
from easy_tdx.factor import FactorEngine, FactorAnalyzer, preprocess

client = TdxClient()
data = {c: client.get_klines("SZ", c, "DAY") for c in ["000001", "000002", "600036"]}

# 计算截面因子值
engine = FactorEngine()
factor_data = engine.compute_cross_section(data, ["momentum_20d", "volatility_20d"])
# factor_data 格式: columns=[date, code, momentum_20d, volatility_20d]

# 预处理
clean = preprocess(factor_data, ["momentum_20d", "volatility_20d"])

# 构造远期收益（5 日收益率，对齐到因子日期）
return_data = engine.compute_forward_returns(data, period=5)
# return_data 格式: columns=[date, code, forward_5d]

# 因子分析
analyzer = FactorAnalyzer(clean, return_data, n_quantiles=5)
report = analyzer.full_report()
print(f"IC均值={report.ic_mean:.3f}, IR={report.ir:.3f}")

# ── 多因子选股 + 组合回测 ──
from easy_tdx.portfolio import RebalanceEngine, FactorWeightedOptimizer

optimizer = FactorWeightedOptimizer()
rebalancer = RebalanceEngine(optimizer=optimizer, factor_name="momentum_20d", n_stocks=50)
result = rebalancer.run(data, start_date=20230101, end_date=20240101)
print(f"年化收益={result.performance['annual_return']:.2%}")
```

## 8. 交付节奏

| 版本 | 内容 | 独立价值 |
|------|------|----------|
| **v1.11.0** | `factor/base` + `factor/engine` + `factor/builtin/`（15 个因子） + CLI `easy-tdx factor list` | 能计算和列举因子 |
| **v1.12.0** | `factor/transform` + `factor/analysis` + CLI `easy-tdx factor analyze` | 能评估因子好坏 |
| **v1.13.0** | `portfolio/` 全模块 + CLI `easy-tdx portfolio backtest` | 能用因子构建组合并回测 |

## 9. 测试策略

```
tests/unit/
├── test_factor_base.py         # Factor 基类、注册表
├── test_factor_engine.py       # FactorEngine 计算引擎
├── test_factor_builtin.py      # 每个内置因子的正确性
├── test_factor_transform.py    # 预处理管道
├── test_factor_analysis.py     # IC/分层/衰减
├── test_portfolio_optimizer.py # 各优化器
├── test_portfolio_risk.py      # 风险模型
└── test_portfolio_rebalance.py # 再平衡回测
```

**全部离线可测**：用 `np.random` 生成的价格数据 + fixture 验证，不依赖网络。

## 10. 后续扩展（方案 B 预留）

本设计为方案 B（高级回测增强）预留了以下接口：

- `factor/analysis.py` 的 `FactorReport` 可直接用于回测归因
- `portfolio/rebalance.py` 的 `RebalanceResult` 可接入增强的 `BacktestEngine`
- 后续可添加：滑点建模（方根模型/市场冲击）、执行仿真（TWAP/VWAP）、归因分析
