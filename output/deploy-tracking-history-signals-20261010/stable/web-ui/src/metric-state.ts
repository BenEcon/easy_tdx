import type { BacktestResult, PerformanceBasis } from './types'

export interface MetricState {
  state: 'finite' | 'unavailable' | 'positive_infinity' | 'negative_infinity'
  reason: string
}
export type MetricStates = Record<string, MetricState>

export function resultBasis(result: Partial<BacktestResult>): PerformanceBasis | undefined {
  return result.data_provenance?.performance_basis
    ?? result.config?.performance_basis as PerformanceBasis | undefined
}

export function metricText(value: unknown, state?: MetricState, format: 'percent' | 'ratio' | 'int' | 'bars' = 'ratio'): string {
  if (state?.state === 'unavailable') return '—'
  if (state?.state === 'positive_infinity' || value === Infinity) return '∞'
  if (state?.state === 'negative_infinity' || value === -Infinity) return '−∞'
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (format === 'percent') return `${(value * 100).toFixed(2)}%`
  if (format === 'int') return String(Math.round(value))
  if (format === 'bars') return `${value.toFixed(0)} 根`
  return value.toFixed(2)
}
