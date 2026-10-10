import {archiveTime} from './archive-data-validation.ts'
import {freezeArchiveDraft,type ArchiveDraft} from './cloud-archives.ts'
import type {FactorEvaluation} from './factor-research.ts'
import {assertValidationResult} from './factor-validation.ts'
import {assertHorizonComparison} from './factor-horizons.ts'
import {assertComposition} from './factor-composition.ts'

type Row=Record<string,unknown>
export interface FactorArchive {
  format:'factor-research-v1';mode:'series'|'evaluation';title:string;savedAt:string
  result:Row&{settings:Row&{factors:string[]};factor_definitions:Record<string,Row>;input_snapshots:Array<Row>;errors:Record<string,string>}
}
const object=(v:unknown):v is Row=>!!v&&typeof v==='object'&&!Array.isArray(v)
const number=(v:unknown)=>v===null||typeof v==='number'&&Number.isFinite(v)
function require(value:unknown,reason:string):asserts value {if(!value)throw Error(`因子原档不完整：${reason}`)}
/** Inspect only. Frozen definitions may have disappeared from the live catalog. */
export function validateFactorArchive(value:unknown):FactorArchive {
  require(object(value)&&value.format==='factor-research-v1'&&(value.mode==='series'||value.mode==='evaluation'),'版本或模式不支持')
  require(typeof value.title==='string'&&value.title.trim()&&value.title.length<=120&&archiveTime(value.savedAt,true)!==null,'标题或保存时间无效')
  const r=value.result;require(object(r)&&object(r.settings)&&object(r.factor_definitions)&&object(r.errors),'配置、公式或错误记录缺失')
  const s=r.settings,names=s.factors,evaluation=value.mode==='evaluation'
  require(Array.isArray(names)&&names.length>=1&&names.length<=(evaluation?4:12)&&names.every(n=>typeof n==='string'&&/^[a-zA-Z0-9_]{1,100}$/.test(n))&&new Set(names).size===names.length,'因子选择无效')
  require(Object.keys(r.factor_definitions).length===names.length,'冻结公式数量不符')
  for(const n of names){const d=r.factor_definitions[n];require(object(d)&&d.name===n&&['formula','implementation_version','source','catalog_version','formula_sha256'].every(k=>typeof d[k]==='string'&&d[k])&&object(d.resolved_parameters),'缺少完整公式或实际参数')}
  require(['NONE','QFQ','HFQ'].includes(String(s.adjust))&&Number.isInteger(s.count)&&Number(s.count)>=60&&Number(s.count)<=800,'复权或范围无效')
  const snapshots=r.input_snapshots;require(Array.isArray(snapshots)&&(evaluation?snapshots.length>=5&&snapshots.length<=20:snapshots.length===1),'原始输入缺失')
  const symbols=evaluation?(Array.isArray(s.stocks)?s.stocks.map(stock=>object(stock)?`${stock.market}:${stock.code}`:''):[]):[`${s.market}:${s.code}`]
  require(symbols.length===snapshots.length&&new Set(symbols).size===symbols.length,'股票池无效')
  for(const [i,input] of snapshots.entries()){
    require(object(input)&&input.version==='factor-input-v1'&&input.symbol===symbols[i]&&/^(SZ|SH|BJ):\d{6}$/.test(symbols[i]??''),'原始标的不一致')
    require(Array.isArray(input.columns)&&input.columns.length>0&&input.columns.length<=64&&input.columns.every(c=>typeof c==='string')&&new Set(input.columns).size===input.columns.length,'原始字段无效')
    const columns=input.columns
    require(Array.isArray(input.rows)&&input.rows.length>0&&input.rows.length<=Number(s.count)&&input.rows.every(row=>Array.isArray(row)&&row.length===columns.length),'原始行不完整')
    require(Array.isArray(input.dtypes)&&input.dtypes.length===columns.length&&object(input.index)&&Array.isArray(input.index.values)&&input.index.values.length===input.rows.length,'类型或索引缺失')
    require(typeof input.digest==='string'&&/^[a-f0-9]{64}$/.test(input.digest)&&object(input.attrs)&&object(input.attrs.snapshot_metadata),'输入摘要或来源缺失')
    require(input.attrs.snapshot_metadata.actual_adjust===s.adjust&&input.attrs.snapshot_metadata.category===s.category,'周期或复权来源不一致')
  }
  require(typeof r.input_fingerprint==='string'&&/^[a-f0-9]{64}$/.test(r.input_fingerprint),'计算指纹缺失')
  let good:unknown[]
  if(evaluation){
    require(r.version==='factor-cross-section-v1'&&r.trade_eligible===false&&r.assets===snapshots.length&&Array.isArray(r.reports)&&Array.isArray(r.latest)&&Array.isArray(r.redundancy)&&Array.isArray(r.limitations),'检验结果不完整')
    require([1,5,10,20].includes(Number(s.horizon))&&[3,5].includes(Number(s.groups))&&['raw','mad_zscore'].includes(String(s.preprocess))&&s.category==='DAY','检验配置无效')
    good=r.reports.map(report=>{require(object(report)&&typeof report.name==='string'&&Array.isArray(report.daily)&&Array.isArray(report.layer_means)&&report.layer_means.length===s.groups,'检验报告不完整');for(const day of report.daily)require(object(day)&&archiveTime(day.date)!==null&&['ic','rank_ic','rolling_rank_ic'].every(k=>number(day[k]))&&Array.isArray(day.layers)&&day.layers.length===s.groups&&day.layers.every(number),'每日检验不完整');return report.name})
  }else{
    require(Array.isArray(r.computed)&&Array.isArray(r.rows)&&r.rows.length===(snapshots[0] as {rows:unknown[]}).rows.length&&r.count===r.rows.length&&r.input_count===r.rows.length&&r.output_truncated===false&&object(r.diagnostics),'时间序列不完整')
    good=r.computed
    for(const row of r.rows)require(object(row)&&archiveTime(row.datetime)!==null&&good.every(n=>typeof n==='string'&&n in row&&number(row[n])),'序列值缺失')
  }
  const errorMap=r.errors,errors=Object.keys(errorMap)
  if(evaluation)assertValidationResult(r.validation,s.validation,good as string[])
  if(evaluation)assertHorizonComparison(r,s,good as string[])
  if(evaluation)assertComposition(r,s,symbols)
  require(good.every(n=>typeof n==='string'&&names.includes(n)&&!errors.includes(n))&&new Set(good).size===good.length&&errors.every(n=>names.includes(n)&&typeof errorMap[n]==='string'&&errorMap[n])&&good.length+errors.length===names.length,'选择、成功与失败列表不一致')
  return value as unknown as FactorArchive
}
export function factorArchiveDraft(mode:FactorArchive['mode'],result:unknown):ArchiveDraft {
  require(object(result)&&object(result.settings),'没有可保存的完整结果')
  const s=result.settings,period=({DAY:'日线',WEEK:'周线',MONTH:'月线',MIN_1:'1 分钟',MIN_5:'5 分钟',MIN_15:'15 分钟',MIN_30:'30 分钟',MIN_60:'60 分钟'} as Record<string,string>)[String(s.category)]??String(s.category)
  const title=mode==='series'?`${s.code} · ${period} · 因子研究`:`${Array.isArray(s.stocks)?s.stocks.length:0} 只标的 · 因子截面检验`
  const payload=validateFactorArchive({format:'factor-research-v1',mode,title,savedAt:new Date().toISOString(),result})
  return freezeArchiveDraft({kind:'factor',name:title,note:'',payload})
}
export function archivedEvaluation(value:FactorArchive):FactorEvaluation|null{return value.mode==='evaluation'?value.result as unknown as FactorEvaluation:null}

/** Keep the complete replay envelope; rebuilding it from result alone would
 * erase the source digest, original definitions and migration evidence. */
export function factorRecomputedArchive(value:unknown,source?:{id:string;digest:string;revision:number}):FactorArchive {
  const archive=validateFactorArchive(value)
  const lineage=(value as Row).recomputed_from
  require(object(lineage)&&typeof lineage.archive_id==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(lineage.archive_id)&&typeof lineage.digest==='string'&&/^[a-f0-9]{64}$/.test(lineage.digest)&&Number.isSafeInteger(lineage.revision)&&Number(lineage.revision)>0,'重算来源版本缺失')
  require(lineage.input_policy==='frozen_inputs_current_implementation'&&lineage.provenance==='client_archive_not_server_verified'&&object(lineage.original_definitions),'重算输入口径或原始公式缺失')
  if(source)require(lineage.archive_id===source.id&&lineage.digest===source.digest&&lineage.revision===source.revision,'重算来源不一致，未采用此结果')
  return freezeArchiveDraft({kind:'factor',name:archive.title,note:'',payload:archive}).payload as unknown as FactorArchive
}
