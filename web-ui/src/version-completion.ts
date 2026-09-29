import type { RegroupingRevision, VersionCompletionAudit } from './types'
import { oppositeEvidence } from './expansion-evidence.ts'

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
