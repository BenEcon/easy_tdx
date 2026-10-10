export const MOVING_AVERAGE_PERIODS = Object.freeze([5, 10, 20, 30, 60, 120, 250])
export const INDICATOR_LINE_COLORS = ['#ffff00', '#ffffff', '#da70d6', '#00ff00', '#00ffff', '#ff8c00', '#ff3030']

export function createMovingAverageSettings() {
  return MOVING_AVERAGE_PERIODS.map(period => ({ period, enabled: period === 5 || period === 10 }))
}

export function movingAverageSelection(available: number[], enabled: number[]) {
  const selected = new Set(enabled)
  return Object.fromEntries(available.map(period => [`MA${period}`, selected.has(period)]))
}

export function movingAverageColor(period: number): string {
  const index = MOVING_AVERAGE_PERIODS.indexOf(period)
  return index < 0 ? `hsl(${Math.round(period * 137.508) % 360}, 32%, 70%)` : INDICATOR_LINE_COLORS[index]!
}
