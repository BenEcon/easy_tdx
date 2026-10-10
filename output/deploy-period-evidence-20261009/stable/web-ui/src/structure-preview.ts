import type { Bar, ChanlunBi } from './types'

/** Presentation only: a reverse excursion, never a strict pen or future forecast. */
export function nextPenPreview(bars: (Pick<Bar, 'datetime' | 'high' | 'low'> & { is_closed?: boolean })[], bis: ChanlunBi[]) {
  const pen = bis.at(-1)
  if (!pen) return null
  const normalize = (date: string) => date.replace('T', ' ').replace(/ 00:00(?::00)?$/, '').replace(/(\d{2}:\d{2}):00$/, '$1')
  const matches = bars.flatMap((bar, index) => normalize(bar.datetime) === normalize(pen.end_date) ? [index] : [])
  if (matches.length !== 1) return null
  const start = matches[0]!
  const price = pen.end_value ?? (pen.direction === 'up' ? pen.high : pen.low)
  if (!Number.isFinite(price) || start >= bars.length - 1) return null
  const down = pen.direction === 'up'
  let end = -1, endPrice = price
  for (let index = start + 1; index < bars.length; index++) {
    const bar = bars[index]!
    if (bar.is_closed === false) break
    if (!Number.isFinite(bar.high) || !Number.isFinite(bar.low) || bar.low > bar.high) return null
    // Do not invent an anchored reversal while the current pen is extending.
    if (down ? bar.high > price : bar.low < price) return null
    const value = down ? bar.low : bar.high
    if (down ? value < endPrice : value > endPrice) { end = index; endPrice = value }
  }
  return end < 0 ? null : { start, end, startPrice: price, endPrice, direction: down ? 'down' : 'up' }
}

export function consolidationAppearance(confirmed: boolean) {
  return {
    itemStyle: {
      color: confirmed ? 'rgba(137,173,198,.035)' : 'rgba(210,169,108,.075)',
      borderColor: confirmed ? 'rgba(155,189,211,.65)' : '#d2a96c',
      borderWidth: confirmed ? 1 : 1.25,
      borderType: confirmed ? 'solid' as const : 'dashed' as const,
    },
    label: { color: confirmed ? '#9dbbce' : '#e0bb84' },
  }
}
