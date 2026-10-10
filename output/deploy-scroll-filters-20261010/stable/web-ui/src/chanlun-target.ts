export type TargetKind = 'stock' | 'index' | 'board'
export type BoardKind = 'HY' | 'HY2' | 'GN' | 'FG' | 'DQ'
export interface ResearchTarget {
  kind: TargetKind
  code: string
  market: string
  name?: string
  boardType?: BoardKind
}
export const indexTargets = [
  { value: 'SH:000001', label: '000001-上证指数' },
  { value: 'SZ:399001', label: '399001-深证成指' },
  { value: 'SZ:399106', label: '399106-深证综指' },
  { value: 'SZ:399006', label: '399006-创业板指' },
  { value: 'SH:000300', label: '000300-沪深300' },
  { value: 'SH:000016', label: '000016-上证50' },
  { value: 'SH:000905', label: '000905-中证500' },
  { value: 'SH:000852', label: '000852-中证1000' },
  { value: 'SH:000688', label: '000688-科创50' },
]
export const targetKindLabel = { stock: '个股', index: '指数', board: '板块' }
export function targetIdentity(target: ResearchTarget): string {
  return `${target.kind}:${target.market}:${target.code}`
}
