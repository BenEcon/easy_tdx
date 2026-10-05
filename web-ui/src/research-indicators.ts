import type { Bar } from './types'
import { calculateIndicatorRows, type IndicatorParams } from './technical-indicators'

// Bar arrays are immutable analysis snapshots. Weak ownership avoids retaining old data.
const snapshots = new WeakMap<Bar[], Map<string, Promise<Array<Record<string, unknown>>>>>()
export function researchIndicatorRows(bars: Bar[], type: string, params: IndicatorParams) {
  let entries = snapshots.get(bars)
  if (!entries) { entries = new Map(); snapshots.set(bars, entries) }
  const key = JSON.stringify([type, Object.entries(params).sort(([a], [b]) => a.localeCompare(b))])
  const existing = entries.get(key)
  if (existing) return existing
  const result = calculateIndicatorRows(bars, type, params).catch(error => { entries!.delete(key); throw error })
  entries.set(key, result)
  while (entries.size > 12) entries.delete(entries.keys().next().value!)
  return result
}
