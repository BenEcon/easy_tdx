import type { ChanlunDivergence, ChanlunSignal, WaveDiagnostic } from './types'
import { divergenceEvidence, divergenceName, signalEvidence, waveDiagnosticLines, waveFailureSummary } from './divergence-evidence.ts'
import { macdPrompts } from './divergence-marker.ts'

export type EvidenceFamily = 'standard' | 'nonstandard' | 'special' | 'double' | 'structure' | 'structure_signal' | 'macd_prompt'
export type EvidenceState = 'confirmed' | 'candidate' | 'superseded' | 'never' | 'blocked' | 'unrecorded'
export interface EvidenceDateFocus { date: string; precision: 'day' | 'minute' }
export interface EvidenceFilter {
  family: EvidenceFamily | 'all'
  state: EvidenceState | 'all'
  direction: 'up' | 'down' | 'all'
  query: string
  date?: EvidenceDateFocus
}
export const evidenceStateLabels: Record<EvidenceState, string> = {
  confirmed: '已确认', candidate: '候选未确认', superseded: '已替代 / 失效',
  never: '未形成候选', blocked: '曾有候选 · 当前未通过', unrecorded: '状态未记录',
}
export function eventEvidenceState(item: ChanlunDivergence): EvidenceState {
  // Legacy records without a lifecycle state are not silently promoted to confirmed.
  return item.status ?? 'unrecorded'
}
export function diagnosticEvidenceState(item: WaveDiagnostic): EvidenceState {
  if (item.status !== 'blocked') return item.status
  return item.first_candidate_index == null ? 'never' : 'blocked'
}
interface IndexedEvidence<T> {
  item: T
  family: EvidenceFamily
  state: EvidenceState
  direction?: 'up' | 'down'
  search: string
  dates?: Array<string | null | undefined>
  ranges?: Array<[string | null | undefined, string | null | undefined]>
}
const normalize = (text: string) => text.normalize('NFKC').toLocaleLowerCase().replaceAll('t00:00:00', '')
const familyNames = { standard: '标准', nonstandard: '非标准', special: '特殊', double: '双线', structure: '结构' }
export function signalEvidenceState(item: ChanlunSignal): EvidenceState {
  return item.confirmed_date ? 'confirmed' : 'unrecorded'
}
export function indexStructureSignals(items: readonly ChanlunSignal[]): IndexedEvidence<ChanlunSignal>[] {
  const names: Record<string, string> = { '1buy': '一类买点', '2buy': '二类买点', '3buy': '三类买点', '1sell': '一类卖点', '2sell': '二类卖点', '3sell': '三类卖点' }
  return items.slice().reverse().map(item => {
    const state = signalEvidenceState(item)
    const direction = /^[123]buy$/.test(item.type) ? 'down' : /^[123]sell$/.test(item.type) ? 'up' : undefined
    return { item, family: 'structure_signal', state, direction, dates: [item.date, item.confirmed_date],
      search: normalize(['结构性买卖点', names[item.type] ?? item.type, evidenceStateLabels[state],
        item.date, item.confirmed_date, item.source, item.msg,
        ...(item.source === 'confirmed_segment_base_v1' ? signalEvidence(item) : [])].filter(Boolean).join(' ')) }
  })
}
export function indexMacdPrompts(items: readonly ChanlunDivergence[]): IndexedEvidence<ChanlunDivergence>[] {
  // Exactly the chart's existing M1 gate; never turn another family into a structural point.
  return indexEvidenceEvents(macdPrompts([...items])).map(row => ({ ...row, family: 'macd_prompt',
    search: normalize(`MACD M1 ${row.direction === 'down' ? '买入提示' : '卖出提示'} ${row.search}`) }))
}
export function indexEvidenceEvents(items: readonly ChanlunDivergence[]): IndexedEvidence<ChanlunDivergence>[] {
  return items.filter(item => item.bc).slice().reverse().map(item => {
    const family: EvidenceFamily = item.type === 'macd_wave' ? 'standard'
      : item.type === 'macd_wave_nonstandard' ? 'nonstandard' : item.type === 'macd_wave_special' ? 'special'
        : item.type === 'macd' ? 'double' : 'structure'
    const state = eventEvidenceState(item)
    return { item, family, state, direction: item.direction,
      dates: [item.curr_date, item.prev_date, item.detected_date, item.preliminary_date, item.confirmed_date, item.invalidated_date],
      search: normalize([divergenceName(item), evidenceStateLabels[state], item.curr_date, item.prev_date,
        item.detected_date, item.preliminary_date, item.confirmed_date, item.invalidated_date,
        item.msg, item.failure_reason, ...divergenceEvidence(item)].filter(Boolean).join(' ')) }
  })
}
export function indexEvidenceDiagnostics(items: readonly WaveDiagnostic[]): IndexedEvidence<WaveDiagnostic>[] {
  return items.slice().reverse().map(item => {
    const family = item.family ?? 'standard'
    const state = diagnosticEvidenceState(item)
    return { item, family, state, direction: item.direction,
      dates: [...Object.values(item.dates), ...(item.rejections ?? []).flatMap(entry => [entry.from_date, entry.through_date])],
      ranges: [
        ...['a', 'b', 'c'].map(part => [item.dates[`${part}_start`], item.dates[`${part}_end`]] as [string | undefined, string | undefined]),
        ...(item.rejections ?? []).map(entry => [entry.from_date, entry.through_date] as [string | undefined, string | undefined]),
      ],
      search: normalize([familyNames[family], item.direction === 'down' ? '底背离' : '顶背离',
        evidenceStateLabels[state], ...Object.values(item.dates), waveFailureSummary(item),
        ...waveDiagnosticLines(item)].join(' ')) }
  })
}
function dateKey(value: string | null | undefined, precision: EvidenceDateFocus['precision']): string | null {
  if (!value) return null
  const normalized = value.replace('T', ' ')
  if (!/^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?$/.test(normalized)) return null
  if (precision === 'day') return normalized.slice(0, 10)
  return normalized.length >= 16 ? normalized.slice(0, 16) : null
}
function matchesDate<T>(row: IndexedEvidence<T>, focus: EvidenceDateFocus): boolean {
  const selected = dateKey(focus.date, focus.precision)
  if (!selected) return false
  return !!row.dates?.some(date => dateKey(date, focus.precision) === selected)
    || !!row.ranges?.some(([start, end]) => {
      const a = dateKey(start, focus.precision), b = dateKey(end, focus.precision)
      return a !== null && b !== null && a <= selected && selected <= b
    })
}
export function filterEvidence<T>(items: readonly IndexedEvidence<T>[], filter: EvidenceFilter): T[] {
  const terms = normalize(filter.query.trim()).split(/\s+/).filter(Boolean)
  return items.filter(row => (filter.family === 'all' || row.family === filter.family)
    && (filter.state === 'all' || row.state === filter.state)
    && (filter.direction === 'all' || row.direction === filter.direction)
    && (!filter.date || matchesDate(row, filter.date))
    && terms.every(term => row.search.includes(term))).map(row => row.item)
}
