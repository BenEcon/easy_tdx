import type { RegroupingCase, RegroupingVersions } from './types'

export function regroupingStatus(status: string): string {
  return ({
    endpoint_consistent_draft: '端点一致 · 自然完成待证',
    endpoint_conflict_draft: '仍有端点冲突',
    awaiting_partition: '等待可用切分',
    requires_higher_level_inputs: '优先保留升级结构 · 等待混合层级重组',
  } as Record<string, string>)[status] ?? '状态待核验'
}

export function regroupingReason(reason: string): string {
  return ({
    initial_interpretation: '初次解释',
    higher_centre_priority: '升级结构优先',
    endpoint_conflicts_resolved: '新证据消除端点冲突',
    later_boundary_regrouping: '后续边界重组',
    start_boundary_regrouping: '起点重新归属 · 前缀保留待核验',
  } as Record<string, string>)[reason] ?? '变化原因待核验'
}

function same(a: number[] | undefined, b: number[]): boolean {
  return Array.isArray(a) && a.length === b.length && a.every((value, i) => value === b[i])
}

function continuous(ids: number[]): boolean {
  return ids.every((id, i) => Number.isInteger(id) && id >= 0 && (!i || id === ids[i-1]! + 1))
}

/** V2 may detach sources, but never lose or silently certify the detached prefix. */
function validOwnership(item: RegroupingCase): boolean {
  const origin = item.origin_start_segment_index, anchors = item.start_anchor_segment_indices
  if (origin === undefined || !anchors?.length || anchors[0] !== origin || !continuous(anchors)) return false
  let previousStart = origin
  for (const revision of item.revisions) {
    const prefix = revision.retained_prefix_segment_indices, sources = revision.source_segment_indices
    if (!Array.isArray(prefix) || !sources?.length || revision.prefix_role !== 'unresolved_prior_sources') return false
    const all = [...prefix, ...sources], start = sources[0]!
    if (all[0] !== origin || !continuous(all) || !anchors.includes(start)) return false
    const change = revision.start_change
    if (previousStart === start) {
      if (change !== null) return false
    } else if (!change || change.previous_start_segment_index !== previousStart
      || change.current_start_segment_index !== start
      || !same(change.detached_segment_indices, all.filter(id => id >= previousStart && id < start))
      || !same(change.reincorporated_segment_indices, all.filter(id => id >= start && id < previousStart))) return false
    previousStart = start
  }
  const current = item.revisions.at(-1)!
  return Array.isArray(item.pending_segment_indices)
    && continuous([...current.source_segment_indices, ...item.pending_segment_indices])
}

/** Do not show a full-snapshot ledger inside an earlier replay or another case. */
export function visibleRegroupingCase(data: RegroupingVersions | undefined, id: string, count: number) {
  if (!data || !['causal_regrouping_versions_v1', 'causal_regrouping_versions_v2', 'causal_regrouping_versions_v3'].includes(data.rule)
    || !Number.isInteger(count) || count <= 0) return null
  const matches = data.cases.filter(c => c.candidate_id === id)
  if (matches.length !== 1) return null
  const item = matches[0]!
  const at = (n: number) => Number.isInteger(n) && n >= 0 && n < count
  if (!at(item.as_of_index) || !at(item.formation_known_index) || !item.revisions.length) return null
  if (item.current_revision_id !== item.revisions.at(-1)?.id) return null
  for (let i = 0; i < item.revisions.length; i++) {
    const revision = item.revisions[i]!, previous = item.revisions[i - 1]
    if (revision.id !== `${id}:v${i + 1}` || revision.version !== i + 1
      || revision.supersedes !== (previous?.id ?? null) || !at(revision.known_index)
      || revision.known_index < item.formation_known_index || revision.known_index > item.as_of_index
      || (previous && revision.known_index <= previous.known_index)
      || revision.natural_type_complete !== false || revision.eligible_for_recursive_input !== false) return null
  }
  if (data.rule !== 'causal_regrouping_versions_v1' && !validOwnership(item)) return null
  return item
}
