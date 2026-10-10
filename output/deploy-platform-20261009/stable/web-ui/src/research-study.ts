export interface StudyEvent {
  date: string; known_at?: string; key: string; direction: number; label: string
  active: boolean; invalidated_at: string | null; bars_ago: number
}
export interface StudyPair {
  state: string; description: string; directions: string; fast: number | null; slow: number | null
  gap: number | null; relative_gap: number | null; gap_change: number | null
  position_bars: number; above_ma5_bars?: number; above_ma10_bars?: number
}
interface StrictPen {
  direction: string; start_date: string; end_date: string; start_price: number; end_price: number
  locked: boolean; confirmed_date: string | null
}
export interface StudyRow {
  category: string; error?: string; bar_count: number; last_date: string; last_closed_at: string
  excluded_bars: number; warmup_warning: boolean; price: number; axis: string; histogram: string
  histogram_shrinking_bars: number; observations: string[]
  volume_ratio?: number | null
  window: { start: string; end: string; count: number; warmup_bars: number; truncated: boolean }
  recent: { overall: string; tail: string; structure: string; summary: string; change_pct: number | null
    high: number; low: number; max_close_drawdown_pct: number | null; method: string }
  ma_research: { periods: number[]; bull: { to: number | null; reason: string }; bear: { to: number | null; reason: string }
    lines: Array<{ period: number; value: number | null; slope: number | null }>
    gaps: Array<{ fast: number; slow: number; gap: number | null; gap_change: number | null }> }
  pairs: Record<'ma' | 'volume' | 'macd', StudyPair>
  coordination: { summary: string; components: Array<{ key: string; label: string; supported: boolean; date: string | null; description: string }> }
  events: StudyEvent[]
  axis_history: Array<{ key: string; first_up: string | null; last_up: string | null; invalidated_at: string | null; currently_above: boolean }>
  direction_observation: { strict: StrictPen | null; state: string; direction: string | null; description: string
    anchor_date: string | null; anchor_price: number | null; known_date: string | null
    confirmation: string; invalidation: string
    history: Array<{ date: string; description: string; anchor_date: string | null }>
    auxiliary: Array<{ category: string; covered: boolean; supports: boolean; description: string; last_closed_at: string
      axis: string; recent: string; tail: string; coordination: string; pen: StrictPen | null; divergences: Array<{ date: string; status: string; direction: string }> }> }
  divergences: Array<{ kind?: string; date: string; direction: string; status: string; confirmed_date: string | null }>
}
export interface Study {
  as_of: string; rows: StudyRow[]; conflicts: string[]; policy: string; rule_version: string; parameters: unknown
}
export const studyPeriods = [
  { value: 'MONTH', label: '月线' }, { value: 'WEEK', label: '周线' }, { value: 'DAY', label: '日线' },
  { value: 'MIN_120', label: '120 分钟' }, { value: 'MIN_60', label: '60 分钟' },
  { value: 'MIN_30', label: '30 分钟' }, { value: 'MIN_15', label: '15 分钟' },
  { value: 'MIN_5', label: '5 分钟' }, { value: 'MIN_1', label: '1 分钟' },
] as const
export type StudyPeriod = typeof studyPeriods[number]['value']
export const studyLabel = (value: string) => studyPeriods.find(p => p.value === value)?.label ?? value
export const studyNumber = (value: number | null | undefined) => value == null ? '不可计算' : value.toFixed(2)
export const studySlope = (value: number | null) => value == null ? '样本不足' : value > 0 ? '上升' : value < 0 ? '下降' : '持平'
export const studyStatus = (value: string) => ({ candidate: '候选', preliminary: '初步确认', confirmed: '已确认', superseded: '失效 / 被替代' }[value] ?? value)

/** Wall-clock exchange-local value. Never infer a timezone from the browser. */
export const studyTime = (value: string) => value.replace('T', ' ').slice(0, 19).padEnd(19, ':00')
export function studyWindowError(mode: string, start: string, end: string, cutoff: string) {
  if (mode !== 'range') return ''
  if (!start || !end) return '请选择研究窗口的起止时间'
  if (start > end) return '研究开始时间不能晚于结束时间'
  if (studyTime(end) > studyTime(cutoff)) return '研究结束时间不能超过主图共同截止'
  return ''
}
