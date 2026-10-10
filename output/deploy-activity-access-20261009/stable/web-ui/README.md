# easy-tdx 回测 Web UI

单标的策略回测的可视化前端（Vue3 + ECharts）。对应后端回测 REST API（`/api/v1/backtest/*`）。

## 快速开始

需要两个进程：后端 FastAPI（提供回测 + 行情 API）+ 前端 Vite dev server。

```bash
# 1. 启动后端（仓库根目录，使用 venv）
venv/Scripts/easy-tdx serve --port 8000

# 2. 启动前端（本目录）
npm install      # 首次
npm run dev      # 启动在 http://localhost:5173
```

浏览器打开 `http://localhost:5173`。开发期 `/api` 请求由 vite proxy 转发到后端 `127.0.0.1:8000`，无需处理跨域。

## 功能（MVP-A）

- **选标的取行情**：沪深北市场，日线/周线/分钟线，调 `/api/v1/bars`
- **策略选择 + 动态参数表单**：下拉选预置策略（MA交叉/MACD/布林/RSI/KDJ），参数表单按后端 schema 自动渲染
- **回测报告**：
  - K线主图 + 买卖点标注（ECharts candlestick + markPoint）
  - 净值曲线 + 回撤双轴图
  - 19 项绩效指标表（收益/风险/交易分组）
  - 成交记录表

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 框架 | Vue 3.5 + TypeScript | Composition API + `<script setup>` |
| 构建 | Vite 8 | dev proxy 解决跨域 |
| 状态 | Pinia | 策略列表 / OHLCV / 回测结果 |
| 路由 | Vue Router 4 | MVP 仅 `/`，预留组合/寻优/对比 |
| 图表 | ECharts（按需引入） | candlestick / line / markPoint |

## 目录结构

```
src/
├── main.ts               # 入口（Pinia + Router）
├── App.vue               # 根布局
├── router.ts             # 路由
├── api.ts                # fetch 封装（strategies/bars/backtest）
├── types.ts              # 后端 schema 的 TS 镜像
├── echarts-setup.ts      # ECharts 按需注册
├── style.css             # 深色金融主题
├── stores/backtest.ts    # 状态管理
├── views/BacktestView.vue    # 主页面（左配置 / 右报告）
└── components/
    ├── StrategyPicker.vue    # 策略下拉 + 动态参数表单
    ├── SymbolPicker.vue      # 选标的取行情
    ├── KlineChart.vue        # K线 + 买卖点
    ├── EquityChart.vue       # 净值 + 回撤
    ├── MetricTable.vue       # 绩效指标表
    └── TradeTable.vue        # 成交记录表
```

## 生产构建

```bash
npm run build    # 产物在 dist/，由 FastAPI 同源托管（待后续配置）
```

## 注意事项

- **取行情需要网络**：`/api/v1/bars` 通过 TDX 协议取真实行情，需后端能连通行情服务器。无网络时可手动构造 OHLCV（后续可加内联数据粘贴入口）。
- **A股配色惯例**：红涨绿跌（与 ECharts 默认相反），见 `echarts-setup.ts`。
