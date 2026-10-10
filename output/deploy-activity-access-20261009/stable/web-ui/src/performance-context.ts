import type { BacktestResult, PerformanceBasis, PortfolioResult } from './types'
import { resultBasis, type MetricStates } from './metric-state'

export const SAMPLING_VERSION = 'performance-sampling-v5'
export const METRIC_VERSION = 'performance-metrics-v1'
export const GRADING_VERSION = 'performance-grading-v1'

export interface PerformanceContext {
  status: 'current' | 'historical' | 'unsupported' | 'incomplete'
  label: string
  reason: string
  basis?: PerformanceBasis
}

/** Versions belong to the stored result, never the current page controls. */
export function performanceContext(basis?: PerformanceBasis | null, gridStates?: MetricStates): PerformanceContext {
  if (!basis) return {
    status: 'historical', label: '历史口径',
    reason: '未记录完整计算依据，保留历史原值，暂不按新版评级；重新运行会生成独立的新结果。',
  }
  if (/^performance-sampling-v[1-4]$/.test(basis.contract_version)) return {
    status: 'historical', label: '历史口径', basis,
    reason: `保存于 ${basis.contract_version}，保留原值，不自动升级或重算历史评级。`,
  }
  if (basis.contract_version !== SAMPLING_VERSION ||
      (basis.metric_contract !== undefined && basis.metric_contract !== METRIC_VERSION)) return {
    status: 'unsupported', label: '未支持口径', basis,
    reason: '计算版本不在当前评级支持范围，保留原值，暂不评级。',
  }
  const states = gridStates ?? basis.metric_status
  const periods: Record<string, number> = { DAY: 252, WEEK: 52, MONTH: 12, SEASON: 4, YEAR: 1 }
  if ((!gridStates && basis.metric_contract !== METRIC_VERSION) ||
      !states || !Object.keys(states).length ||
      !Number.isInteger(basis.return_count) || basis.return_count < 0 ||
      !Number.isInteger(basis.sample_count) || basis.sample_count < 0 ||
      basis.return_count > Math.max(0, basis.sample_count - 1) ||
      basis.annual_periods !== periods[basis.sample_category] ||
      !basis.sample_category || !basis.input_category) return {
    status: 'incomplete', label: '依据不完整', basis,
    reason: '计算依据或指标状态缺失，保留结果原值，暂不评级。',
  }
  return { status: 'current', label: '新版口径', reason: '', basis }
}

export function portfolioBasis(result: Partial<PortfolioResult>): PerformanceBasis | undefined {
  return result.performance_basis ?? result.data_provenance?.performance_basis ?? undefined
}

/** A snapshot preserves metrics and evidence; it is not an exact market replay. */
export function performanceSnapshot(performance: Record<string, unknown>, basis?: PerformanceBasis) {
  return cloneSnapshot({
    ...performance,
    trades_count: performance.total_trades,
    performance_basis: basis,
    snapshot_contract: 'performance-snapshot-v1',
    grading_version: performanceContext(basis).status === 'current' ? GRADING_VERSION : undefined,
  })
}

/** Read enumerable JSON-shaped data through Vue proxies without cloning proxies. */
function cloneSnapshot<T>(value: T): T {
  if (Array.isArray(value)) return value.map(item => cloneSnapshot(item)) as T
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneSnapshot(item)])) as T
  }
  return value
}

/** Same formulas alone do not imply matching periods or sampling windows. */
export function comparisonWarnings(results: Partial<BacktestResult>[]): string[] {
  if (results.length < 2) return []
  const contexts = results.map(result => performanceContext(resultBasis(result)))
  const warnings: string[] = []
  if (contexts.some(context => context.status !== 'current')) {
    warnings.push('包含历史、未支持或依据不完整的结果；原值可查阅，不宜直接按新版指标排名。')
  }
  const bases = contexts.map(context => context.basis).filter((basis): basis is PerformanceBasis => Boolean(basis))
  const fields: Array<[keyof PerformanceBasis, string]> = [
    ['input_category', '分析周期'], ['sample_category', '收益采样周期'],
    ['annual_periods', '年化期数'], ['sample_start', '采样起点'], ['sample_end', '采样终点'],
    ['annualization_method', '年化方法'], ['risk_free_method', '无风险利率方法'],
    ['risk_free_rate', '无风险利率'], ['sortino_definition', '索提诺定义'],
    ['valuation_contract', '组合估值口径'],
  ]
  const differences = fields.filter(([key]) => new Set(bases.map(basis => basis[key] ?? null)).size > 1)
    .map(([, label]) => label)
  if (differences.length) warnings.push(`${differences.join('、')}不同；以下仅并列展示保存值，不进行同口径排名。`)
  return warnings
}
