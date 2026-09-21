const periods = [5, 10, 20, 30, 60, 120, 250]
export const INDICATOR_LINE_COLORS = ['#ffff00', '#ffffff', '#da70d6', '#00ff00', '#00ffff', '#ff8c00', '#ff3030']

export function movingAverageColor(period: number): string {
  const index = periods.indexOf(period)
  return index < 0 ? `hsl(${Math.round(period * 137.508) % 360}, 32%, 70%)` : INDICATOR_LINE_COLORS[index]!
}
