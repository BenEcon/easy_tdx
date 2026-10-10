# Backtest Engine Design — easy-tdx

**Date:** 2026-06-09
**Status:** Approved (rev 2 — incorporated DeepSeek feasibility review)
**Module:** `easy_tdx.backtest`
**Priority:** P0 — 量化工具链全栈的第一块拼图

---

## 1. 目标

为 easy-tdx 新增自建回测引擎模块，让用户能基于 easy-tdx 获取的 K 线数据执行策略回测、查看绩效报告。

### 核心约束

- 纯计算模块，与 `chanlun` 同级，零网络依赖
- 仅依赖 `pandas`/`numpy`（项目已有），不引入第三方回测库
- 接收 easy-tdx 标准 DataFrame（`datetime, open, close, high, low, vol, amount`）及带指标列的扩展 DataFrame
- 双模式策略定义：Python 类继承（P0）+ DSL 公式语法（P1）
- v1 只实现向量化执行路径（日级策略），架构预留事件驱动扩展点

### v1 范围（P0 vs P1）

| 优先级 | 模块 | 说明 |
|--------|------|------|
| **P0** | Strategy 基类 | Python 类继承 + `init()`/`next()` 生命周期 |
| **P0** | 向量化引擎 | 信号→撮合→持仓→绩效 四步管道 |
| **P0** | OrderSimulator | 5 种成交价规则 + 订单拒绝策略 |
| **P0** | PortfolioTracker | 持仓追踪 + 资金曲线 |
| **P0** | PerformanceAnalyzer | 18 项绩效指标 |
| **P0** | CLI `easy-tdx backtest` | 自动获取 K 线 + 执行回测 |
| **P0** | 预计算指标列支持 | DataFrame 中的额外列可直接在策略中引用 |
| **P0** | 缠论预留接口 | `self.chanlun` 属性，引擎接受可选 `chanlun_result` 参数 |
| **P1** | DSL 装饰器 | `@dsl_strategy` Python 函数模式 |
| **P1** | DSL 字符串解析 | CLI `--strategy "CROSS(MA(close,5),MA(close,20))"` |
| **P1** | `run_many` 多股票 | 顺序独立回测多只股票 |
| **P1** | `run_grid` 参数扫描 | 参数网格搜索 |

---

## 2. 架构

### 2.1 文件结构

```
src/easy_tdx/backtest/
├── __init__.py          # 公开 API 导出
├── strategy.py          # Strategy 基类 + StrategyDataProxy + IndicatorProvider
├── dsl.py               # DSL 解析器 + @dsl_strategy 装饰器 + 字符串 DSL 编译 (P1)
├── engine.py            # BacktestEngine（向量化执行路径）
├── orders.py            # OrderSimulator（撮合规则 + 订单拒绝策略）
├── portfolio.py         # PortfolioTracker（持仓/资金曲线）
├── performance.py       # PerformanceAnalyzer（绩效指标计算）
├── types.py             # Trade / Position / Signal / BacktestResult 数据类
└── cli.py               # CLI 集成（easy-tdx backtest ...，自动获取 K 线）
```

### 2.2 模块交互流

```
easy_tdx MacClient.get_stock_kline() → DataFrame
  或 MacClient.get_stock_kline_with_indicators() → DataFrame (含指标列)
  或 ChanlunAnalyser.process_klines() → ChanlunResult (可选注入)
                    │
                    ▼
          BacktestEngine(strategy, cash=100000, chanlun_result=None)
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   Strategy     DSL Parser   OrderSimulator
   (Python类)   (公式语法)   (撮合+拒绝策略)
        │           │           │
        └─────┬─────┘           │
              ▼                 │
         Signal (bool mask)     │
              │                 │
              ▼                 ▼
         PortfolioTracker ←────┘
              │
              ▼
         PerformanceAnalyzer
              │
              ▼
         BacktestResult
         (绩效指标 + 资金曲线 + 交易记录)
```

---

## 3. 核心数据类型

### 3.1 Signal

```python
@dataclass
class Signal:
    datetime: int
    direction: Literal["BUY", "SELL"]
    size: float                # 0 = 全仓/清仓
    price: float | None        # None = 市价
    stop_loss: float | None
    take_profit: float | None
```

### 3.2 Trade

```python
@dataclass
class Trade:
    datetime: int
    direction: Literal["BUY", "SELL"]
    size: float
    price: float
    commission: float
    slippage: float
    pnl: float                # 仅平仓时计算
    rejected: bool = False     # 订单是否被拒绝（资金/持仓不足）
```

### 3.3 Position

```python
@dataclass
class Position:
    datetime: int
    size: float                # 正=多头，负=空头，0=空仓
    avg_price: float
    market_value: float
    unrealized_pnl: float
```

### 3.4 BacktestResult

```python
@dataclass
class BacktestResult:
    performance: dict[str, float]
    equity_curve: pd.DataFrame   # datetime, cash, position_value, total, drawdown, drawdown_pct
    trades: pd.DataFrame         # datetime, direction, size, price, commission, pnl, rejected
    positions: pd.DataFrame      # datetime, size, avg_price, market_value, unrealized_pnl
    config: dict                 # 包含 future_leak_warning 等标记
```

方法：
- `to_json() → str`
- `to_dict() → dict`
- `summary() → None`（打印概要）

---

## 4. Strategy 基类

### 4.1 接口定义

```python
class Strategy(ABC):
    def init(self) -> None:
        """注册指标。策略初始化时调用一次。"""
        pass

    def next(self) -> None:
        """每根 K 线调用。在此生成买卖信号。"""
        pass

    def I(self, func: Callable, *args, **kwargs) -> np.ndarray:
        """注册指标函数。init() 后一次性计算，返回完整数组。"""
        ...

    def buy(self, size: float = 0, price: float | None = None,
            stop_loss: float | None = None, take_profit: float | None = None) -> None:
        """买入。size=0 全仓。"""
        ...

    def sell(self, size: float = 0, price: float | None = None,
             stop_loss: float | None = None, take_profit: float | None = None) -> None:
        """卖出。size=0 清仓。"""
        ...

    @property
    def data(self) -> StrategyDataProxy: ...

    @property
    def position(self) -> Position: ...

    @property
    def chanlun(self) -> Any | None:
        """缠论分析结果（如果引擎注入了 chanlun_result 参数）。
        v1 仅作为数据通道，策略可读取笔/中枢/买卖点信息。
        v2 计划实现自动集成。"""
        ...
```

### 4.2 StrategyDataProxy

```python
class StrategyDataProxy:
    """K 线数据代理。支持 .close[0]（当前）、.close[-1]（前一根）。
    
    自动暴露 DataFrame 中的所有列——包括预计算的指标列。
    例如 get_stock_kline_with_indicators() 返回的 MACD_DIF 列
    可直接通过 self.data.MACD_DIF[0] 访问。
    """
    @property
    def open(self) -> _SeriesAccessor: ...
    @property
    def close(self) -> _SeriesAccessor: ...
    @property
    def high(self) -> _SeriesAccessor: ...
    @property
    def low(self) -> _SeriesAccessor: ...
    @property
    def vol(self) -> _SeriesAccessor: ...
    @property
    def amount(self) -> _SeriesAccessor: ...
    # 额外列（预计算指标、缠论结果等）通过 __getattr__ 动态暴露
    def __getattr__(self, name: str) -> _SeriesAccessor: ...

class _SeriesAccessor:
    """[0] 当前值、[-1] 前一根、切片。"""
    def __getitem__(self, key: int) -> float: ...
    def __len__(self) -> int: ...
```

### 4.3 Python 类策略示例

**基本用法：**

```python
class MACrossStrategy(Strategy):
    def init(self):
        self.ma5 = self.I(MA, self.data.close, 5)
        self.ma20 = self.I(MA, self.data.close, 20)

    def next(self):
        if crossover(self.ma5, self.ma20):
            self.buy(size=100)
        elif crossover(self.ma20, self.ma5):
            self.sell(size=100)

engine = BacktestEngine(strategy=MACrossStrategy, cash=100000)
result = engine.run(df)
```

**使用预计算指标列：**

```python
class BollingerBreakout(Strategy):
    def init(self):
        pass  # 指标已在 DataFrame 中预计算

    def next(self):
        if self.data.close[0] > self.data.BOLL_UPPER[0]:
            self.sell(size=0)
        elif self.data.close[0] < self.data.BOLL_LOWER[0]:
            self.buy(size=0)

# 先获取带指标的 DataFrame
with MacClient.from_best_host() as c:
    df = c.get_stock_kline_with_indicators(
        Market.SH, "600519",
        indicators=["BOLL"],
        count=500,
    )

engine = BacktestEngine(strategy=BollingerBreakout, cash=100000)
result = engine.run(df)
```

**使用缠论信号（v1 手动注入）：**

```python
class ChanlunStrategy(Strategy):
    def init(self):
        pass

    def next(self):
        # self.chanlun 是外部注入的 ChanlunResult
        if self.chanlun is None:
            return
        last_mmd = self.chanlun.mmds[-1] if self.chanlun.mmds else None
        if last_mmd and "1buy" in last_mmd.msg:
            self.buy(size=0)

# 获取 K 线 + 缠论分析
with MacClient.from_best_host() as c:
    df = c.get_stock_kline(Market.SH, "600519", Period.DAILY, count=800)
analyser = ChanlunAnalyser("SH600519", "DAILY")
chanlun_result = analyser.process_klines(df)

engine = BacktestEngine(strategy=ChanlunStrategy, cash=100000)
result = engine.run(df, chanlun_result=chanlun_result)
```

---

## 5. DSL 策略定义 (P1)

### 5.1 设计边界

| 能做 | 不做 |
|------|------|
| 指标交叉、比较、逻辑组合 | 循环、变量赋值、函数定义 |
| 内置常用函数（CROSS, ABOVE, BELOW, BETWEEN） | 自定义控制流 |
| 参数化（可调窗口期） | 图灵完备 |
| **显式引用价格序列** (`close`, `open`, `high`, `low`) | 隐式推断（消除歧义） |

超出 DSL 能力的——直接用 Python 类。

### 5.2 两种 DSL 模式

**Python 装饰器模式**：

```python
from easy_tdx.backtest import dsl_strategy

@dsl_strategy
def dual_ma(df):
    buy = CROSS(MA(df.close, 5), MA(df.close, 20))
    sell = CROSS(MA(df.close, 20), MA(df.close, 5))
    return buy, sell
```

**字符串模式**（CLI 用，显式引用列名）：

```bash
easy-tdx backtest SH 600519 --strategy "CROSS(MA(close,5),MA(close,20))" --cash 100000 --table
```

编译器内部将 `close` 映射到 DataFrame 的 `close` 列。标识符规则：字母/数字/下划线，首字符不为数字。支持的列名：`open`, `close`, `high`, `low`, `vol`, `amount`，以及预计算的指标列名（如 `MACD_DIF`, `BOLL_UPPER`）。

### 5.3 内置 DSL 函数

复用 `MyTT.py` 已有实现：

| 函数 | 签名 | 含义 |
|------|------|------|
| `MA(series, n)` | `(ndarray, int) → ndarray` | 简单移动平均 |
| `EMA(series, n)` | `(ndarray, int) → ndarray` | 指数移动平均 |
| `RSI(series, n)` | `(ndarray, int) → ndarray` | 相对强弱 |
| `BOLL(series, n, k)` | `(ndarray, int, float) → tuple` | 布林带 |
| `MACD(series, fast, slow, signal)` | `(ndarray, ...) → tuple` | MACD |
| `CROSS(a, b)` | `(ndarray, ndarray) → ndarray[bool]` | 上穿检测 |
| `REF(series, n)` | `(ndarray, int) → ndarray` | 前 n 期值 |
| `HHV(series, n)` | `(ndarray, int) → ndarray` | n 期最高 |
| `LLV(series, n)` | `(ndarray, int) → ndarray` | n 期最低 |
| `BETWEEN(x, a, b)` | `(ndarray, ...) → ndarray[bool]` | 区间判断 |
| `COUNT(cond, n)` | `(ndarray[bool], int) → ndarray` | n 期满足条件次数 |

### 5.4 DSL 编译器

`DSLCompiler.compile(func)` 流程：
1. 调用 `func(mock_df)` 捕获 DSL 函数调用
2. 记录 `(buy_mask, sell_mask)` 信号生成规则
3. 动态生成 Strategy 子类

引擎侧优化：DSL 策略不逐 Bar 调用 `next()`，直接用 bool mask 一次性生成全部 Signal。

---

## 6. 引擎执行流

### 6.1 BacktestEngine 构造参数

```python
class BacktestEngine:
    def __init__(
        self,
        strategy: type[Strategy] | Strategy,
        cash: float = 100000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",       # "next_open" | "next_close" | "this_close" | "worst" | "best"
        position_mode: str = "full",        # "full" | "fixed" | "percent" | "signal_only"
        order_reject_policy: str = "reduce", # "reduce" | "skip"
        benchmark: pd.DataFrame | None = None,
    ):
        ...

    def run(self, df: pd.DataFrame, chanlun_result: Any | None = None) -> BacktestResult:
        """执行回测。df 是 easy_tdx 标准 K 线 DataFrame（可含额外指标列）。
        chanlun_result 可选注入缠论分析结果，策略通过 self.chanlun 访问。
        注意：缠论结果中的时间戳按最近 K 线 datetime 匹配对齐（笔确认需后续K线，
        买卖点时间戳可能与 K 线不完全一致，引擎取 <= 该时间戳的最后一根 K 线）。"""
        ...
```

### 6.2 四步执行管道

1. **信号生成**：DSL → bool mask；Python 类 → trace next() 生成 mask
2. **信号→订单**（OrderSimulator）：根据 execution 规则确定成交价，根据仓位模式确定量，根据 order_reject_policy 处理资金/持仓不足
3. **持仓追踪**（PortfolioTracker）：逐 Bar 更新现金/持仓/市值/回撤
4. **绩效分析**（PerformanceAnalyzer）：从资金曲线计算全部指标

Step 2 是唯一需要逐行处理的步骤（仓位依赖前一 Bar 状态）。其余步骤全向量化。

### 6.3 OrderSimulator 成交价规则

| 模式 | 说明 |
|------|------|
| `next_open`（默认） | 下一根 K 线开盘价成交，最真实 |
| `next_close` | 下一根 K 线收盘价成交 |
| `this_close` | 当根 K 线收盘价成交（**未来函数风险**，引擎自动在日志输出红色警告，并在 `BacktestResult.config` 中标记 `future_leak_warning=True`） |
| `worst` | 对投资者最差价格（买入取 high，卖出取 low） |
| `best` | 对投资者最优价格（买入取 low，卖出取 high） |

### 6.4 仓位管理规则

| 模式 | 说明 |
|------|------|
| `full`（默认） | 买入用全部现金，卖出清仓 |
| `fixed` | 每次固定股数 |
| `percent` | 每次用总资产的 N% |
| `signal_only` | 只生成信号，不模拟仓位 |

### 6.5 订单拒绝策略

当资金不足（买入）或持仓不足（卖出）时的处理方式：

| 模式 | 说明 |
|------|------|
| `reduce`（默认） | 自动减到最大可买/可卖量：买入量 = min(请求量, 最大可买量)；卖出量 = min(请求量, 当前持仓量)。记录实际成交 |
| `skip` | 跳过该信号，记录一条 `rejected=True` 的 Trade |

### 6.6 费用模型

- 佣金：`max(size * price * commission_rate, min_commission)`，买卖双向
- 印花税：`size * price * stamp_tax_rate`，仅卖出
- 滑点：`size * slippage_per_share`

### 6.7 基准对齐规则

`benchmark` 参数传入 `pd.DataFrame`，要求包含 `datetime` 和 `close` 列。引擎内部执行：
1. 按 `datetime` 对齐（`merge` on `datetime`）
2. 缺失值前向填充（`ffill`）
3. 仍缺失的 Bar 不计入 alpha/information_ratio 计算

### 6.8 多策略批量回测 (P1)

```python
# 多只股票（顺序独立回测，非组合）
results = engine.run_many({
    "SH600519": df_519,
    "SZ000858": df_858,
})
# → dict[str, BacktestResult]，每个 key 对应一只股票的回测结果

# 参数扫描
results = engine.run_grid(df, params={
    "short": [5, 10, 15],
    "long": [20, 30, 60],
})
# → list[GridResult]
# GridResult.params: dict[str, Any]  # 使用的参数组合
# GridResult.result: BacktestResult   # 该参数组合的回测结果
# GridResult 支持 .sort_by("sharpe").to_table()
```

---

## 7. 绩效指标

| 指标 | key | 算法 |
|------|-----|------|
| 总收益率 | `total_return` | `(total[-1] / total[0]) - 1` |
| 年化收益率 | `annual_return` | `(1 + r) ** (252/n) - 1` |
| 最大回撤 | `max_drawdown` | `max((peak - total) / peak)` |
| 最大回撤天数 | `max_dd_duration` | 首次新高 - 回撤起点 |
| 夏普比率 | `sharpe` | `(mean(ret) - rf/252) / std(ret) * sqrt(252)` |
| 索提诺比率 | `sortino` | 分母只用负收益标准差 |
| 卡玛比率 | `calmar` | `annual_return / max_drawdown` |
| 总交易次数 | `total_trades` | `len(trades)` |
| 盈利/亏损次数 | `win_trades` / `lose_trades` | `trade_pnl > 0 / <= 0` |
| 被拒绝订单数 | `rejected_trades` | `trade.rejected == True` 的数量 |
| 胜率 | `win_rate` | `win_trades / total_trades` |
| 盈亏比 | `profit_factor` | `sum(win_pnl) / abs(sum(lose_pnl))` |
| 平均盈利/亏损 | `avg_win` / `avg_loss` | 盈利/亏损交易均值 |
| 最大单笔盈亏 | `max_win` / `max_loss` | 单笔极值 |
| 平均持仓天数 | `avg_holding_days` | 买入到卖出的 Bar 数均值 |
| 收益波动率 | `volatility` | `std(daily_ret) * sqrt(252)` |
| 基准超额收益 | `alpha` | 策略收益 - 基准收益（需 benchmark） |
| 信息比率 | `information_ratio` | 超额收益均值 / 跟踪误差（需 benchmark） |

---

## 8. CLI 集成

### 8.1 命令

CLI 自动获取 K 线数据，用户无需手动构造 DataFrame：

```bash
# 基本用法：自动获取 K 线 + 执行回测
easy-tdx backtest SH 600519 --strategy "CROSS(MA(close,5),MA(close,20))" --cash 100000 --table

# 指定周期/复权/数量
easy-tdx backtest SH 600519 --strategy "CROSS(MA(close,5),MA(close,20))" \
    --period DAILY --adjust QFQ --count 500 --table

# Python 类策略文件
easy-tdx backtest SH 600519 --strategy-file my_strategy.py --cash 100000

# 参数化
easy-tdx backtest SH 600519 --strategy "CROSS(MA(close,{short}),MA(close,{long}))" \
    --params short=5,long=20

# 参数扫描 (P1)
easy-tdx backtest SH 600519 --strategy "CROSS(MA(close,{short}),MA(close,{long}))" \
    --grid short=5,10,15 --grid long=20,30,60 --sort-by sharpe --table

# 输出 CSV
easy-tdx backtest SH 600519 --strategy "CROSS(MA(close,5),MA(close,20))" --output csv

# 策略文件中用预计算指标列
easy-tdx backtest SH 600519 --strategy-file boll_strategy.py --indicators BOLL --table
```

### 8.2 输出格式

默认 JSON，`--table` 切换表格，`--output csv` 输出 CSV。与现有 CLI 行为一致。

---

## 9. 测试计划

```
tests/unit/test_backtest_strategy.py     # Strategy 基类 + 指标注入 + 预计算列 + 缠论注入
tests/unit/test_backtest_dsl.py          # DSL 解析 + 编译 (P1)
tests/unit/test_backtest_engine.py       # 引擎核心（信号→成交→持仓）
tests/unit/test_backtest_orders.py       # 撮合规则（5 种 execution + 2 种 reject policy）
tests/unit/test_backtest_portfolio.py    # 持仓追踪 + 资金曲线
tests/unit/test_backtest_performance.py  # 绩效计算（手工验证已知结果）
tests/unit/test_backtest_cli.py          # CLI 命令（click test runner）
```

全部离线测试，使用手工构造的 DataFrame fixture，零网络依赖。

---

## 10. 未来扩展点（v1 不实现，架构不堵死）

- **缠论自动集成** (P1→v2)：引擎自动调用 `ChanlunAnalyser`，策略通过 `self.chanlun` 直接获取笔/中枢/买卖点，无需手动注入
- **事件驱动执行路径**：支持日内策略、逐 tick 推演
- **多品种组合回测**：Portfolio 级别，同时持有多只股票的资金分配
- **风控模块**：最大回撤止损、单笔止损、仓位上限
- **实时模拟交易**：Strategy 基类接口可直接迁移
- **可视化**：K 线 + 买卖点标注 + 资金曲线
- **信号导出**：`--save-signals` 将买卖点写入 DataFrame，联动 indicator 命令
