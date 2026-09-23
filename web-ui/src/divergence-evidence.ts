import type { ChanlunDivergence } from './types'

export function divergenceName(item: ChanlunDivergence): string {
  const side = item.direction === 'up' ? '顶' : '底'
  if (item.type === 'macd_wave') return `波段${side}背离`
  if (item.type === 'macd') return `双线${side}背离`
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
