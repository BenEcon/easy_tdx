import type { ResearchSnapshot } from './research-snapshots'

/** Validate local backup shape before allowing it into a chart; never execute embedded content. */
export function validateResearchSnapshot(value: unknown): ResearchSnapshot {
  const fail = (): never => { throw new Error('不是受支持的研究快照，或其中的行情／分析记录不完整') }
  if (!value || typeof value !== 'object') return fail()
  const data = value as ResearchSnapshot
  if (data.schema !== 1 || typeof data.title !== 'string' || typeof data.cutoff !== 'string'
    || !data.target || !['stock','index','board'].includes(data.target.kind) || typeof data.target.code !== 'string'
    || !data.preferences || !data.layers || !['bis','xds','zss','bcs','mmds'].every(key => typeof (data.layers as Record<string,unknown>)[key] === 'boolean')
    || !Array.isArray(data.charts) || data.charts.length < 1 || data.charts.length > 2) return fail()
  for (const chart of data.charts) {
    if (!['DAY','WEEK','MONTH','MIN_1','MIN_5','MIN_15','MIN_30','MIN_60'].includes(chart?.category)
      || !Array.isArray(chart.bars) || !chart.bars.length || chart.bars.length > 800
      || !chart.metadata || typeof chart.metadata.actual_adjust !== 'string' || typeof chart.metadata.observed_at !== 'string') return fail()
    let prior = ''
    for (const bar of chart.bars) {
      if (!bar || typeof bar.datetime !== 'string' || !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(bar.datetime)
        || bar.datetime <= prior || ![bar.open,bar.close,bar.low,bar.high].every(Number.isFinite)
        || bar.low > Math.min(bar.open,bar.close) || bar.high < Math.max(bar.open,bar.close)) return fail()
      prior = bar.datetime
    }
    const result = chart.result
    if (!result || typeof result.code !== 'string' || typeof result.frequency !== 'string'
      || ![result.bis,result.xds,result.zss,result.bcs,result.mmds].every(Array.isArray)) return fail()
    for (const segment of [...result.bis,...result.xds]) {
      if (!segment || typeof segment.start_date !== 'string' || typeof segment.end_date !== 'string'
        || ![segment.low,segment.high].every(Number.isFinite) || !['up','down'].includes(segment.direction)) return fail()
    }
    for (const item of [...result.bcs,...result.mmds]) if (!item || typeof item.msg !== 'string' || typeof item.type !== 'string') return fail()
    for (const item of result.pen_consolidations ?? []) if (!item || !Array.isArray(item.pen_indices) || ![item.lower,item.upper].every(Number.isFinite)) return fail()
    for (const item of result.wave_diagnostics ?? []) if (!item || !Array.isArray(item.checks) || !item.dates || !Array.isArray(item.rejections)) return fail()
    for (const item of [...result.zss,...(result.structural_centres ?? [])]) if (!item || ![item.zd,item.zg,item.dd,item.gg].every(Number.isFinite)) return fail()
  }
  return { ...data, name: typeof data.name === 'string' ? data.name.slice(0,120) : data.title.slice(0,120), note: typeof data.note === 'string' ? data.note.slice(0,4000) : '',
    ruleVersions: Array.isArray(data.ruleVersions) ? data.ruleVersions.filter(Number.isFinite).slice(0,30) : [], frontendVersion: typeof data.frontendVersion === 'string' ? data.frontendVersion : '未提供' }
}
