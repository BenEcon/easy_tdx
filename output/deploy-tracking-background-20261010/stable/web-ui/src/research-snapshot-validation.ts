import type { ResearchSnapshot } from './research-snapshots'
import { validateFrozenChartIndicators } from './frozen-chart-indicators.ts'
import { archiveTime, validateArchiveBars } from './archive-data-validation.ts'
import { validateArchiveChartResult } from './archive-chart-validation.ts'

/** Validate local backup shape before allowing it into a chart; never execute embedded content. */
export function validateResearchSnapshot(value: unknown): ResearchSnapshot {
  const fail = (): never => { throw new Error('不是受支持的研究快照，或其中的行情／分析记录不完整') }
  if (!value || typeof value !== 'object') return fail()
  const data = value as ResearchSnapshot
  if (data.schema !== 1 || typeof data.title !== 'string' || archiveTime(data.cutoff) === null
    || !data.target || !['stock','index','board'].includes(data.target.kind) || typeof data.target.code !== 'string'
    || !data.preferences || !data.layers || !['bis','xds','zss','bcs','mmds'].every(key => typeof (data.layers as Record<string,unknown>)[key] === 'boolean')
    || !Array.isArray(data.charts) || data.charts.length < 1 || data.charts.length > 12) return fail()
  const categories=new Set<string>()
  for (const chart of data.charts) {
    if (!['DAY','WEEK','MONTH','MIN_1','MIN_5','MIN_15','MIN_30','MIN_60','MIN_120'].includes(chart?.category)
      || categories.has(chart.category)
      || !Array.isArray(chart.bars) || !chart.bars.length || chart.bars.length > 8000
      || !chart.metadata || typeof chart.metadata.actual_adjust !== 'string' || typeof chart.metadata.observed_at !== 'string') return fail()
    categories.add(chart.category)
    validateArchiveBars(chart.bars)
    if (chart.frozenIndicators !== undefined) validateFrozenChartIndicators(chart.frozenIndicators,chart.bars)
    validateArchiveChartResult(chart.result,`charts.${chart.category}.result`)
  }
  return { ...data, name: typeof data.name === 'string' ? data.name.slice(0,120) : data.title.slice(0,120), note: typeof data.note === 'string' ? data.note.slice(0,4000) : '',
    ruleVersions: Array.isArray(data.ruleVersions) ? data.ruleVersions.filter(Number.isFinite).slice(0,30) : [], frontendVersion: typeof data.frontendVersion === 'string' ? data.frontendVersion : '未提供' }
}
