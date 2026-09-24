import type { ChanlunDivergence, ChanlunSignal } from './types'

export function signalEvidence(signal: ChanlunSignal): string[] {
  const e = signal.evidence ?? {}
  const lines = ['规则：已确认线段构成的基础结构；不是按图表周期推定的高级别结构。']
  for (const [key, title] of [['first_segment', '前置一类点线段'], ['rebound_segment', '反弹／回落线段'],
    ['departure_segment', '离开线段'], ['return_segment', '回试线段'], ['a_segment', 'A 段'], ['c_segment', 'C 段']]) {
    const value = e[key!]
    if (typeof value === 'number') lines.push(`${title}：${value + 1}`)
  }
  if (typeof e.centre_segment_count === 'number') lines.push(`中枢构成：${e.centre_segment_count} 条线段`)
  if (typeof e.zd === 'number' && typeof e.zg === 'number') lines.push(`固定核心：${e.zd.toFixed(2)} — ${e.zg.toFixed(2)}`)
  if (typeof e.area_ratio === 'number') lines.push(`MACD 柱面积 C/A：${(e.area_ratio * 100).toFixed(2)}%`)
  if (e.first_return) lines.push('首次回试已完成，未重新进入中枢。')
  if (e.strength === 'weak_new_extreme') lines.push('弱二类：回试突破首个极值；策略默认过滤。')
  lines.push(`极值位置：${signal.date ?? '—'}；可用时间：${signal.confirmed_date ?? '未确认'}`)
  return lines
}

export function divergenceName(item: ChanlunDivergence): string {
  const side = item.direction === 'up' ? '顶' : '底'
  if (item.type === 'macd_wave') return `波段${side}背离`
  if (item.type === 'macd') return `双线${side}背离`
  if (item.type === 'pz') return `盘整力度${side}背驰`
  return `趋势${side}背驰`
}

export function divergenceEvidence(item: ChanlunDivergence): string[] {
  const e = item.evidence ?? {}
  const dates = item.intervals ?? {}
  const lines: string[] = []
  for (const segment of ['a', 'b', 'c']) {
    if (dates[`${segment}_start`]) lines.push(`${segment.toUpperCase()} 段：${dates[`${segment}_start`]} — ${dates[`${segment}_end`]}`)
  }
  const pairs = [['价格极值', 'previous_price', 'price'], ['DIF', 'previous_dif', 'dif'],
    ['DEA', 'previous_dea', 'dea'], ['柱面积 A → C', 'a_area', 'c_area'],
    ['段内 DIF 极值 A → C', 'a_dif_extreme', 'c_dif_extreme'],
    ['段内 DEA 极值 A → C', 'a_dea_extreme', 'c_dea_extreme']]
  for (const [label, before, after] of pairs) {
    if (Number.isFinite(e[before!]) && Number.isFinite(e[after!])) {
      lines.push(`${label}：${e[before!]!.toFixed(2)} → ${e[after!]!.toFixed(2)}`)
    }
  }
  if (Number.isFinite(e.area_ratio)) lines.push(`面积比 C/A：${(e.area_ratio! * 100).toFixed(2)}%`)
  lines.push(`首次提示：${item.detected_date ?? '—'}；确认：${item.confirmed_date ?? '尚未确认'}`)
  return lines
}
