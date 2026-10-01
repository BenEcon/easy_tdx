type Point = [number, number]
type CandleLayout = {
  ends: Point[]
  brushRect?: { x: number; y: number; width: number; height: number }
}

/**
 * ECharts rounds each body edge and wick independently, leaving a 0.5px offset.
 * Keep its crisp wick position, and place both body edges symmetrically around it.
 * An even CSS-pixel width keeps the 1px body outline on the same half-pixel grid.
 * Price coordinates, category indices and wick extrema are never changed.
 */
export function alignCandleBody(layout: CandleLayout | undefined, candleWidth: number, axis: 0 | 1 = 0): void {
  if (!layout || layout.ends?.length !== 8 || !Number.isFinite(candleWidth) || candleWidth <= 0) return
  const points = layout.ends
  if (points.some(point => !point || !point.every(Number.isFinite))) return
  const center = points[4]![axis]
  if (points.slice(4).some(point => point[axis] !== center)) return
  const halfWidth = Math.max(1, Math.round(candleWidth / 2))
  for (const [index, side] of [-1, 1, 1, -1].entries()) {
    points[index]![axis] = center + side * halfWidth
  }
  if (layout.brushRect) {
    layout.brushRect[axis === 0 ? 'x' : 'y'] = center - halfWidth
    layout.brushRect[axis === 0 ? 'width' : 'height'] = halfWidth * 2
  }
}

type LayoutRegisters = Pick<typeof import('echarts/core'), 'registerLayout' | 'PRIORITY'>

/** Run after the native candle layout, including resize, dataZoom and progressive updates. */
export function installCandleAlignment(registers: LayoutRegisters): void {
  registers.registerLayout(registers.PRIORITY.VISUAL.LAYOUT + 1, {
    seriesType: 'candlestick',
    reset(seriesModel) {
      const data = seriesModel.getData()
      // Large/simple modes only draw a high-low line, not a rectangle.
      if (seriesModel.pipelineContext.large || data.getLayout('isSimpleBox')) return
      const axis = seriesModel.getBaseAxis().dim === 'x' ? 0 : 1
      const width = data.getLayout('candleWidth') as number
      return {
        progress(params, currentData) {
          const align = (index: number) => alignCandleBody(currentData.getItemLayout(index) as CandleLayout | undefined, width, axis)
          if (params.next) {
            let index: number | null
            while ((index = params.next()) !== null) align(index)
          } else {
            for (let index = params.start; index < params.end; index++) align(index)
          }
        },
      }
    },
  })
}
