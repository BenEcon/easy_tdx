import type { Bar } from './types'

export type TechnicalIndicator = 'none' | 'volume' | 'macd' | 'kdj' | 'rsi'

export const TECHNICAL_INDICATORS: Array<{
  value: TechnicalIndicator
  label: string
  description: string
}> = [
  { value: 'none', label: '无指标', description: '仅观察价格走势' },
  { value: 'volume', label: '成交量', description: '观察量价配合' },
  { value: 'macd', label: 'MACD', description: '趋势与动能' },
  { value: 'kdj', label: 'KDJ', description: '短期超买超卖' },
  { value: 'rsi', label: 'RSI', description: '相对强弱' },
]

function ema(values: number[], period: number): number[] {
  if (!values.length) return []
  const alpha = 2 / (period + 1)
  const output = [values[0]]
  for (let index = 1; index < values.length; index += 1) {
    output.push(values[index] * alpha + output[index - 1] * (1 - alpha))
  }
  return output
}

export function calculateMacd(bars: Bar[]): { dif: number[]; dea: number[]; histogram: number[] } {
  const closes = bars.map((bar) => bar.close)
  const fast = ema(closes, 12)
  const slow = ema(closes, 26)
  const dif = closes.map((_, index) => fast[index] - slow[index])
  const dea = ema(dif, 9)
  return {
    dif,
    dea,
    histogram: dif.map((value, index) => (value - dea[index]) * 2),
  }
}

export function calculateKdj(bars: Bar[]): { k: number[]; d: number[]; j: number[] } {
  let previousK = 50
  let previousD = 50
  const k: number[] = []
  const d: number[] = []
  const j: number[] = []

  bars.forEach((bar, index) => {
    const window = bars.slice(Math.max(0, index - 8), index + 1)
    const lowest = Math.min(...window.map((item) => item.low))
    const highest = Math.max(...window.map((item) => item.high))
    const rsv = highest === lowest ? 50 : ((bar.close - lowest) / (highest - lowest)) * 100
    previousK = (2 * previousK + rsv) / 3
    previousD = (2 * previousD + previousK) / 3
    k.push(previousK)
    d.push(previousD)
    j.push(3 * previousK - 2 * previousD)
  })

  return { k, d, j }
}

export function calculateRsi(bars: Bar[], period = 14): Array<number | null> {
  const output: Array<number | null> = Array(bars.length).fill(null)
  if (bars.length <= period) return output

  let gain = 0
  let loss = 0
  for (let index = 1; index <= period; index += 1) {
    const change = bars[index].close - bars[index - 1].close
    gain += Math.max(change, 0)
    loss += Math.max(-change, 0)
  }

  let averageGain = gain / period
  let averageLoss = loss / period
  const value = () => averageLoss === 0 ? 100 : 100 - 100 / (1 + averageGain / averageLoss)
  output[period] = value()

  for (let index = period + 1; index < bars.length; index += 1) {
    const change = bars[index].close - bars[index - 1].close
    averageGain = (averageGain * (period - 1) + Math.max(change, 0)) / period
    averageLoss = (averageLoss * (period - 1) + Math.max(-change, 0)) / period
    output[index] = value()
  }
  return output
}

export function percentageChange(bars: Bar[], index: number): number | null {
  if (index < 0 || index >= bars.length) return null
  const previousClose = index > 0 ? bars[index - 1].close : bars[index].open
  if (!Number.isFinite(previousClose) || previousClose === 0) return null
  return ((bars[index].close - previousClose) / previousClose) * 100
}

export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return '—'
  const absolute = Math.abs(value)
  if (absolute >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿`
  if (absolute >= 10_000) return `${(value / 10_000).toFixed(2)}万`
  return value.toFixed(2)
}
