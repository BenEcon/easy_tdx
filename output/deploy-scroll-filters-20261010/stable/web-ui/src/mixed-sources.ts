import type { MixedSourceCover } from './types'

const roles: Record<string, string> = {
  retained_prefix: '保留前缀', unresolved_selection: '候选来源',
  part_0: 'A 分区', part_1: 'B 分区', part_2: 'C 分区', pending_tail: '待定尾部',
}
export const sourceRole = (role: string) => roles[role] ?? '归属待核验'
const same = (a: number[], b: number[]) => Array.isArray(a) && a.length === b.length && a.every((x, i) => x === b[i])
const chain = (a: number[]) => Array.isArray(a) && a.length > 0 && a.every((x, i) => Number.isInteger(x) && x >= 0 && (!i || x === a[i - 1]! + 1))

/** Optional evidence must match the current interpretation and visible snapshot. */
export function visibleMixedCover(data: MixedSourceCover | undefined, id: string, expected: number[], asOf: number, count: number): MixedSourceCover | null {
  if (!data || data.rule !== 'indivisible_source_cover_v1' || data.interpretation_id !== id
    || !Number.isInteger(count) || count <= 0 || !Number.isInteger(asOf) || asOf < 0 || asOf >= count
    || data.as_of_index !== asOf || !chain(expected) || !same(data.source_segment_indices, expected)
    || data.natural_type_complete !== false || data.eligible_for_recursive_input !== false
    || !Array.isArray(data.blocks) || !Array.isArray(data.conflicts)) return null
  const known = (x: number) => Number.isInteger(x) && x >= 0 && x <= asOf
  if (data.status === 'blocked') {
    return !data.blocks.length && data.joint_regrouping_required === true && data.conflicts.length > 0
      && data.conflicts.every(c => ['proof_crosses_window', 'overlapping_proofs'].includes(c.reason)
        && typeof c.proof_id === 'string' && c.proof_id.length > 0 && chain(c.source_segment_indices) && known(c.known_index)) ? data : null
  }
  if (data.status !== 'covered' || data.conflicts.length || !same(data.blocks.flatMap(b => b.source_segment_indices), expected)) return null
  for (const b of data.blocks) {
    if (!chain(b.source_segment_indices) || !known(b.known_index) || b.natural_type_complete !== false
      || !Number.isFinite(b.low) || !Number.isFinite(b.high) || b.low > b.high
      || !Array.isArray(b.role_spans) || !b.role_spans.length
      || !b.role_spans.every(s => Object.hasOwn(roles, s.role) && chain(s.source_segment_indices))
      || !same(b.role_spans.flatMap(s => s.source_segment_indices), b.source_segment_indices)
      || b.crosses_role_boundary !== (b.role_spans.length > 1)) return null
    if (b.kind === 'base_run') {
      if (b.level !== 0 || b.proof_id !== null || b.crosses_role_boundary) return null
    } else if (b.kind !== 'extension_proof' || !Number.isInteger(b.level) || b.level < 2
      || b.source_segment_indices.length !== 3 ** b.level
      || b.proof_id !== `extension:L${b.level}:${b.source_segment_indices[0]}:${b.source_segment_indices.at(-1)}`) return null
  }
  return data.joint_regrouping_required === data.blocks.some(b => b.crosses_role_boundary) ? data : null
}
