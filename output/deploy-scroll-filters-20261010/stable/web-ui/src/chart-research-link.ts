import type { Bar } from './types'

export type TimeWindow = { start: string; end: string }
export type PlotRect = { x: number; y: number; width: number; height: number }
/** Quiet time coverage, clipped per plot so legends and inter-panel gaps stay clear. */
export function timeLinkGraphic(rect: PlotRect, first: number, last: number, count: number, halfBand: number) {
  if (![rect.x, rect.y, rect.width, rect.height, first, last, halfBand].every(Number.isFinite)
    || rect.width <= 0 || rect.height <= 0 || count < 1) return null
  const edge = rect.x + rect.width
  if (count === 1) {
    if (first < rect.x || first > edge) return null
    return { type: 'line', silent: true, z: 3,
      shape: { x1: first, x2: first, y1: rect.y, y2: rect.y + rect.height },
      style: { stroke: 'rgba(134,178,222,.32)', lineWidth: 1 } }
  }
  const x = Math.max(rect.x, Math.min(first, last) - Math.max(0, halfBand))
  const end = Math.min(edge, Math.max(first, last) + Math.max(0, halfBand))
  if (end <= x) return null
  return { type: 'rect', silent: true, z: 1,
    shape: { x, y: rect.y, width: end - x, height: rect.height },
    style: { fill: 'rgba(134,178,222,.065)', lineWidth: 0 } }
}
export const stamp = (value: string) => value.replace('T', ' ').slice(0, 19)
/** Match exchange-local intervals, never ordinal indices across different periods. */
export function barWindow(bar: Bar, category = ''): TimeWindow {
  let start = stamp(bar.datetime)
  const period = category.toUpperCase()
  // Providers may label weekly/monthly candles by their last trading day.
  // Calendar starts are only display coverage; do not invent constituent bars.
  if (period === 'WEEK') {
    const day = new Date(`${start.slice(0, 10)}T00:00:00Z`)
    day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7)
    if (Number.isFinite(day.getTime())) start = `${day.toISOString().slice(0, 10)} 00:00:00`
  } else if (period === 'MONTH') start = `${start.slice(0, 7)}-01 00:00:00`
  return { start, end: stamp(bar.period_end ?? bar.datetime) }
}
export function overlappingBars(bars: Bar[], window: TimeWindow, category = ''): number[] {
  return bars.flatMap((bar, index) => {
    const range = barWindow(bar, category)
    // Adjacent minute bars share an endpoint, but are not the same interval.
    const hit = range.start === window.start || (range.start < window.end && range.end > window.start)
    return hit ? [index] : []
  })
}
export type MarkerCandidate<T> = { value: T; center: number[]; size: number[] }
export function nearestMarkers<T>(items: MarkerCandidate<T>[], x: number, y: number): T[] {
  const hits = items.filter(item => [...item.center, ...item.size, x, y].every(Number.isFinite)
    && Math.abs(x - item.center[0]!) <= Math.max(5, item.size[0]! / 2) + 2
    && Math.abs(y - item.center[1]!) <= Math.max(5, item.size[1]! / 2) + 2)
    .sort((a, b) => Math.hypot(x - a.center[0]!, y - a.center[1]!) - Math.hypot(x - b.center[0]!, y - b.center[1]!))
  const nearest = hits[0]
  if (!nearest) return []
  // Only co-located symbols share a chooser; nearby unrelated points do not steal hits.
  return hits.filter(item => Math.hypot(item.center[0]! - nearest.center[0]!, item.center[1]! - nearest.center[1]!) <= 2).map(item => item.value)
}
