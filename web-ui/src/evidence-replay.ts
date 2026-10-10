import type { Bar, Category, ChanlunResult } from './types'

export interface EvidenceSource { category: Category; bars: Bar[]; result: ChanlunResult }
export function selectEvidenceSource<T extends EvidenceSource>(sources: readonly T[], category: Category): T | null {
  // Never fall back to a different period when a delayed UI event names a missing source.
  return sources.find(source => source.category === category) ?? null
}
export function evidenceReplayRequest(source: EvidenceSource, position: number) {
  if (!Number.isInteger(position) || position < 1 || position > source.bars.length) throw new Error('审核位置超出当前周期快照')
  if (!source.result.code || source.bars.slice(0, position).some(bar => bar.is_closed === false)) throw new Error('审核快照包含未收盘行情或缺少标的身份')
  return { code: source.result.code, category: source.category, bars: source.bars, visible_count: position,
    ...(source.result.structure_settings ? { structure_settings: source.result.structure_settings } : {}) }
}
