import type { ChanlunDivergence } from './types'

/** A display subtype, not a second event or a relaxed wave-divergence rule. */
export function isSpecialDualLine(item: ChanlunDivergence) {
  return item.type === 'macd' && item.evidence?.special_no_c === 1
    && (item.direction === 'up' || item.direction === 'down')
}

/** Preserve independently inspectable families, excluding inactive events only. */
export function visibleDivergences(items: ChanlunDivergence[], history = false) {
  const active = items.filter(item => item.bc && (history || item.status !== 'superseded'))
  // Different families/statuses must remain individually inspectable. The chart
  // offsets overlapping marks; the evidence list retains every source record.
  return active
}

/** Presentation-only MACD prompts; never append them to structural mmds. */
export function macdPrompts(items: ChanlunDivergence[]) {
  return items.filter(item => item.bc && item.type === 'macd_wave' && item.status === 'confirmed'
    && (item.direction === 'up' || item.direction === 'down')
    && Number.isInteger(item.signal_index) && item.signal_index! >= 0
    && Number.isInteger(item.confirmed_index) && item.confirmed_index! > item.signal_index!
    && item.curr_date && item.confirmed_date)
}

/** Direction, family and lifecycle are separate visual channels. */
export function divergenceMarker(item: ChanlunDivergence, history = false) {
  if (!item.bc || item.status === 'superseded' && !history) return null
  const inactive = item.status === 'superseded'
  const candidate = item.status !== 'confirmed'
  const special = item.type === 'macd_wave_special'
  const reversePen = special || item.type === 'macd' && [20261004, 2026100414].includes(item.evidence?.rule_version ?? 0)
  // A special diamond can fill only with a later, recorded reverse-pen witness.
  const hollow = inactive || (reversePen ? !(item.status === 'confirmed'
    && Number.isInteger(item.signal_index) && item.signal_index! >= 0
    && Number.isInteger(item.confirmed_index) && item.confirmed_index! > item.signal_index!
    && item.evidence?.reverse_pen_start === item.signal_index
    && item.evidence?.reverse_pen_confirmed === item.confirmed_index) : candidate)
  const color = inactive ? '#8e949e' : item.direction === 'up' ? '#61dfa0' : '#cf8ff5'
  return {
    symbol: item.type === 'macd' ? 'circle' : item.type === 'macd_wave_nonstandard' ? 'triangle' : 'diamond',
    symbolSize: special ? 13 : 9,
    itemStyle: {
      color: hollow ? 'transparent' : color,
      borderColor: color,
      borderWidth: 1.5,
      borderType: hollow ? 'dashed' : 'solid',
      opacity: inactive ? .5 : 1,
    },
    label: { show: false },
  }
}
