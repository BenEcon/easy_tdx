/**
 * 评级系统自检脚本。
 *
 * 项目未引入 vitest，采用 Node 内置 test runner（node:test）跑。
 * 评级逻辑是纯函数 + 零 DOM 依赖，可直接 import ESM TypeScript（Node v22+ 原生支持）。
 *
 * 运行：node --test src/grading/__tests__/grade.test.ts
 *
 * 关键断言：京东方案例（126.43% 收益但胜率 35.56%、回撤 41.65%、卡玛 0.336）
 * 必须落在 D 档——这是产品诉求的核心验证点。
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { reactive } from 'vue'

import { gradeBacktestResult, gradeOptimizationPoint, gradePerformance, gradeGridPoint, gradePortfolio } from '../index.ts'
import { GRADING_VERSION, performanceContext, performanceSnapshot, comparisonWarnings } from '../../performance-context.ts'
import { interpolate } from '../engine.ts'
import { THRESHOLDS } from '../thresholds.ts'
import { computeCombinedMetrics } from '../combinedMetrics.ts'
import type { BacktestResult, Performance, PerformanceBasis, PortfolioResult, GridPointResult, EquityPoint } from '../../types.ts'

function currentBasis(perf: Partial<Performance> = BOE_PERF): PerformanceBasis {
  return {
    contract_version: 'performance-sampling-v5', metric_contract: 'performance-metrics-v1',
    input_category: 'DAY', sample_category: 'DAY', category_source: 'snapshot',
    annual_periods: 252, sample_count: 252, return_count: 251, warnings: [],
    annualization_method: 'observed_period_compounding', risk_free_method: 'annual_rate_divided_by_periods',
    risk_free_rate: .03, sortino_definition: 'negative_excess_return_population_std',
    sample_start: '2025-01-02 15:00:00', sample_end: '2025-12-31 15:00:00',
    metric_status: Object.fromEntries(Object.entries(perf).map(([key]) => [key, { state: 'finite' as const, reason: '' }])),
  }
}

// ── 京东方案例（用户提供的真实回测数据）──────────────────────────────────────
const BOE_PERF: Performance = {
  total_return: 1.2643,
  annual_return: 0.1401,
  max_drawdown: 0.4165,
  max_dd_duration: 1,
  sharpe: 0.529,
  sortino: 0.825,
  calmar: 0.336,
  total_trades: 90,
  win_trades: 32,
  lose_trades: 58,
  rejected_trades: 0,
  win_rate: 0.3556,
  profit_factor: 1.107,
  avg_win: 0.0444,
  avg_loss: -0.0203,
  max_win: 0.2554,
  max_loss: -0.05,
  avg_holding_days: 11.222,
  volatility: 0.2496,
}

test('新版组合评级使用后端采样，不按图表柱数重新日线年化', () => {
  const basis = {
    ...currentBasis(), input_category: 'MIN_5',
    sample_category: 'DAY', category_source: 'snapshot', annual_periods: 252,
    sample_count: 4, return_count: 3, warnings: [],
  }
  const r = gradePortfolio({
    total_performance: { ...BOE_PERF, total_stocks: 2, total_cash: 200000 },
    individual_results: {}, equity_allocation: {}, combined_equity: [],
    performance_basis: basis,
  })
  assert.equal(r.dimensions.find(d => d.key === 'sharpe')?.raw, BOE_PERF.sharpe)
  assert.equal(r.dimensions.find(d => d.key === 'volatility')?.raw, BOE_PERF.volatility)
  assert.equal(r.insufficientSample, true)
})

test('必要风险指标缺失不能展示为零风险或正常评级', () => {
  const r = gradePerformance({ ...BOE_PERF, sharpe: Number.NaN, volatility: Number.NaN })
  assert.match(r.unavailableReason ?? '', /暂不评级/)
  const point = gradeGridPoint({ params: {}, total_return: .1, sharpe: null,
    max_drawdown: .05, total_trades: 30, win_rate: .6, profit_factor: 2 })
  assert.match(point.unavailableReason ?? '', /暂不评级/)
})

test('无穷比率不等于满分，真实零利润因子仍按亏损判断', () => {
  for (const value of [Infinity, -Infinity, Number.NaN]) {
    assert.match(gradePerformance({ ...BOE_PERF, calmar: value }).unavailableReason ?? '', /暂不评级/)
  }
  const point = { params: {}, total_return: .1, sharpe: 1, max_drawdown: .1,
    total_trades: 30, win_rate: 1, profit_factor: null,
    metric_status: { profit_factor: { state: 'positive_infinity' as const, reason: '没有亏损' } } }
  assert.match(gradeGridPoint(point).unavailableReason ?? '', /暂不评级/)
  assert.equal(gradeGridPoint({ ...point, profit_factor: 0, metric_status: undefined }).isLosing, true)
})

test('京东方回测必须评为 D 档（用户核心诉求验证点）', () => {
  const r = gradePerformance(BOE_PERF)
  console.log('京东方评级:', r.grade, '分数:', r.score)
  console.log('维度明细:', r.dimensions.map((d) => `${d.label}=${d.score.toFixed(1)}`).join(', '))
  console.log('否决:', r.vetoes.map((v) => v.reason).join('; '))
  assert.equal(r.grade, 'D', `期望 D，实际 ${r.grade}（分数 ${r.score}）。这个评级必须让用户认可。`)
})

test('京东方评分应在 30-43 区间（C 与 D 的边界）', () => {
  const r = gradePerformance(BOE_PERF)
  // 京东方分项：卡玛低 + 回撤深 + 胜率低，应在 D 档中段
  assert.ok(r.score >= 25 && r.score < 43, `分数 ${r.score} 不在 D 档合理区间`)
})

test('低利润因子触发系统亏损否决', () => {
  const r = gradePerformance({ ...BOE_PERF, profit_factor: 0.95 })
  assert.equal(r.grade, 'D')
  assert.equal(r.isLosing, true)
  assert.ok(r.vetoes.some((v) => v.key === 'losing_system'))
})

test('样本不足（< 10 笔交易）降权但不否决整个评级', () => {
  // 用户实测场景：策略本身数据不错（高夏普、低回撤），但因为长线策略天然交易少，
  // 旧逻辑会直接打到 D。修复后应该只降权 win_rate/profit_factor，评级照常给。
  // 这里用一个净值质量中等的案例，验证它不会无脑掉到 D。
  const r = gradePerformance({
    ...BOE_PERF,
    total_trades: 6,
    sharpe: 1.2,
    max_drawdown: 0.2,
    calmar: 1.5,
    volatility: 0.15,
    // win_rate / profit_factor 故意留噪音值，验证它们不影响总分
    win_rate: 0.5,
    profit_factor: 1.5,
  })
  assert.equal(r.insufficientSample, true, '应标记样本不足')
  // 修复后不应再否决到 D —— 高夏普/低回撤的长线策略应得 B 或更好
  assert.ok(
    ['A', 'B', 'S'].includes(r.grade),
    `高夏普长线策略不应因交易少被打到 D，实际 ${r.grade}（分数 ${r.score}）`,
  )
  // win_rate / profit_factor 权重应为 0
  const wr = r.dimensions.find((d) => d.key === 'win_rate')
  const pf = r.dimensions.find((d) => d.key === 'profit_factor')
  assert.equal(wr?.weight, 0, 'win_rate 权重应降为 0')
  assert.equal(pf?.weight, 0, 'profit_factor 权重应降为 0')
})

test('用户实测场景：6年6笔交易 + 高夏普 → 应得 A/B（核心回归测试）', () => {
  // 用户反馈：「有些策略数据不错，夏普也挺高，但是6年只有6次交易，评级就是D了」
  // 这条测试就是为这个场景兜底，确保修复后不再回归。
  const longTermGood: Performance = {
    total_return: 1.8, // 6 年 80%
    annual_return: 0.103, // 年化约 10%
    max_drawdown: 0.18, // 浅回撤
    max_dd_duration: 120,
    sharpe: 1.4, // 高夏普
    sortino: 1.8,
    calmar: 0.57, // 年化/回撤
    total_trades: 6, // ← 关键：长线策略交易少
    win_trades: 4,
    lose_trades: 2,
    rejected_trades: 0,
    win_rate: 0.667, // 6 笔里 4 笔赢，但样本太小不可信
    profit_factor: 2.5, // 同上
    avg_win: 0.15,
    avg_loss: -0.05,
    max_win: 0.3,
    max_loss: -0.08,
    avg_holding_days: 365, // 平均持仓 1 年
    volatility: 0.16,
  }
  const r = gradePerformance(longTermGood)
  console.log('长线优质策略评级:', r.grade, '分数:', r.score)
  console.log('维度权重:', r.dimensions.map((d) => `${d.label}=${(d.weight * 100).toFixed(0)}%`).join(', '))
  assert.equal(r.insufficientSample, true)
  // 这是核心断言：高夏普长线策略不该因交易少被打到 D
  assert.ok(
    ['A', 'B', 'S'].includes(r.grade),
    `用户场景必须修复：期望 A/B/S，实际 ${r.grade}（分数 ${r.score}）`,
  )
})

test('深回撤 > 60% 触发直接 D 否决', () => {
  const r = gradePerformance({ ...BOE_PERF, max_drawdown: 0.65 })
  assert.equal(r.grade, 'D')
  assert.ok(r.vetoes.some((v) => v.key === 'deep_drawdown'))
})

test('优质回测应得 A 或 S 档', () => {
  // 卡玛 2.0、夏普 1.8、回撤 15%、胜率 55%、利润因子 2.0、波动率 12% → 应是 A 或 S
  const good: Performance = {
    ...BOE_PERF,
    max_drawdown: 0.15,
    max_dd_duration: 30,
    sharpe: 1.8,
    sortino: 2.5,
    calmar: 2.0,
    win_rate: 0.55,
    profit_factor: 2.0,
    volatility: 0.12,
    total_trades: 80,
  }
  const r = gradePerformance(good)
  console.log('优质案例评级:', r.grade, '分数:', r.score)
  assert.ok(r.grade === 'A' || r.grade === 'S', `期望 A/S，实际 ${r.grade}`)
})

test('高回撤但收益高 → 最高 B（一票否决 cap）', () => {
  // 收益 200% 但回撤 55%，不该得高分
  const r = gradePerformance({
    ...BOE_PERF,
    max_drawdown: 0.55,
    total_return: 2.0,
    annual_return: 0.25,
    calmar: 0.45,
  })
  assert.ok(['B', 'C', 'D'].includes(r.grade), `回撤 55% 不应高于 B，实际 ${r.grade}`)
  assert.ok(r.vetoes.some((v) => v.key === 'high_drawdown'))
})

test('插值函数：边界值取端点分数', () => {
  assert.equal(interpolate(THRESHOLDS.max_drawdown.anchors, 0), 100)
  assert.equal(interpolate(THRESHOLDS.max_drawdown.anchors, 0.7), 0)
  assert.equal(interpolate(THRESHOLDS.max_drawdown.anchors, -1), 100) // 越界取端点
})

test('插值函数：中间值线性插值', () => {
  // 夏普 0.5 → 40, 0.8 → 55，0.65 应在中间附近
  const s = interpolate(THRESHOLDS.sharpe.anchors, 0.65)
  assert.ok(s > 40 && s < 55, `夏普 0.65 应在 40-55 之间，实际 ${s}`)
})

test('寻优评级：4 维度降级版', () => {
  const point: GridPointResult = {
    params: {},
    total_return: 1.5,
    sharpe: 1.5,
    max_drawdown: 0.2,
    total_trades: 50,
    win_rate: 0.5,
    profit_factor: 1.8,
  }
  const r = gradeGridPoint(point)
  assert.equal(r.scenario, 'optimize')
  assert.ok(['A', 'B', 'S'].includes(r.grade), `优质寻优点应得 A/B/S，实际 ${r.grade}（${r.score}）`)
  console.log('寻优点评级:', r.grade, r.score)
})

test('寻优评级：网格点交易太少 → 降权但评级照常', () => {
  const point: GridPointResult = {
    params: {},
    total_return: 0.5,
    sharpe: 2.0,
    max_drawdown: 0.1,
    total_trades: 3,
    win_rate: 0.7,
    profit_factor: 2.5,
  }
  const r = gradeGridPoint(point)
  assert.equal(r.insufficientSample, true)
  // 高夏普 + 浅回撤，即使交易少也应该得高分（不再否决到 D）
  assert.ok(
    ['A', 'B', 'S'].includes(r.grade),
    `优质寻优点不应因交易少被打到 D，实际 ${r.grade}`,
  )
})

// ── 组合评级：构造合成净值曲线验证 ─────────────────────────────────────────

function makeSyntheticEquity(
  startValue: number,
  dailyReturns: number[],
  startDate = '2022-01-03',
): EquityPoint[] {
  const points: EquityPoint[] = []
  let value = startValue
  let peak = startValue
  let dt = new Date(startDate)
  for (let i = 0; i < dailyReturns.length; i++) {
    if (i > 0) value *= 1 + dailyReturns[i]
    if (value > peak) peak = value
    const drawdown_pct = peak > 0 ? (peak - value) / peak : 0
    points.push({
      datetime: dt.toISOString().slice(0, 10),
      cash: 0,
      position_value: value,
      total: value,
      drawdown: peak - value,
      drawdown_pct,
    })
    dt.setDate(dt.getDate() + 1)
  }
  return points
}

test('组合评级：稳定上涨净值应得 A 或 S', () => {
  // 252 个交易日，日均 0.05% → 年化约 13%，回撤极小
  const returns = Array.from({ length: 252 }, (_, i) => {
    // 平稳上涨 + 小幅噪声，偶尔回调
    return i % 30 === 0 ? -0.008 : 0.0008 + (Math.sin(i) * 0.0003)
  })
  const equity = makeSyntheticEquity(1000000, returns)
  const m = computeCombinedMetrics(equity)
  console.log('组合重算指标:', {
    年化: (m.annual_return * 100).toFixed(2) + '%',
    回撤: (m.max_drawdown * 100).toFixed(2) + '%',
    夏普: m.sharpe.toFixed(2),
    卡玛: m.calmar.toFixed(2),
  })

  const result: PortfolioResult = {
    total_performance: {
      ...m,
      total_stocks: 3,
      total_cash: 1000000,
    },
    individual_results: {},
    equity_allocation: {},
    combined_equity: equity,
    performance_basis: currentBasis(m),
  }
  const r = gradePortfolio(result)
  console.log('稳定上涨组合评级:', r.grade, r.score)
  assert.equal(r.scenario, 'portfolio')
  assert.equal(r.unavailableReason, undefined)
  // 这种平滑上涨应该有不错的评级
  assert.ok(['A', 'B', 'S'].includes(r.grade), `稳定组合应得 A/B/S，实际 ${r.grade}`)
})

test('组合评级：高波动深回撤净值 → 低档', () => {
  // 模拟一个大幅震荡、最终亏损 + 深回撤的净值
  const returns = Array.from({ length: 252 }, (_, i) => {
    if (i < 60) return -0.01 + Math.sin(i) * 0.015 // 前 60 日大跌
    if (i < 120) return 0.005 + Math.sin(i) * 0.012
    return -0.002 + Math.sin(i) * 0.02 // 后期大幅震荡
  })
  const equity = makeSyntheticEquity(1000000, returns)
  const m = computeCombinedMetrics(equity)
  console.log('波动组合重算:', {
    回撤: (m.max_drawdown * 100).toFixed(2) + '%',
    夏普: m.sharpe.toFixed(2),
    持续: m.max_dd_duration,
  })

  const result: PortfolioResult = {
    total_performance: {
      ...m,
      total_stocks: 3,
      total_cash: 1000000,
    },
    individual_results: {},
    equity_allocation: {},
    combined_equity: equity,
    performance_basis: currentBasis(m),
  }
  const r = gradePortfolio(result)
  console.log('波动组合评级:', r.grade, r.score)
  assert.equal(r.unavailableReason, undefined)
  // 高波动 + 深回撤应得低评级
  assert.ok(['C', 'D', 'B'].includes(r.grade), `差组合应得 B/C/D，实际 ${r.grade}`)
})

test('combinedMetrics：单点净值返回全 0（兜底）', () => {
  const m = computeCombinedMetrics([{
    datetime: '2022-01-03',
    cash: 1000000,
    position_value: 0,
    total: 1000000,
    drawdown: 0,
    drawdown_pct: 0,
  }])
  assert.equal(m.total_return, 0)
  assert.equal(m.sharpe, 0)
  assert.equal(m.n_points, 1)
})

test('历史组合仅保留原值，不从曲线推断日线或重算评级', () => {
  const original: PortfolioResult = { total_performance: { total_return: .2, annual_return: 999,
    total_stocks: 1, total_cash: 100000 }, individual_results: {}, equity_allocation: {},
    combined_equity: makeSyntheticEquity(100000, [.001, .002, .003]) }
  const frozen = structuredClone(original)
  const grade = gradePortfolio(original)
  assert.equal(grade.context?.status, 'historical')
  assert.match(grade.unavailableReason ?? '', /历史原值/)
  assert.deepEqual(grade.vetoes, [])
  assert.ok(grade.dimensions.every(d => Number.isNaN(d.raw)))
  assert.deepEqual(original, frozen)
})

test('v1-v4、未知版本及不完整依据不伪装为新版结果', () => {
  for (const version of ['performance-sampling-v1', 'performance-sampling-v2',
    'performance-sampling-v3', 'performance-sampling-v4', 'performance-sampling-v6', 'unknown']) {
    const result: BacktestResult = { performance: BOE_PERF, config: {
      performance_basis: { ...currentBasis(), contract_version: version } },
      equity_curve: [], trades: [], positions: [] }
    const copy = structuredClone(result)
    const grade = gradeBacktestResult(result)
    assert.equal(grade.context?.status, version.match(/v[1-4]$/) ? 'historical' : 'unsupported')
    assert.ok(grade.unavailableReason)
    assert.deepEqual(grade.vetoes, [])
    assert.deepEqual(result, copy)
  }
  const basis = currentBasis()
  assert.equal(performanceContext({ ...basis, metric_status: undefined }).status, 'incomplete')
  assert.equal(performanceContext({ ...basis, return_count: -1 }).status, 'incomplete')
  assert.equal(performanceContext({ ...basis, metric_contract: undefined }).status, 'incomplete')
  assert.equal(performanceContext({ ...basis, sample_category: 'WEEK', annual_periods: 252 }).status, 'incomplete')
  assert.equal(performanceContext({ ...basis, return_count: 999 }).status, 'incomplete')
  assert.equal(performanceContext({ ...basis, metric_contract: 'future' }).status, 'unsupported')
})

test('新版结果使用已记录指标，真实 999 和零不被当作历史哨兵', () => {
  const perf = { ...BOE_PERF, calmar: 999, max_drawdown: 0, profit_factor: 0 }
  const grade = gradeBacktestResult({ performance: perf, config: { performance_basis: currentBasis(perf) },
    trades: [], positions: [], equity_curve: [] })
  assert.equal(grade.unavailableReason, undefined)
  assert.equal(grade.gradingVersion, GRADING_VERSION)
  assert.equal(grade.dimensions.find(d => d.key === 'calmar')?.raw, 999)
  assert.equal(grade.isLosing, true)
  assert.equal(grade.grade, 'D')
})

test('指标状态缺失或与数值冲突不能产出评级，包括被降权维度', () => {
  const perf = { ...BOE_PERF, total_trades: 0 }
  const basis = currentBasis(perf)
  for (const state of [undefined, { state: 'unavailable' as const, reason: 'no trades' }]) {
    const states = { ...basis.metric_status }
    if (state) states.profit_factor = state
    else delete states.profit_factor
    const grade = gradeBacktestResult({ performance: perf, config: { performance_basis: {
      ...basis, metric_status: states } }, trades: [], positions: [], equity_curve: [] })
    assert.ok(grade.unavailableReason)
    assert.deepEqual(grade.vetoes, [])
  }
})

test('低交易样本的真实不可用逐笔指标仍可降权，不误拦截可用净值评级', () => {
  const perf = { ...BOE_PERF, total_trades: 6, profit_factor: null, win_rate: null } as unknown as Performance
  const basis = currentBasis(perf)
  basis.metric_status!.profit_factor = { state: 'unavailable', reason: '逐笔样本不足' }
  basis.metric_status!.win_rate = { state: 'unavailable', reason: '逐笔样本不足' }
  const grade = gradeBacktestResult({ performance: perf, config: { performance_basis: basis },
    trades: [], positions: [], equity_curve: [] })
  assert.equal(grade.unavailableReason, undefined)
  assert.equal(grade.insufficientSample, true)
  assert.equal(grade.dimensions.find(d => d.key === 'profit_factor')?.weight, 0)
  assert.equal(grade.dimensions.find(d => d.key === 'win_rate')?.weight, 0)
})

test('寻优逐行核验新版采样与候选状态，输入范围不替代候选证据', () => {
  const point: GridPointResult = { params: {}, total_return: .1, sharpe: 1, max_drawdown: .1,
    total_trades: 30, win_rate: .6, profit_factor: 2 }
  const basis = { ...currentBasis(), scope: 'input_sampling_schedule', metric_contract: undefined,
    metric_status: undefined }
  assert.ok(gradeOptimizationPoint(point, basis).unavailableReason)
  const row = { ...point, metric_status: currentBasis(point).metric_status }
  assert.equal(gradeOptimizationPoint(row, basis).unavailableReason, undefined)
  assert.equal(gradeOptimizationPoint(row).context?.status, 'historical')
  assert.equal(gradeOptimizationPoint(row, { ...basis, contract_version: 'performance-sampling-v4' }).context?.status, 'historical')
  assert.equal(gradeOptimizationPoint(row, { ...basis, metric_contract: 'future' }).context?.status, 'unsupported')
})

test('完整快照保留精度、真实 0/999、全部指标及版本且不关联可变输入', () => {
  const perf = { ...BOE_PERF, calmar: 999, max_drawdown: 0, sharpe: 1.2345678901234567 }
  const basis = currentBasis(perf)
  const snapshot = performanceSnapshot(perf, basis)
  assert.equal(snapshot.sharpe, perf.sharpe)
  assert.equal(snapshot.calmar, 999)
  assert.equal(snapshot.max_drawdown, 0)
  assert.equal(snapshot.trades_count, perf.total_trades)
  assert.equal(snapshot.sortino, perf.sortino)
  assert.equal(snapshot.grading_version, GRADING_VERSION)
  basis.warnings.push('later change')
  assert.deepEqual(snapshot.performance_basis?.warnings, [])
  assert.deepEqual(JSON.parse(JSON.stringify(snapshot)).performance_basis.metric_status, basis.metric_status)
})

test('策略保存接受真实 Vue 响应式结果，不因 Proxy 无法 structuredClone 而失败', () => {
  const store = reactive({ performance: { ...BOE_PERF }, basis: currentBasis() })
  const snapshot = performanceSnapshot({ ...store.performance }, store.basis)
  assert.deepEqual(snapshot.performance_basis, currentBasis())
  store.basis.metric_status!.sharpe.state = 'unavailable'
  store.performance.sharpe = 9
  assert.equal(snapshot.sharpe, BOE_PERF.sharpe)
  assert.equal(snapshot.performance_basis?.metric_status?.sharpe.state, 'finite')
})

test('再次保存历史指标不补造新版计算或评级依据', () => {
  const legacy = { ...BOE_PERF, calmar: 999 }
  const saved = performanceSnapshot(legacy)
  assert.equal(saved.calmar, 999)
  assert.equal(saved.performance_basis, undefined)
  assert.equal(saved.grading_version, undefined)
  const oldBasis = { ...currentBasis(), contract_version: 'performance-sampling-v4' }
  const old = performanceSnapshot(legacy, oldBasis)
  assert.deepEqual(old.performance_basis, oldBasis)
  assert.equal(old.grading_version, undefined)
})

test('对比展示原值并指出版本、周期、范围与利率差异，不自动重算', () => {
  const result = (basis?: PerformanceBasis): BacktestResult => ({ performance: BOE_PERF,
    config: { performance_basis: basis }, trades: [], positions: [], equity_curve: [] })
  const basis = currentBasis()
  assert.deepEqual(comparisonWarnings([result(basis), result(structuredClone(basis))]), [])
  assert.match(comparisonWarnings([result(basis), result()]).join(), /历史/)
  const changed = { ...basis, input_category: 'WEEK', sample_category: 'WEEK', annual_periods: 52,
    sample_start: '2024-01-01', risk_free_rate: .01 }
  const warnings = comparisonWarnings([result(basis), result(changed)]).join()
  for (const word of ['分析周期', '收益采样周期', '年化期数', '采样起点', '无风险利率']) assert.ok(warnings.includes(word))
  assert.deepEqual(basis, currentBasis())
})
