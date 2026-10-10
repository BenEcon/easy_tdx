import { matchesBreadth, type BreadthFilter, type TrackingAnalysis } from './tracking.ts'

const dimensions = {
  total: 'coverage', covered: 'coverage', penUp: 'pen', penDown: 'pen',
  aboveZero: 'axis', belowZero: 'axis', divergence: 'divergence',
  buy: 'structure', sell: 'structure', macdBuy: 'macd', macdSell: 'macd',
} as const

/** Same period/dimension: OR. Different periods/dimensions: AND. */
export function matchesBreadthFilters(row: TrackingAnalysis, selections: BreadthFilter[]): boolean {
  const groups = new Map<string, BreadthFilter[]>()
  for (const selection of selections) {
    const key = `${selection.category}:${dimensions[selection.metric]}`
    groups.set(key, [...(groups.get(key) ?? []), selection])
  }
  return [...groups.values()].every(group => group.some(selection => matchesBreadth(row, selection)))
}

export function toggleBreadthFilter(selections: BreadthFilter[], value: BreadthFilter): BreadthFilter[] {
  const same = (item: BreadthFilter) => item.category === value.category && item.metric === value.metric
  return selections.some(same) ? selections.filter(item => !same(item)) : [...selections, value]
}

export function matchesTrackingStatus(row: TrackingAnalysis, statuses: string[]): boolean {
  return !statuses.length || statuses.includes(row.state)
}
