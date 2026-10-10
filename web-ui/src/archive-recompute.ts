import { archiveObject, archiveNumber, archiveTime, validateArchiveBars } from './archive-data-validation.ts'
import { prepareArchiveImport } from './archive-import.ts'
import { validateArchiveChartResult } from './archive-chart-validation.ts'
import { freezeArchiveDraft, type ArchiveDraft, type ArchiveRecord } from './cloud-archives.ts'
import { archivedIndicatorSettings, projectRecomputedIndicators } from './archive-indicator-recompute.ts'
import type { FrozenChartIndicators } from './frozen-chart-indicators.ts'
import type { Bar } from './types'
import { readStructureSettings } from './structure-settings.ts'

type RecordValue = Record<string, unknown>
export interface RecomputeJob { category: string; before: unknown; request: RecordValue; frozenBefore?: FrozenChartIndicators }
export interface RecomputePlan { draft: ArchiveDraft; jobs: RecomputeJob[]; warnings: string[] }
export interface RecomputeResult {
  contract: 'archive-recompute-v1'|'archive-recompute-v2'; request_id: string; kind: 'chart'|'study'; input_digest: string
  execution_version: string; scope: string; parameters: RecordValue; result: RecordValue
  indicator_data?: unknown; frozenIndicators?: FrozenChartIndicators
}
function barsForCompute(value: unknown) {
  validateArchiveBars(value)
  const bars = value as RecordValue[]
  if (bars.length > 800) throw Error('单周期超过当前重算接口的 800 根限制；未截短原档，请保留完整记录')
  for (const bar of bars) {
    if (!archiveNumber(bar.vol) || !archiveNumber(bar.amount) || bar.vol < 0 || bar.amount < 0) throw Error('原档缺少有效成交量或成交额，不能补零重算')
    if (typeof bar.datetime !== 'string' || /(?:Z|[+-]\d\d:\d\d)$/.test(bar.datetime)) throw Error('原档行情需为交易所本地时间，不自动转换时区')
  }
  return bars
}

export function planArchiveRecompute(record: ArchiveRecord): RecomputePlan {
  if(record.kind==='backtest'||record.kind==='portfolio')throw Error('此处只查看回测原档，不调用缠论重算；策略库重跑会创建新的计算结果，不替换原档')
  const imported = prepareArchiveImport(record, '原档.json'), payload = imported.draft.payload as RecordValue
  const warnings = ['只使用保存的原行情，不请求最新行情、不重新复权；差异不能证明行情真实性或历史当时可得性。']
  const jobs: RecomputeJob[] = []
  if (record.kind === 'chart') {
    warnings.push('图表按当前算法与原档结构设置重算；未记录设置的旧档使用新笔／3 段，不是原版本复现。', '有冻结指标的周期按保存参数重算全部均线及指标，保留预热空值；无冻结指标的旧周期仅重算结构与 MACD，不补造原参数。')
    for (const entry of payload.charts as RecordValue[]) {
      const result = entry.result as RecordValue
      if (typeof result.code !== 'string' || !result.code || result.code.length > 24) throw Error('原图缺少有效的计算标的身份，不能以当前选股替代')
      const bars = barsForCompute(entry.bars)
      if(bars.length<120)warnings.push(`${entry.category} 仅 ${bars.length} 根原行情，EMA 类指标可能尚未充分收敛；不自动补取更早行情。`)
      const frozen=entry.frozenIndicators as FrozenChartIndicators|undefined
      jobs.push({ category: String(entry.category), before: frozen?{result,frozenIndicators:frozen}:result, frozenBefore:frozen,
        request: { kind:'chart', chart:{ code:result.code,category:entry.category,bars,visible_count:bars.length,
          ...(result.structure_settings === undefined ? {} : {structure_settings:readStructureSettings(result.structure_settings)}) },...(frozen?{chart_indicators:archivedIndicatorSettings(frozen)}:{}) } })
    }
  } else {
    const result = payload.result as RecordValue, parameters = result.parameters
    if (!archiveObject(parameters)) throw Error('旧研究缺少参数，不能用当前页面设置补造；仍可查看原档')
    const keys = ['volume_multiple','squeeze_quantile','ma_periods','window_bars','window_start','window_end']
    if (parameters.structure_settings !== undefined) { readStructureSettings(parameters.structure_settings); keys.push('structure_settings') }
    if (keys.some(key => !Object.hasOwn(parameters,key))) throw Error('旧研究的窗口或指标参数不完整，未重算')
    if (!archiveNumber(parameters.volume_multiple) || parameters.volume_multiple < 1 || parameters.volume_multiple > 10
      || !archiveNumber(parameters.squeeze_quantile) || parameters.squeeze_quantile <= 0 || parameters.squeeze_quantile >= 1
      || !Number.isInteger(parameters.window_bars) || Number(parameters.window_bars) < 3 || Number(parameters.window_bars) > 800
      || !Array.isArray(parameters.ma_periods) || !parameters.ma_periods.length || parameters.ma_periods.length > 12
      || parameters.ma_periods.some(value=>!Number.isInteger(value)||value<1||value>800)) throw Error('原研究参数的类型或范围无效，未转换或替换')
    for (const value of [payload.as_of,parameters.window_start,parameters.window_end]) {
      if (value !== null && (archiveTime(value,true) === null || /(?:Z|[+-]\d\d:\d\d)$/.test(String(value)))) throw Error('原研究截止和窗口必须为完整的交易所本地时间')
    }
    if (JSON.stringify(parameters.macd) !== '[12,26,9]' || JSON.stringify(parameters.boll) !== '[20,2]') throw Error('原研究 MACD／布林参数与当前研究接口不兼容，未替换参数')
    const instrument = payload.instrument
    if (!archiveObject(instrument) || typeof instrument.kind !== 'string' || !['stock','index','board'].includes(instrument.kind) || typeof instrument.market !== 'string' || typeof instrument.code !== 'string') throw Error('原研究缺少完整标的类型与市场，未猜测身份')
    if (instrument.code !== payload.code) throw Error('原研究的标的身份与保存代码不一致，未采用任一版本替代')
    const series = (payload.series as RecordValue[]).map(entry => {
      const snapshot = entry.snapshot as RecordValue, metadata = snapshot.metadata as RecordValue
      if (metadata.bar_time !== 'start' && metadata.bar_time !== 'end') throw Error('原研究缺少行情时间标签，不能猜测起止口径')
      return { category:entry.category,code:`${instrument.kind}:${instrument.market}:${instrument.code}`,bar_time:metadata.bar_time,bars:barsForCompute(snapshot.bars) }
    })
    if(!series.length)throw Error('原研究全部取数失败，没有可供重算的行情；请保留失败记录并回到研究页重新查询')
    warnings.push('使用原研究保存的窗口、均线及量能参数；没有保存行情的失败周期不会被补造。')
    jobs.push({ category:'多周期研究',before:result,request:{kind:'study',study:{as_of:payload.as_of,series,...Object.fromEntries(keys.map(key=>[key,parameters[key]]))}} })
  }
  return { draft: imported.draft, jobs, warnings }
}

export function checkRecomputeResult(value: unknown, job: RecomputeJob, requestId: string): RecomputeResult {
  const withIndicators=job.frozenBefore!==undefined
  if (!archiveObject(value) || value.contract !== (withIndicators?'archive-recompute-v2':'archive-recompute-v1') || value.request_id !== requestId || value.kind !== job.request.kind
    || typeof value.execution_version !== 'string' || !/^research-execution-v1:[a-f\d]{64}$/.test(value.execution_version)
    || typeof value.input_digest !== 'string' || !/^[a-f\d]{64}$/.test(value.input_digest)
    || value.source !== 'client_supplied_archived_bars_not_market_verified' || value.historical_data_vintage !== false
    || !archiveObject(value.result) || !archiveObject(value.parameters)
    || value.scope !== (value.kind === 'chart' ? withIndicators?'structure_macd_and_saved_chart_indicators':(job.request.chart as RecordValue).structure_settings?'structure_and_macd_saved_settings':'structure_and_macd_current_defaults' : 'study_saved_parameters_current_algorithm')) throw Error('重算响应缺少匹配的请求、执行版本或输入证据，未采用结果')
  if (value.kind === 'chart') {
    validateArchiveChartResult(value.result,'recomputed.result')
    if (value.result.code !== (job.request.chart as RecordValue).code) throw Error('重算标的与原档不匹配')
    const saved = (job.request.chart as RecordValue).structure_settings
    if (saved !== undefined && (value.result.structure_settings === undefined || JSON.stringify(readStructureSettings(saved)) !== JSON.stringify(readStructureSettings(value.result.structure_settings)))) throw Error('重算结构设置与原档不一致')
  } else {
    const expected = ((job.request.study as RecordValue).series as RecordValue[]).map(row=>row.category)
    const saved = (job.request.study as RecordValue).structure_settings
    if (saved !== undefined && (value.parameters.structure_settings === undefined || JSON.stringify(readStructureSettings(saved)) !== JSON.stringify(readStructureSettings(value.parameters.structure_settings)))) throw Error('重算研究的结构设置与原档不一致')
    if (!Array.isArray(value.result.rows) || value.result.rows.length !== expected.length
      || value.result.rows.some((row,i)=>!archiveObject(row)||row.category!==expected[i])) throw Error('重算周期与原档不匹配，未丢弃缺失周期')
  }
  const clean={...value} as unknown as RecomputeResult
  delete clean.frozenIndicators
  if(job.frozenBefore)clean.frozenIndicators=projectRecomputedIndicators(value.indicator_data,job.frozenBefore,(job.request.chart as RecordValue).bars as Bar[])
  return clean
}

export function recomputeComparable(result:RecomputeResult):unknown {
  return result.frozenIndicators?{result:result.result,frozenIndicators:result.frozenIndicators}:result.result
}

export interface ArchiveDifference { path: string; before: unknown; after: unknown; beforePresent: boolean; afterPresent: boolean }
/** Structural path diff: never silently truncate, round, or equate an absent field to null. */
export function compareArchiveValues(before: unknown, after: unknown): ArchiveDifference[] {
  const rows: ArchiveDifference[] = [], stack = [{path:'$',before,after,beforePresent:true,afterPresent:true}]
  while (stack.length) {
    const row=stack.pop()!
    if (row.beforePresent === row.afterPresent && Object.is(row.before,row.after)) continue
    const a=row.before,b=row.after
    const containers = row.beforePresent && row.afterPresent && a !== null && b !== null && typeof a==='object' && typeof b==='object' && Array.isArray(a)===Array.isArray(b)
    if (!containers) { rows.push(row); continue }
    const keys=[...new Set([...Object.keys(a as object),...Object.keys(b as object)])].sort().reverse()
    for (const key of keys) stack.push({path:row.path+(Array.isArray(a)?`[${key}]`:`[${JSON.stringify(key)}]`),before:(a as RecordValue)[key],after:(b as RecordValue)[key],beforePresent:Object.hasOwn(a as object,key),afterPresent:Object.hasOwn(b as object,key)})
    if (Array.isArray(a) && Array.isArray(b) && a.length !== b.length) rows.push({path:row.path+'.length',before:a.length,after:b.length,beforePresent:true,afterPresent:true})
  }
  return rows
}

export function recomputedArchiveDraft(record: ArchiveRecord, plan: RecomputePlan, responses: RecomputeResult[], at: string): ArchiveDraft {
  if(record.kind==='backtest'||record.kind==='portfolio')throw Error('回测原档不能写入缠论重算结果')
  if (responses.length !== plan.jobs.length || new Set(responses.map(row=>row.execution_version)).size !== 1) throw Error('周期重算未全部完成或执行版本不一致，不能保存为完整新副本')
  if(plan.jobs.some((job,i)=>job.frozenBefore&&!responses[i]!.frozenIndicators))throw Error('原档指标未全部重算，不能保存为完整新副本')
  const payload = structuredClone(plan.draft.payload) as RecordValue
  if (record.kind === 'chart') {
    payload.charts = (payload.charts as RecordValue[]).map((chart,i) => { const {frozenIndicators:_old,...rest}=chart; const response=responses[i]!; return {...rest,result:response.result,...(response.frozenIndicators?{frozenIndicators:response.frozenIndicators}:{})} })
    payload.savedAt = at; payload.frontendVersion = 'archive-recompute-v2-chart-projection-v1'
    // Old version numbers remain in the source lineage, not on the new result.
    payload.ruleVersions = []
  } else {
    const previous = payload.result as RecordValue, current = structuredClone(responses[0]!.result)
    const computed = new Set((current.rows as RecordValue[]).map(row=>row.category))
    const missing = (previous.rows as RecordValue[]).filter(row=>!computed.has(row.category))
    current.rows = [...current.rows as RecordValue[],...missing.map(row=>({category:row.category,error:'原档未保存本周期行情，未重算；原记录见来源存档'}))]
    payload.result = current
    if(archiveObject(payload.collection))payload.collection={...payload.collection,execution:'completed'}
  }
  payload.recomputation = {contract:'archive-recompute-v1',at,source_archive:{id:record.id,digest:record.digest,revision:record.revision},warnings:plan.warnings,
    indicator_projection:'saved-style-server-values-v1',
    runs:responses.map(({result:_result,frozenIndicators:_frozen,indicator_data:_data,...evidence},i)=>({...evidence,chart_indicator_parameters:plan.jobs[i]!.request.chart_indicators??null})),original_rule_versions:(plan.draft.payload as RecordValue).ruleVersions??null}
  return freezeArchiveDraft({kind:record.kind,name:`${record.name} · 重算`.slice(0,120),note:'使用存档原行情显式重算的新副本；来源原档未修改。',payload})
}
