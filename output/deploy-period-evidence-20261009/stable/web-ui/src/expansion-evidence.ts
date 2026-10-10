import type { ExpansionAudit, ExpansionCandidate, ExpansionPart, ExpansionPartAudit, ExpansionRegrouping } from './types'

export function expansionStatus(status: string): string {
  return ({
    awaiting_centre_exit: '等待两中枢退出',
    requires_higher_level_inputs: '需要更高层级输入',
    no_three_range_partition: '未找到有效三段切分',
    partition_found_awaiting_type_completion: '已有切分 · 自然完成待证',
  } as Record<string, string>)[status] ?? '状态待核验'
}

export function partitionSelection(selection?: string | null): string {
  return ({
    endpoint_consistent_preferred: '优先选择端点一致的切分',
    geometric_fallback_with_conflicts: '无端点一致解，保留几何切分及冲突',
  } as Record<string, string>)[selection ?? ''] ?? '此结果未提供切分优选依据'
}

export function completionStatus(status?: string): string {
  return ({
    endpoint_conflict: '端点与区间极值冲突',
    awaiting_same_level_completion: '反向基础线段已确认 · 同级别完成待证',
    awaiting_opposite_lower_unit: '等待反向基础线段',
  } as Record<string, string>)[status ?? ''] ?? '完成依据未提供或不匹配'
}

export function completionReason(reason: string): string {
  return ({
    start_not_directional_extreme: '起点不是该方向的区间极值',
    end_not_directional_extreme: '终点不是该方向的区间极值',
    no_confirmed_opposite_lower_unit: '尚无已确认的反向基础线段',
    same_level_completion_unproven: '缺少同级别自然走势完成证明',
    no_current_partition: '当前版本尚无可用分区',
    higher_proof_requires_regrouping: '高层证明需要整体重组，不能沿用旧分区',
    retained_prefix_unresolved: '保留前缀的自然归属仍待确定',
    source_cover_conflict: '来源覆盖存在冲突',
    indivisible_proof_crosses_boundary: '完整高层证明跨越当前归属边界',
  } as Record<string, string>)[reason] ?? '存在未识别的核验条件，请重新分析'
}

export function evidencePrice(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '未提供'
}

export function evidenceRange(range?: number[] | null): string {
  return range?.length === 2 && range.every(Number.isFinite) && range[0]! <= range[1]!
    ? `${evidencePrice(range[0])}–${evidencePrice(range[1])}` : '未形成'
}

export function candidateAudit(data: ExpansionRegrouping | undefined, candidate: ExpansionCandidate) {
  return data?.completion_audits?.find(audit => audit.candidate_id === candidate.id)
}

export function matchingPartAudit(audit: ExpansionAudit | undefined, part: ExpansionPart, index: number) {
  // Evidence belongs to source IDs, never simply to an array position.
  return audit?.parts.find(item => item.part_index === index
    && item.source_segment_indices.length === part.source_segment_indices.length
    && item.source_segment_indices.every((id, at) => id === part.source_segment_indices[at]))
}

export function oppositeEvidence(candidate: Pick<ExpansionCandidate, 'parts' | 'source_segment_indices'>, part: ExpansionPart,
  audit: ExpansionPartAudit | undefined, visibleCount: number) {
  const evidence = audit?.opposite_evidence
  const index = (value: unknown): value is number => typeof value === 'number'
    && Number.isInteger(value) && value >= 0
  if (!evidence || !index(visibleCount) || !index(evidence.segment_index)
    || evidence.segment_index !== audit?.opposite_segment_index
    || evidence.known_index !== audit?.opposite_known_index
    || !index(evidence.start_index) || !index(evidence.end_index) || !index(evidence.known_index)
    || evidence.start_index !== part.end_index || evidence.end_index <= evidence.start_index
    || evidence.known_index < evidence.end_index || evidence.known_index >= visibleCount
    || evidence.known_index < part.known_index
    || !Number.isFinite(evidence.start_value) || !Number.isFinite(evidence.end_value)
    || evidence.start_value !== part.end_value
    || evidence.direction !== (part.direction === 'up' ? 'down' : 'up')
    || (evidence.direction === 'up' ? evidence.end_value <= evidence.start_value : evidence.end_value >= evidence.start_value)
    || evidence.segment_index !== part.source_segment_indices.at(-1)! + 1) return null
  const owners = candidate.parts.flatMap((item, at) => item.source_segment_indices.includes(evidence.segment_index) ? [at] : [])
  if (owners.length > 1) return null
  const owner = owners[0] ?? null
  if (owner !== evidence.source_part_index
    || (owner === null && evidence.segment_index !== candidate.source_segment_indices.at(-1)! + 1)) return null
  return { ...evidence, sourceLabel: owner === null
    ? '位于候选来源之后，不计入 A/B/C 组成'
    : `属于分区 ${String.fromCharCode(65 + owner)}，不是额外独立的完成依据` }
}
