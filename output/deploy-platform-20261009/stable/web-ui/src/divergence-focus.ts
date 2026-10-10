import type { ChanlunDivergence } from './types'

export interface DivergenceFocus {
  scope?: 'expansion' | 'released' | 'reverse-pen'
  pen?: { start: number; end: number; startPrice: number; endPrice: number }
  title: string
  mode: 'ranges' | 'points'
  points: { label: string; index: number }[]
  ranges: { label: string; start: number; end: number }[]
  start: number
  end: number
}

export function divergenceFocus(item: ChanlunDivergence, count: number, title: string): DivergenceFocus | null {
  if (!item.bc || !Number.isInteger(count) || count < 1) return null
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
  if (item.type === 'macd_wave_special' && (!Number.isInteger(item.signal_index)
    || item.signal_index! < 0 || item.signal_index! >= count
    || item.signal_index! < (e.b_start ?? Infinity) || item.signal_index! > (e.b_end ?? -1))) return null
  const ranges: DivergenceFocus['ranges'] = []
  for (const label of ['A', 'B', 'C'] as const) {
    if (label === 'C' && item.type === 'macd_wave_special') continue
    const key = label.toLowerCase()
    const start = e[`${key}_start`], end = e[`${key}_end`]
    if (label === 'B' && start === undefined && end === undefined) continue
    if (start === undefined || end === undefined || !Number.isInteger(start)
      || !Number.isInteger(end) || start < 0 || end < start || end >= count) return null
    if (ranges.length && start < ranges.at(-1)!.end) return null
    ranges.push({label, start, end})
  }
  const padding = Math.max(3, Math.ceil((ranges.at(-1)!.end - ranges[0]!.start + 1) * .08))
  const points = item.type === 'macd_wave_special' && item.signal_index != null
    ? [{label: 'B 内新极值', index: item.signal_index}] : []
  return {title, mode: 'ranges', points, ranges, start: Math.max(0, ranges[0]!.start - padding),
    end: Math.min(count - 1, ranges.at(-1)!.end + padding)}
}

/** Frozen local proof, not a replacement for any global structural pen. */
export function reversePenFocus(item: ChanlunDivergence, count: number, title: string): DivergenceFocus | null {
  const e = item.evidence ?? {}
  const start = e.reverse_pen_start, end = e.reverse_pen_end
  const known = item.confirmed_index
  if (!item.bc || item.status !== 'confirmed' || e.reverse_pen_local !== 1
    || !Number.isInteger(count) || count < 1 || start == null || end == null || known == null
    || !Number.isInteger(start) || !Number.isInteger(end) || !Number.isInteger(known)
    || start !== item.signal_index || start < 0 || end <= start || known <= end || known >= count
    || e.reverse_pen_confirmed !== known
    || !Number.isFinite(e.reverse_pen_start_price) || !Number.isFinite(e.reverse_pen_end_price)) return null
  return {title, scope:'reverse-pen', mode:'points', ranges:[],
    points:[{label:'信号极值',index:start},{label:'反向端点',index:end},{label:'实际确认',index:known}],
    pen:{start,end,startPrice:e.reverse_pen_start_price!,endPrice:e.reverse_pen_end_price!},
    start:Math.max(0,start-3),end:Math.min(count-1,known+3)}
}
