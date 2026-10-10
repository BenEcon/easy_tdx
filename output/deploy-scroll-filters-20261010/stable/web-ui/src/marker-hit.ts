/** Use the rendered symbol centre (including stacking offset), not the candle price. */
export function markerHit(point: number[], offset: number[], size: number | number[], x: number, y: number) {
  const [width, height] = Array.isArray(size) ? size : [size, size]
  if (point.length !== 2 || offset.length !== 2 || ![...point, ...offset, width, height, x, y].every(Number.isFinite)) return false
  return Math.abs(x - point[0]! - offset[0]!) <= Math.max(5, width! / 2) + 2
    && Math.abs(y - point[1]! - offset[1]!) <= Math.max(5, height! / 2) + 2
}
