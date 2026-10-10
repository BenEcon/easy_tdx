export const DEFAULT_CANDLE_TRANSPARENCY = 80

export function candleTransparency(value?: number): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(0, Math.min(100, Math.round(value))) : DEFAULT_CANDLE_TRANSPARENCY
}

/** Alpha applies only to the body fill; borders/wicks keep their original colors. */
export function candleFill(hex: string, transparency?: number): string {
  const rgb = [1, 3, 5].map(start => parseInt(hex.slice(start, start + 2), 16))
  return `rgba(${rgb.join(',')},${(100 - candleTransparency(transparency)) / 100})`
}
