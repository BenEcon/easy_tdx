/** Keep exchange-local timestamps as text: never apply the browser's timezone. */
function parts(value: string) {
  return /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::(\d{2})(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})?)?$/.exec(value.trim())
}

function key(value: string): string | undefined {
  const p = parts(value)
  if (!p) return undefined
  const fraction = (p[4] ?? '').replace(/0+$/, '').replace(/\.$/, '')
  const zone = p[5] === '+00:00' ? 'Z' : (p[5] ?? '')
  return `${p[1]}T${p[2] ?? '00:00'}:${p[3] ?? '00'}${fraction}${zone}`
}

/** Full timestamps match exactly; only a date-only value may use a unique day. */
export function createBarTimeLookup(values: string[]): (value: string) => number | undefined {
  const exact = new Map<string, number>()
  const days = new Map<string, number>()
  const ambiguous = new Set<string>()
  for (const [index, value] of values.entries()) {
    const normalized = key(value)
    if (normalized === undefined) continue
    if (!exact.has(normalized)) exact.set(normalized, index)
    const day = normalized.slice(0, 10)
    const previous = days.get(day)
    if (previous === undefined) days.set(day, index)
    else if (key(values[previous]!) !== normalized) ambiguous.add(day)
  }
  return value => {
    const normalized = key(value)
    if (normalized === undefined) return undefined
    // A bare date cannot silently choose a midnight bar in an intraday series.
    if (!parts(value)?.[2]) {
      const day = normalized.slice(0, 10)
      return ambiguous.has(day) ? undefined : days.get(day)
    }
    return exact.get(normalized)
  }
}

export function formatMarketTime(value: string): string {
  const p = parts(value)
  if (!p) return value
  const fraction = (p[4] ?? '').replace(/0+$/, '').replace(/\.$/, '')
  if (!p[2] || (p[2] === '00:00' && (!p[3] || p[3] === '00') && !fraction && !p[5])) {
    return p[1]!
  }
  const seconds = (p[3] && p[3] !== '00') || fraction ? `:${p[3] ?? '00'}${fraction}` : ''
  return `${p[1]} ${p[2]}${seconds}${p[5] ?? ''}`
}
