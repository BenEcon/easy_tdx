import type { ChanlunDivergence } from './types'

export interface DivergenceFocus {
  scope?: 'expansion' | 'released'
  title: string
  mode: 'ranges' | 'points'
  points: { label: string; index: number }[]
  ranges: { label: string; start: number; end: number }[]
  start: number
  end: number
}

export function divergenceFocus(item: ChanlunDivergence, count: number, title: string): DivergenceFocus | null {
  if (!item.bc || item.status === 'superseded' || !Number.isInteger(count) || count < 1) return null
  if (item.type === 'macd') {
    const previous = item.reference_index, current = item.signal_index
    if (previous == null || current == null || !Number.isInteger(previous)
      || !Number.isInteger(current) || previous < 0 || current <= previous || current >= count) return null
    const padding = Math.max(3, Math.ceil((current - previous + 1) * .15))
    return {title, mode: 'points', ranges: [],
      points: [{label: '前极值', index: previous}, {label: '本次极值', index: current}],
      start: Math.max(0, previous - padding), end: Math.min(count - 1, current + padding)}
  }
  const e = item.evidence ?? {}
  const ranges: DivergenceFocus['ranges'] = []
  for (const label of ['A', 'B', 'C'] as const) {
    const key = label.toLowerCase()
    const start = e[`${key}_start`], end = e[`${key}_end`]
    if (label === 'B' && start === undefined && end === undefined) continue
    if (start === undefined || end === undefined || !Number.isInteger(start)
      || !Number.isInteger(end) || start < 0 || end < start || end >= count) return null
    if (ranges.length && start < ranges.at(-1)!.end) return null
    ranges.push({label, start, end})
  }
  const padding = Math.max(3, Math.ceil((ranges.at(-1)!.end - ranges[0]!.start + 1) * .08))
  return {title, mode: 'ranges', points: [], ranges, start: Math.max(0, ranges[0]!.start - padding),
    end: Math.min(count - 1, ranges.at(-1)!.end + padding)}
}
