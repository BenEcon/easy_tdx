import type { ReleasedRecursion } from './types'
import type { DivergenceFocus } from './divergence-focus'
import { releaseEvidence } from './released-evidence.ts'

export type ReleaseFocusMode = 'movement' | 'macd' | 'reverse'

/** Resolve an ID against the current verified snapshot, never a retained event object. */
export function releasedFocus(data: ReleasedRecursion | undefined, id: string,
  count: number, mode: ReleaseFocusMode): DivergenceFocus | null {
  const evidence = releaseEvidence(data, count), record = evidence?.records.get(id)
  if (!record || !['movement', 'macd', 'reverse'].includes(mode)) return null
  const ranges: DivergenceFocus['ranges'] = []
  const valid = (start: number | undefined, end: number | undefined, known: number) =>
    Number.isSafeInteger(start) && Number.isSafeInteger(end) && start! >= 0
    && start! < end! && end! <= known && end! < count
  if (mode === 'movement') {
    ranges.push({label: `M${record.level} 本走势`, start: record.start_index, end: record.end_index})
  } else if (mode === 'macd') {
    const e = record.macd_evidence
    if (!e || !valid(e.a_start, e.a_end, record.known_index)
      || !valid(e.c_start, e.c_end, record.known_index)
      || e.a_start! < record.start_index || e.c_end! > record.end_index
      || e.a_end! >= e.c_start!) return null
    ranges.push({label: 'A 比较段', start: e.a_start!, end: e.a_end!},
      {label: 'C 比较段', start: e.c_start!, end: e.c_end!})
  } else {
    const reverse = evidence!.records.get(record.opposite_id)
    const start = reverse?.start_index ?? record.opposite_start_index
    const end = reverse?.end_index ?? record.opposite_end_index
    if (!valid(start, end, record.known_index) || start !== record.end_index) return null
    ranges.push({label: '反向确认 · 不计入本走势', start: start!, end: end!})
  }
  const first = ranges[0]!.start, last = ranges.at(-1)!.end
  const padding = Math.max(3, Math.ceil((last - first + 1) * .08))
  return {scope: 'released', title: `M${record.level} · ${record.direction === 'up' ? '向上' : '向下'}${record.kind === 'consolidation' ? '盘整' : '趋势'}核验`,
    mode: 'ranges', ranges, points: [], start: Math.max(0, first - padding),
    end: Math.min(count - 1, last + padding)}
}
