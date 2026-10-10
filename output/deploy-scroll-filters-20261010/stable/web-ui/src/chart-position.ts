import type { Bar } from './types'

const minute = (value: string) => value.replace('T', ' ').slice(0, 16)

/** Explicit raw positions are authoritative. Legacy dates must match uniquely. */
export function chartBarIndex(bars: Pick<Bar, 'datetime'>[], date: string | null,
  index?: number | null): number | null {
  if (index != null) return Number.isInteger(index) && index >= 0 && index < bars.length ? index : null
  if (!date) return null
  const normalized = minute(date)
  const matches = bars.flatMap((bar, i) => {
    const value = minute(bar.datetime)
    return (normalized.length === 10 ? value.slice(0, 10) === normalized : value === normalized) ? [i] : []
  })
  return matches.length === 1 ? matches[0]! : null
}

/** Reserve space for markers offset up to 23px in the 342px price pane. */
export function priceAxisPadding(extent: {min: number; max: number}): number {
  if (!Number.isFinite(extent.min) || !Number.isFinite(extent.max) || extent.max < extent.min) return 0
  return Math.max((extent.max - extent.min) * .12, Math.max(Math.abs(extent.min), Math.abs(extent.max)) * .002, .01)
}
