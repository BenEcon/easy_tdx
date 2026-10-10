/** Geometry must move as one frame, never interpolate each overlay independently. */
export const synchronousChartMotion = {
  animation: false,
  animationDuration: 0,
  animationDurationUpdate: 0,
} as const

export function synchronizeChartSeries(series: Array<Record<string, unknown>>): void {
  for (const item of series) {
    Object.assign(item, synchronousChartMotion, { progressive: 0 })
    // The research window is bounded; keep candles in the same normal render pass.
    if (item.type === 'candlestick') item.large = false
    for (const key of ['markPoint', 'markLine', 'markArea']) {
      const marker = item[key]
      if (marker && typeof marker === 'object') Object.assign(marker, synchronousChartMotion)
    }
  }
}
