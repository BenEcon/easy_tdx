import { archiveNumber as number, archiveObject as object, archiveTime } from './archive-data-validation.ts'
import { studyLabel, studyPeriods, type StudyPeriod, type StudyRow } from './research-study.ts'

const text=(value:unknown):value is string=>typeof value==='string'
const optionalNumber=(value:unknown)=>value===null||number(value)
const time=(value:unknown)=>archiveTime(value)!==null
const optionalTime=(value:unknown)=>value==null||time(value)
const count=(value:unknown)=>number(value)&&Number.isInteger(value)&&value>=0
const period=(value:unknown):value is StudyPeriod=>studyPeriods.some(item=>item.value===value)

/** Validate every field consumed by the overview table, not a speculative new analysis schema. */
export function studyOverviewIssue(value:unknown):string|null {
  if(!object(value))return '记录不是对象'
  if(!period(value.category))return '不支持的周期'
  if(value.error!==undefined)return text(value.error)&&value.error.trim() ? null : 'error'
  for(const key of ['price'])if(!number(value[key]))return key
  for(const key of ['axis','histogram'])if(!text(value[key]))return key
  if(value.volume_ratio!==undefined&&!optionalNumber(value.volume_ratio))return 'volume_ratio'
  if(!optionalTime(value.last_closed_at))return 'last_closed_at'
  if(!object(value.pairs))return 'pairs'
  for(const key of ['ma','volume','macd']){
    const pair=value.pairs[key]
    if(!object(pair)||!optionalNumber(pair.fast)||!optionalNumber(pair.slow)||!text(pair.description))return `pairs.${key}`
  }
  if(!object(value.ma_research))return 'ma_research'
  for(const key of ['bull','bear']){
    const side=value.ma_research[key]
    if(!object(side)||(side.to!==null&&(!count(side.to)||side.to===0)))return `ma_research.${key}.to`
  }
  const direction=value.direction_observation
  if(!object(direction)||!text(direction.description)||!optionalTime(direction.known_date))return 'direction_observation'
  if(direction.strict!==null){
    const pen=direction.strict
    if(!object(pen)||(pen.direction!=='up'&&pen.direction!=='down')||typeof pen.locked!=='boolean'
      ||!time(pen.start_date)||!time(pen.end_date)||archiveTime(pen.start_date)! > archiveTime(pen.end_date)!
      ||!number(pen.start_price)||!number(pen.end_price))return 'direction_observation.strict'
  }
  if(!Array.isArray(value.divergences))return 'divergences'
  for(const item of value.divergences){
    if(!object(item)||!time(item.date)||!optionalTime(item.confirmed_date)||!text(item.status)
      ||(item.direction!=='up'&&item.direction!=='down')||(item.kind!==undefined&&!text(item.kind)))return 'divergences[]'
  }
  if(!Array.isArray(value.observations)||!value.observations.every(text))return 'observations'
  if(typeof value.warmup_warning!=='boolean'||!count(value.excluded_bars))return '行情质量标记'
  const window=value.window
  if(!object(window)||!time(window.start)||!time(window.end)||archiveTime(window.start)! > archiveTime(window.end)!
    ||!count(window.count)||typeof window.truncated!=='boolean')return 'window'
  return null
}

export interface ArchiveStudyEntry { key:string; label:string; category:StudyPeriod|null; raw:unknown; problem:string|null }
export function archiveStudyPreview(payload:unknown):{entries:ArchiveStudyEntry[];rows:StudyRow[]}|null {
  if(!object(payload)||!object(payload.result)||!Array.isArray(payload.result.rows))return null
  const counts=new Map<StudyPeriod,number>()
  for(const row of payload.result.rows)if(object(row)&&period(row.category))counts.set(row.category,(counts.get(row.category)??0)+1)
  const entries=payload.result.rows.map((raw,index):ArchiveStudyEntry=>{
    const category=object(raw)&&period(raw.category)?raw.category:null
    const issue=studyOverviewIssue(raw)
    const duplicate=category&&(counts.get(category)??0)>1
    return {key:`record-${index}`,category,raw,label:category?studyLabel(category):`未识别周期 · 记录 ${index+1}`,
      problem:duplicate?'同一周期存在重复记录，未擅自选择其中一份。':issue?`原档无法完整展示（${issue}）；原始记录保留，未补算或修复。`:null}
  })
  const seen=new Set<StudyPeriod>(),rows:StudyRow[]=[]
  for(const entry of entries){
    if(!entry.category||seen.has(entry.category))continue
    seen.add(entry.category)
    // An error row is intentionally a table-only projection. Never write it into the archive.
    if(entry.problem)rows.push({category:entry.category,error:entry.problem} as StudyRow)
    else if(object(entry.raw)&&typeof entry.raw.error==='string')rows.push({category:entry.category,error:entry.raw.error,
      ...(time(entry.raw.last_closed_at)?{last_closed_at:entry.raw.last_closed_at}:{})} as StudyRow)
    else rows.push(entry.raw as StudyRow)
  }
  return {entries,rows}
}
