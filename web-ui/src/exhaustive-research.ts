import type { ReleasedRecursion } from './types'
import { releaseEvidence } from './released-evidence'

export interface SearchSolution { id: string; ordinal: number; solution_token: string; snapshot: ReleasedRecursion }
export interface SearchPage {
  scope: string; fingerprint: string; complete: boolean; next_cursor: string | null
  emitted: number; results: SearchSolution[]; eligible_for_trading: false; theory_equivalence_claim: false
  coverage: string; historical_data_vintage: false
}
export interface AuditAttempt {
  kind: string; level: number; source_first: number; source_last: number; known_index: number
  outcome: string; reason: string | null; details: Record<string, unknown>; selection?: string
  macd_checks: { gate: string; passed: boolean; values: Record<string, unknown> }[]
  confirmed_index?: number; ownership_checks?: unknown[]
}
export interface CandidateAudit {
  scope: string; fingerprint: string; interpretation: string; total_attempts: number; offset: number
  next_offset: number | null; attempts: AuditAttempt[]; summary: Record<string, number>
  input: { accepted_segment_count: number; rejected_suffix_count: number; input_rejections: {reason: string; position: number}[];
    chain_boundaries: {level: number; left_source: number; right_source: number; reason: string}[] }
  eligible_for_trading: false; as_of_index: number
}
export function validSearchPage(p: SearchPage, total: number, before: number, identity?: string): boolean {
  try {
    return p.scope === 'fixed_base_all_candidate_subsets_v1' && p.eligible_for_trading === false
      && p.theory_equivalence_claim === false && p.historical_data_vintage === false
      && p.coverage === 'all_disjoint_subsets_on_fixed_base_including_unresolved'
      && typeof p.fingerprint === 'string' && !!p.fingerprint && (!identity || p.fingerprint === identity)
      && typeof p.complete === 'boolean' && (p.complete ? p.next_cursor === null : typeof p.next_cursor === 'string' && !!p.next_cursor)
      && p.results.length > 0 && p.results.length <= 8 && p.emitted === before + p.results.length
      && new Set(p.results.map(r => r.id)).size === p.results.length
      && p.results.every((r, i) => r.ordinal === before + i + 1 && !!r.id && !!r.solution_token && !!releaseEvidence(r.snapshot, total))
  } catch { return false }
}
export function validAudit(a: CandidateAudit, total: number, offset: number, identity?: string): boolean {
  try {
    const index = (n: number) => Number.isSafeInteger(n) && n >= 0
    return a.scope === 'actual_candidate_gate_trace_v1' && a.eligible_for_trading === false
      && ['default', 'solution'].includes(a.interpretation) && typeof a.fingerprint === 'string' && !!a.fingerprint
      && a.as_of_index === total - 1 && a.offset === offset && (!identity || a.fingerprint === identity)
      && Number.isSafeInteger(a.total_attempts) && a.total_attempts >= offset
      && a.attempts.length === Math.min(50, a.total_attempts - offset)
      && a.next_offset === (offset + a.attempts.length < a.total_attempts ? offset + a.attempts.length : null)
      && Object.values(a.summary).reduce((x, y) => x + y, 0) === a.total_attempts
      && Object.values(a.summary).every(index)
      && index(a.input.accepted_segment_count) && index(a.input.rejected_suffix_count)
      && a.input.input_rejections.every(r => index(r.position) && typeof r.reason === 'string')
      && a.input.chain_boundaries.every(r => index(r.level) && index(r.left_source) && index(r.right_source) && typeof r.reason === 'string')
      && a.attempts.every(r => ['candidate', 'rejected', 'pending'].includes(r.outcome)
        && index(r.level) && r.level > 0 && index(r.source_first) && index(r.source_last) && r.source_last >= r.source_first
        && index(r.known_index) && r.known_index < total && r.details !== null && typeof r.details === 'object'
        && (r.outcome === 'candidate' ? r.reason === null : typeof r.reason === 'string')
        && new Set(r.macd_checks.map(g => g.gate)).size === r.macd_checks.length
        && r.macd_checks.every(g => Object.hasOwn(gates, g.gate) && typeof g.passed === 'boolean' && g.values !== null && typeof g.values === 'object'))
  } catch { return false }
}
export const reasons: Record<string, string> = {
  candidate_formed: '已形成候选', reverse_not_yet_confirmed: '等待相邻反向结构确认',
  no_following_centre_units: '尚无后续结构用于形成中枢', macd_series_missing: '缺少 MACD 序列',
  start_extreme_irrecoverable: '起点极值已失效，后续不能修复', invalidated_start_suffix: '此起点已失效，后续窗口不再生成候选',
  multiple_centres_in_consolidation: '存在多个中枢，不满足盘整候选条件', centre_not_immediately_after_entry: '中枢未紧接进入段',
  centre_upgraded: '中枢发生升级', same_batch_structure_invalidated: '同批结构证据使候选失效',
  next_unit_not_opposite: '相邻结构不是反向确认', start_not_directional_extreme: '起点不是方向极值',
  structure_gates_not_met: '结构条件未齐备', macd_gates_not_met: 'MACD 或价格条件未通过',
  centres_not_separated: '两个中枢未严格分离', end_not_directional_extreme: '终点不是方向极值',
  missing_matching_entry: '缺少匹配进入段', confirmation_unavailable: '基础线段尚未确认',
  invalid_source_indices: '基础线段索引无效', invalid_source_geometry: '基础线段价格结构无效',
  invalid_raw_anchor_order: '原始 K 线锚点顺序无效', source_chain_disconnected: '基础线段链不连续',
  unresolved_source_gap: '存在未完成来源缺口，不能跨越拼接',
  protected_promoted_sources: '来源已归属升级中枢，不能降级使用',
}
export const gates: Record<string, string> = {
  ordered_complete_intervals: 'A / C 区间完整且有序', dif_finite_coverage: 'DIF 数据完整', dea_finite_coverage: 'DEA 数据完整',
  hist_finite_coverage: '柱体数据完整', strict_price_extreme: '价格严格创新极值', shrinking_same_colour_area: '同色柱面积缩小',
  dif_extreme_and_zero_axis: 'DIF 极值与零轴条件', dif_centre_pullback: 'DIF 中枢回拉',
  dea_extreme_and_zero_axis: 'DEA 极值与零轴条件', dea_centre_pullback: 'DEA 中枢回拉',
}
const fields: Record<string, string> = {
  centre_exists: '存在中枢', centre_departed: '已离开中枢', current_is_departure: '当前结构为离开段', same_direction: '方向一致',
  end_is_extreme: '终点为极值', two_centres: '存在两个中枢', centre_count: '中枢数', unit_index: '结构索引',
  failed_at_index: '首次失效位置', a_price: 'A 段价格', c_price: 'C 段价格', tolerance: '容差', a_area: 'A 段面积', c_area: 'C 段面积',
  a_extreme: 'A 段极值', c_extreme: 'C 段极值', pullback: '回拉值', direction: '方向',
  a_start: 'A 起点', a_end: 'A 终点', c_start: 'C 起点', c_end: 'C 终点', bar_count: 'K 线数',
  length: '数据长度', required_end: '所需末端索引', start_value: '起点价格', end_value: '终点价格',
  low: '区间最低', high: '区间最高', zd: '中枢下沿', zg: '中枢上沿', invalidated_index: '失效索引',
  expected_entry_index: '所需进入段索引', a_dif_extreme: 'A 段 DIF 极值', c_dif_extreme: 'C 段 DIF 极值',
  a_dea_extreme: 'A 段 DEA 极值', c_dea_extreme: 'C 段 DEA 极值', area_ratio: 'C / A 面积比',
}
export function detailText(values: Record<string, unknown>): string {
  return Object.entries(values).map(([key, value]) => `${fields[key] ?? key}：${typeof value === 'boolean' ? value ? '通过' : '未满足' : typeof value === 'number' ? Number(value.toFixed(6)) : typeof value === 'object' ? JSON.stringify(value) : String(value)}`).join(' · ')
}
