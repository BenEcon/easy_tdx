import type { ExpansionPart, ExpansionPartAudit, RegroupingRevision, VersionCompletionAudit } from './types'
import { oppositeEvidence } from './expansion-evidence.ts'

export function engineeringCompletion(part: ExpansionPart, audit: ExpansionPartAudit, asOf: number) {
  const match = audit.engineering_completion
  const kind = part.component_kind === 'trend_candidate' ? 'trend' : 'consolidation'
  const ids = part.source_segment_indices
  const first = ids[0], last = ids.at(-1)
  const close = (a: number, b: number) => Number.isFinite(a) && Number.isFinite(b)
    && Math.abs(a - b) <= Math.max(1e-8, 1e-9 * Math.max(Math.abs(a), Math.abs(b)))
  if (!match || match.rule !== 'exact_historical_engineering_completion_v1'
    || match.movement_rule !== 'approved_mixed_macd_reverse_v1' || match.status !== 'historical_engineering_match'
    || match.level !== 1 || match.kind !== kind || match.direction !== part.direction
    || match.natural_type_complete !== false || match.eligible_for_recursive_input !== false
    || ids.length < (kind === 'trend' ? 9 : 5) || first === undefined || last === undefined
    || !ids.every((id, i) => Number.isInteger(id) && id >= 0 && id === first + i)
    || !Array.isArray(match.source_segment_indices) || match.source_segment_indices.length !== ids.length
    || !match.source_segment_indices.every((id, i) => id === ids[i])
    || match.movement_id !== `movement:${kind}:L1:${first}:${last}`
    || match.start_index !== part.start_index || match.end_index !== part.end_index
    || !close(match.start_value, part.start_value) || !close(match.end_value, part.end_value)
    || !Number.isInteger(asOf) || match.as_of_index !== asOf || !Number.isInteger(match.known_index)
    || match.known_index < part.known_index || match.known_index > asOf
    || match.known_index !== audit.opposite_known_index || audit.opposite_segment_index !== last + 1
    || match.opposite_id !== `segment:${last + 1}` || !audit.start_is_extreme || !audit.end_is_extreme
    || !match.macd_evidence || !['area_ratio', 'a_dif_extreme', 'a_dea_extreme', 'c_dif_extreme', 'c_dea_extreme']
      .every(key => Number.isFinite(match.macd_evidence[key]))
    || !(match.macd_evidence.area_ratio! > 0 && match.macd_evidence.area_ratio! < 1)) return null
  return match
}

export function versionCompletion(audit: VersionCompletionAudit | undefined, revision: RegroupingRevision, asOf: number, visibleCount: number) {
  if (!audit || audit.rule !== 'version_bound_completion_audit_v1' || audit.interpretation_id !== revision.id
    || !Number.isInteger(asOf) || asOf < revision.known_index || !Number.isInteger(visibleCount) || asOf >= visibleCount
    || audit.as_of_index !== asOf || audit.natural_type_complete !== false || audit.eligible_for_recursive_input !== false
    || !Array.isArray(audit.blocking_reasons) || !audit.blocking_reasons.includes('same_level_completion_unproven')
    || !Array.isArray(audit.parts) || audit.parts.length !== revision.parts.length) return null
  for (const [i, part] of revision.parts.entries()) {
    const a = audit.parts[i]
    const startExtreme = part.direction === 'up' ? part.low : part.high
    const endExtreme = part.direction === 'up' ? part.high : part.low
    const close = (x: number, y: number) => Math.abs(x - y) <= Math.max(1e-8, 1e-9 * Math.max(Math.abs(x), Math.abs(y)))
    if (!a || a.part_index !== i || a.natural_type_complete !== false
      || !Number.isInteger(part.known_index) || part.known_index > revision.known_index
      || a.source_segment_indices.length !== part.source_segment_indices.length
      || !a.source_segment_indices.every((id, at) => id === part.source_segment_indices[at])
      || !Array.isArray(a.blocking_reasons) || !a.blocking_reasons.includes('same_level_completion_unproven')
      || !Number.isFinite(a.start_extreme) || !Number.isFinite(a.end_extreme)
      || a.start_extreme !== startExtreme || a.end_extreme !== endExtreme
      || a.start_is_extreme !== close(part.start_value, startExtreme)
      || a.end_is_extreme !== close(part.end_value, endExtreme)) return null
    const conflict = !a.start_is_extreme || !a.end_is_extreme
    const hasReverse = a.opposite_segment_index !== null
    if (a.status !== (conflict ? 'endpoint_conflict' : hasReverse ? 'awaiting_same_level_completion' : 'awaiting_opposite_lower_unit')) return null
    if (hasReverse) {
      if (!oppositeEvidence(revision, part, a, asOf + 1)) return null
    } else if (a.opposite_known_index !== null || a.opposite_evidence != null) return null
  }
  if (!revision.parts.length && !audit.blocking_reasons.includes('no_current_partition')) return null
  if (revision.higher_proof_ids.length && (revision.parts.length || !audit.blocking_reasons.includes('higher_proof_requires_regrouping'))) return null
  if (revision.retained_prefix_segment_indices?.length && !audit.blocking_reasons.includes('retained_prefix_unresolved')) return null
  return audit
}
