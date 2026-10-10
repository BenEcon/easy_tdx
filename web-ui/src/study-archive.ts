import type { BarSnapshot } from './api'
import type { ResearchTarget } from './chanlun-target'
import { copyRadarSourceForTarget, type RadarArchiveSource } from './radar-archive.ts'
import { studyPeriods, type Study, type StudyPeriod, type StudyRow } from './research-study.ts'
import { archiveObject, archiveTime } from './archive-data-validation.ts'

export interface StudyArchiveContext {
  code:string; instrument:ResearchTarget; adjust:string; as_of:string
  selected:StudyPeriod[]; primary:{category:string;snapshot:BarSnapshot}
  parameters:Record<string,unknown>; radarSource?:RadarArchiveSource
}
export interface StudyArchivePayload {
  format:'chanlun-research-snapshot-v2';code:string;instrument:ResearchTarget;adjust:string;as_of:string
  historical_data_vintage:false;result:Study;series:Array<{category:StudyPeriod;snapshot:BarSnapshot}>
  primary:StudyArchiveContext['primary'];warmup_policy:string;radarSource?:RadarArchiveSource
  collection:{contract:'study-collection-v1';selected_periods:StudyPeriod[];execution:'completed'|'failed'|'not_started'}
}
export function detachStudyValue<T>(value:T):T {
  return JSON.parse(JSON.stringify(value,(_key,v)=>{
    if(typeof v==='number'&&!Number.isFinite(v))throw Error('研究记录含非有限数值，未保存')
    return v
  })) as T
}
export function freezeStudyContext(context:StudyArchiveContext):StudyArchiveContext {
  if(context.code!==context.instrument.code)throw Error('研究标的身份不一致')
  const radarSource=copyRadarSourceForTarget(context.instrument,context.radarSource)
  return detachStudyValue({...context,...(radarSource?{radarSource}:{})})
}
/** Preserve every selected period, including absent rows and failed collection. */
export function finishStudyArchive(context:StudyArchiveContext,series:StudyArchivePayload['series'],failures:Record<string,string>,response:Study|null,executionError=''):StudyArchivePayload {
  const expected=new Set(series.map(item=>item.category)),seen=new Set<string>()
  if(response){
    if(!Array.isArray(response.rows)||archiveTime(response.as_of)!==archiveTime(context.as_of))throw Error('研究响应周期或截止与本次请求不一致')
    for(const row of response.rows){
      if(!row||!expected.has(row.category as StudyPeriod)||seen.has(row.category))throw Error('研究响应出现非请求周期或重复周期')
      seen.add(row.category)
    }
  }
  const rows=context.selected.map(category=>{
    const row=response?.rows.find(item=>item.category===category)
    if(row)return row
    // Existing API error rows intentionally omit all computed numeric fields.
    return {category,error:failures[category]||executionError||'研究接口未返回本周期结果，请重试',failure_stage:failures[category]?'collection':'computation'} as unknown as StudyRow
  })
  const result:Study=response?{...response,rows}:{as_of:context.as_of,rows,conflicts:[],policy:'本次没有取得分析结果；仅保存请求与失败原因，不生成结论',rule_version:'未取得服务端规则版本',parameters:context.parameters}
  return detachStudyValue({format:'chanlun-research-snapshot-v2',code:context.code,instrument:context.instrument,adjust:context.adjust,as_of:context.as_of,
    historical_data_vintage:false,result,series,primary:context.primary,
    collection:{contract:'study-collection-v1',selected_periods:context.selected,execution:response?'completed':series.length?'failed':'not_started'},
    ...(context.radarSource?{radarSource:context.radarSource}:{}),
    warmup_policy:'各周期从所保存行情首根开始；EMA 首值为首根收盘价；计算不舍入'})
}
/** Optional newer coverage contract; older archives remain readable as-is. */
export function validateStudyCollection(payload:Record<string,unknown>):void {
  if(payload.collection===undefined)return
  const c=payload.collection
  if(!archiveObject(c)||c.contract!=='study-collection-v1'||typeof c.execution!=='string'||!['completed','failed','not_started'].includes(c.execution)
    ||!Array.isArray(c.selected_periods)||!c.selected_periods.length||c.selected_periods.length>9
    ||new Set(c.selected_periods).size!==c.selected_periods.length||c.selected_periods.some(p=>!studyPeriods.some(item=>item.value===p))
    ||!archiveObject(payload.result)||!Array.isArray(payload.result.rows)||!Array.isArray(payload.series))throw Error('研究选定周期与完成状态不完整')
  const rows=payload.result.rows
  const selected=c.selected_periods
  if(rows.length!==selected.length||new Set(rows.map(r=>archiveObject(r)?r.category:null)).size!==rows.length
    ||rows.some(r=>!archiveObject(r)||!selected.includes(r.category))
    ||payload.series.some(s=>!archiveObject(s)||!selected.includes(s.category))
    ||(c.execution==='not_started'&&payload.series.length!==0)
    ||(c.execution!=='not_started'&&payload.series.length===0)
    ||(c.execution!=='completed'&&rows.some(r=>!archiveObject(r)||typeof r.error!=='string'||!r.error.trim())))throw Error('研究记录未完整保留选定周期，或执行状态与原行情不一致')
}

export function studyArchiveLineage(payload:Record<string,unknown>):RadarArchiveSource|undefined {
  validateStudyCollection(payload)
  if(payload.radarSource===undefined)return undefined
  const target=payload.instrument
  if(!archiveObject(target)||target.kind!=='stock'||typeof target.code!=='string'||target.code!==payload.code
    ||!['SH','SZ','BJ'].includes(String(target.market)))throw Error('研究与原扫描标的身份不一致')
  return copyRadarSourceForTarget(target as unknown as ResearchTarget,payload.radarSource as RadarArchiveSource)
}
