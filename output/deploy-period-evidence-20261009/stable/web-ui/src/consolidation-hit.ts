export interface ConsolidationBounds { index: number; start: number[]; end: number[] }

/** Hit testing uses rendered price-axis pixels, so zoom and intraday slots agree. */
export function consolidationHits(bounds: ConsolidationBounds[], x: number, y: number): number[] {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return []
  return bounds.filter(({ start, end }) => start.length === 2 && end.length === 2
    && [...start, ...end].every(Number.isFinite)
    && x >= Math.min(start[0]!, end[0]!) - 3 && x <= Math.max(start[0]!, end[0]!) + 3
    && y >= Math.min(start[1]!, end[1]!) - 3 && y <= Math.max(start[1]!, end[1]!) + 3
  ).map(item => item.index).reverse()
}

export function boundedPopover(x: number, y: number, width: number, height: number, viewportWidth: number, viewportHeight: number) {
  return { left: Math.max(12, Math.min(x + 10, viewportWidth - width - 12)),
    top: Math.max(12, Math.min(y + 10, viewportHeight - height - 12)) }
}
