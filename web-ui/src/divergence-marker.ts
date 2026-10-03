import type { ChanlunDivergence } from './types'

/** Presentation-only MACD prompts; never append them to structural mmds. */
export function macdPrompts(items: ChanlunDivergence[]) {
  return items.filter(item => item.bc && item.type === 'macd_wave' && item.status === 'confirmed'
    && (item.direction === 'up' || item.direction === 'down')
    && Number.isInteger(item.signal_index) && item.signal_index! >= 0
    && Number.isInteger(item.confirmed_index) && item.confirmed_index! > item.signal_index!
    && item.curr_date && item.confirmed_date)
}

/** Direction, family and lifecycle are separate visual channels. */
export function divergenceMarker(item: ChanlunDivergence) {
  if (!item.bc || item.status === 'superseded') return null
  const candidate = item.status === 'candidate'
  const color = item.direction === 'up' ? '#61dfa0' : '#cf8ff5'
  return {
    symbol: item.type === 'macd' ? 'circle' : 'diamond',
    symbolSize: 9,
    itemStyle: {
      color: candidate ? 'transparent' : color,
      borderColor: color,
      borderWidth: 1.5,
      borderType: candidate ? 'dashed' : 'solid',
    },
    label: { show: false },
  }
}
