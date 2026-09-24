import type { BaseDecomposition } from './types'

export const decompositionRole = (role: string) => ({
  centre_members: '中枢组成段', connector: '中枢间连接段',
  pending_departure: '离开待回试', unassigned: '尚未归属',
} as Record<string, string>)[role] ?? '未知归属'

export function decompositionRange(indices: number[]): string {
  if (!indices.length) return '无来源线段'
  if (indices.length === 1) return `线段 ${indices[0]! + 1}`
  const consecutive = indices.every((value, index) => !index || value === indices[index - 1]! + 1)
  return consecutive ? `线段 ${indices[0]! + 1}–${indices.at(-1)! + 1}`
    : `线段 ${indices.map(value => value + 1).join('、')}`
}

export function decompositionCoverage(data?: BaseDecomposition): string {
  if (!data) return '未提供分解，请重新分析'
  const ids = data.blocks.flatMap(block => block.segment_indices)
  const valid = [data.input_segment_count, data.accepted_segment_count, data.rejected_suffix_count]
    .every(count => Number.isInteger(count) && count >= 0)
    && data.blocks.every(block => block.segment_indices.length > 0)
    && ids.length === data.accepted_segment_count
    && ids.every((id, index) => Number.isInteger(id) && id >= 0 && (!index || id === ids[index - 1]! + 1))
    && data.accepted_segment_count + data.rejected_suffix_count === data.input_segment_count
  if (!valid) return '归属数量或顺序不一致，请重新分析'
  if (data.rejected_suffix_count) return `已覆盖 ${ids.length} 条有效线段；后续 ${data.rejected_suffix_count} 条未纳入`
  return ids.length ? `${ids.length} 条线段 · 无重复、无遗漏` : '暂无已确认线段'
}
