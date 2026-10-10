import type { ExpansionCandidate } from './types'
import type { DivergenceFocus } from './divergence-focus'

/** Locate proven source geometry only; never infer missing endpoints from dates. */
export function expansionFocus(candidate: ExpansionCandidate, count: number, title: string): DivergenceFocus | null {
  const barIndex = (value: unknown): value is number => typeof value === 'number'
    && Number.isInteger(value) && value >= 0 && value < count
  if (!Number.isInteger(count) || count < 1
    || candidate.status !== 'partition_found_awaiting_type_completion'
    || !barIndex(candidate.known_index) || candidate.parts.length !== 3) return null

  const source = candidate.source_segment_indices
  if (source.length < 9 || !source.every((id, i) => Number.isInteger(id) && id >= 0
    && (!i || id === source[i - 1]! + 1))) return null
  const flattened = candidate.parts.flatMap(part => part.source_segment_indices)
  if (flattened.length !== source.length || flattened.some((id, i) => id !== source[i])) return null

  const ranges: DivergenceFocus['ranges'] = []
  for (const [index, part] of candidate.parts.entries()) {
    if (part.source_segment_indices.length < 3 || !barIndex(part.start_index)
      || !barIndex(part.end_index) || part.start_index >= part.end_index
      || !barIndex(part.known_index) || part.known_index < part.end_index
      || part.known_index > candidate.known_index
      || (index > 0 && part.start_index !== candidate.parts[index - 1]!.end_index)) return null
    ranges.push({ label: (['A', 'B', 'C'] as const)[index]!, start: part.start_index, end: part.end_index })
  }
  const padding = Math.max(3, Math.ceil((ranges[2]!.end - ranges[0]!.start + 1) * .08))
  return { scope: 'expansion', title, mode: 'ranges', points: [], ranges,
    start: Math.max(0, ranges[0]!.start - padding), end: Math.min(count - 1, ranges[2]!.end + padding) }
}
