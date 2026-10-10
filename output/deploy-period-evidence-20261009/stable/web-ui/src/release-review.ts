import type { ReleasedRecursion } from './types'
import { releaseEvidence } from './released-evidence.ts'

export function releaseBlockers(data: ReleasedRecursion, id: string, total: number) {
  const evidence = releaseEvidence(data, total), record = evidence?.records.get(id)
  if (!record) return []
  const ids = new Set([...record.required_domain_ids, ...record.current_placement.enclosing_domain_ids,
    ...record.current_placement.conflicts.map(c => c.domain_id)])
  return [...ids].map(domainId => {
    const domain = evidence!.domains.get(domainId)!
    const queue = [{record, path: [record.id]}], seen = new Set<string>()
    let path = [record.id]
    while (queue.length) {
      const node = queue.shift()!
      if (seen.has(node.record.id)) continue
      seen.add(node.record.id)
      if ([...node.record.current_placement.enclosing_domain_ids,
        ...node.record.current_placement.conflicts.map(c => c.domain_id)].includes(domainId)) {
        path = node.path; break
      }
      for (const childId of [...node.record.child_ids, node.record.opposite_id]) {
        const child = evidence!.records.get(childId)
        if (child?.required_domain_ids.includes(domainId)) queue.push({record: child, path: [...node.path, childId]})
      }
    }
    return {domainId, sources: domain.source_segment_indices, requiredLevel: domain.required_parent_level,
      currentLevel: record.level, missingSources: domain.source_segment_indices.filter(s => !record.source_segment_indices.includes(s)),
      path: path.map(identity => ({id: identity, level: evidence!.records.get(identity)!.level,
        sources: evidence!.records.get(identity)!.source_segment_indices}))}
  })
}

export interface ReleaseHistoryState {
  kind: 'movement' | 'domain'; level?: number; required_parent_level?: number
  source_segment_indices: number[]; status?: string; released_by_id?: string | null
  eligible_for_external_recursion?: boolean; represented_by_id?: string | null
  current_placement?: { reason: string | null }
}
export interface ReleaseHistoryEvent {
  id: string; index: number; date: string; change: 'added' | 'changed' | 'removed'
  before: ReleaseHistoryState | null; after: ReleaseHistoryState | null
}
export interface ReleaseHistoryBatch {
  scope: 'raw_prefix_release_history_v1'; start_count: number; end_count: number
  historical_data_vintage: false; eligible_for_trading: false; events: ReleaseHistoryEvent[]
}
export interface ReleaseComparison {
  scope: 'bounded_selection_comparison_v1'; exhaustive: false; default_policy: 'earliest'
  eligible_for_trading: false; historical_data_vintage: false
  variants: { policy: 'earliest' | 'widest' | 'latest'; snapshot: ReleasedRecursion }[]
}
export function historyStateLabel(state: ReleaseHistoryState | null) {
  if (!state) return '本前缀中不存在'
  if (state.kind === 'domain') return state.status === 'released_by_parent' ? '整区已由父走势覆盖释放' : '归属区约束保留'
  if (state.eligible_for_external_recursion) return '外部可用'
  if (state.represented_by_id) return '由父走势代表／内部依据'
  return '局部完成，仍受约束'
}

export function validHistoryBatch(batch: ReleaseHistoryBatch, start: number, end: number): boolean {
  try {
    return batch.scope === 'raw_prefix_release_history_v1' && batch.start_count === start
      && batch.end_count === end && batch.historical_data_vintage === false && batch.eligible_for_trading === false
      && batch.events.every((event, i) => Number.isSafeInteger(event.index)
        && event.index >= start - 1 && event.index < end && typeof event.date === 'string'
        && typeof event.id === 'string' && event.id.length > 0
        && ['added', 'removed', 'changed'].includes(event.change)
        && (event.change === 'added' ? event.before === null && event.after !== null
          : event.change === 'removed' ? event.before !== null && event.after === null
          : event.before !== null && event.after !== null)
        && (!i || batch.events[i - 1]!.index <= event.index)
        && [event.before, event.after].every(state => state === null || (
          ['movement', 'domain'].includes(state.kind) && state.source_segment_indices.length > 0
          && state.source_segment_indices.every((s, j, xs) => Number.isSafeInteger(s) && s >= 0 && (!j || s === xs[j - 1]! + 1)))))
  } catch { return false }
}
