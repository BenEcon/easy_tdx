import type { ChanlunDivergence, ChanlunSignal } from './types'
import { divergenceEvidence, divergenceName, signalEvidence } from './divergence-evidence.ts'

export interface ChartSignalDetail {
  kind: 'structure' | 'macd'
  title: string
  date: string | null
  confirmedDate: string | null
  price: number
  source: string
  message: string
  evidence: string[]
}
export function signalName(type: string): string {
  return ({ '1buy': '一类买点', '2buy': '二类买点', '3buy': '三类买点',
    '1sell': '一类卖点', '2sell': '二类卖点', '3sell': '三类卖点' } as Record<string, string>)[type] ?? type
}
export function structuralSignalDetail(signal: ChanlunSignal, price: number): ChartSignalDetail {
  const known = signal.source === 'confirmed_segment_base_v1'
  return { kind: 'structure', title: signalName(signal.type), date: signal.date,
    confirmedDate: signal.confirmed_date ?? null, price,
    source: known ? '已确认线段 · 基础结构' : '原始信号记录 · 未提供可核验的结构来源',
    message: signal.msg,
    evidence: known ? signalEvidence(signal) : ['该记录未提供已识别的结构规则来源，不推定确认依据。'] }
}
export function macdSignalDetail(item: ChanlunDivergence, price: number): ChartSignalDetail {
  return { kind: 'macd', title: `M1 · MACD ${item.direction === 'down' ? '买入' : '卖出'}提示`,
    date: item.curr_date, confirmedDate: item.confirmed_date ?? null, price,
    source: divergenceName(item), message: item.msg, evidence: divergenceEvidence(item) }
}
