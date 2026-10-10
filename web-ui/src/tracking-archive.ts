import {readTrackingBook,trackingKey,trackingAdjustment,type TrackingAnalysis,type TrackingGroup,type ExpansionIssue} from './tracking.ts'
import {studyPeriods,type StudyPeriod} from './research-study.ts'
import {archiveObject,archiveTime,validateArchiveBars} from './archive-data-validation.ts'
import {freezeArchiveDraft,type ArchiveDraft} from './cloud-archives.ts'

export interface TrackingArchive {
  format:'tracking-analysis-v2';group:TrackingGroup;revision:string;periods:StudyPeriod[]
  cutoff:string;finished_at:string;membership_observed_at:string
  state:'completed'|'partial'|'failed'|'cancelled';phase:string;error:string
  rows:TrackingAnalysis[];issues:ExpansionIssue[]
}
export function validateTrackingArchive(value:unknown):TrackingArchive {
  function require(ok:unknown):asserts ok{if(!ok)throw Error('追踪分析记录不完整或状态不一致，未修改原记录')}
  require(archiveObject(value)&&value.format==='tracking-analysis-v2'&&typeof value.revision==='string')
  const group=readTrackingBook({version:1,revision:value.revision,groups:[value.group]}).groups[0]!
  require(group.targets.length>0&&Array.isArray(value.periods)&&value.periods.length>0&&value.periods.length<=9&&new Set(value.periods).size===value.periods.length&&value.periods.every(p=>studyPeriods.some(v=>v.value===p)))
  require(archiveTime(value.cutoff)!==null&&archiveTime(value.finished_at)!==null&&typeof value.membership_observed_at==='string'&&(!value.membership_observed_at||archiveTime(value.membership_observed_at)!==null))
  require(['completed','partial','failed','cancelled'].includes(String(value.state))&&typeof value.phase==='string'&&typeof value.error==='string'&&Array.isArray(value.rows)&&Array.isArray(value.issues))
  const keys=new Set<string>()
  for(const issue of value.issues){
    require(archiveObject(issue)&&archiveObject(issue.target)&&issue.target.kind==='board'&&typeof issue.reason==='string'&&!!issue.reason.trim())
    require(group.targets.some(t=>trackingKey(t)===trackingKey(issue.target as unknown as TrackingGroup['targets'][number])))
  }
  for(const row of value.rows){
    require(archiveObject(row)&&archiveObject(row.target)&&Array.isArray(row.sources)&&row.sources.length>0&&row.sources.every(s=>typeof s==='string')&&['done','error','cancelled'].includes(String(row.state)))
    const target=readTrackingBook({version:1,revision:'',groups:[{id:'validate',name:'validate',targets:[row.target]}]}).groups[0]!.targets[0]!
    const key=trackingKey(target);require(!keys.has(key));keys.add(key)
    const seen=new Set<string>()
    if(row.evidence){
      require(archiveObject(row.evidence)&&row.evidence.adjust===trackingAdjustment(target)&&row.evidence.requested_count===800&&Array.isArray(row.evidence.series))
      for(const item of row.evidence.series){
        require(archiveObject(item)&&typeof item.category==='string'&&value.periods.includes(item.category)&&!seen.has(item.category)&&archiveObject(item.snapshot)&&archiveObject(item.snapshot.metadata))
        seen.add(item.category);validateArchiveBars(item.snapshot.bars)
        require(item.snapshot.metadata.actual_adjust===row.evidence.adjust&&item.snapshot.metadata.category===item.category)
      }
    }
    if(row.study){
      require(archiveObject(row.study)&&row.study.as_of===value.cutoff&&Array.isArray(row.study.rows)&&row.study.rows.length===value.periods.length&&typeof row.study.rule_version==='string')
      const categories=new Set<string>()
      for(const r of row.study.rows){require(archiveObject(r)&&typeof r.category==='string'&&value.periods.includes(r.category)&&!categories.has(r.category)&&((typeof r.error==='string'&&!!r.error.trim())||seen.has(r.category)));categories.add(r.category)}
    }
    if(row.state==='done')require(archiveObject(row.study)&&Array.isArray(row.study.rows)&&row.study.rows.every(r=>archiveObject(r)&&!r.error))
    if(row.state==='error')require(typeof row.error==='string'&&!!row.error)
  }
  if(value.state==='completed')require(value.rows.length>0&&value.rows.every(r=>r.state==='done')&&!value.issues.length&&!value.error&&group.targets.every(t=>keys.has(trackingKey(t))))
  if(value.state==='partial')require(value.issues.length>0||value.rows.some(r=>r.state==='error'))
  if(value.state==='failed')require(!!value.error.trim())
  return value as unknown as TrackingArchive
}
export function trackingArchiveDraft(payload:TrackingArchive):ArchiveDraft {
  validateTrackingArchive(payload)
  return freezeArchiveDraft({kind:'tracking',name:`追踪 · ${payload.group.name} · ${payload.cutoff}`,note:'自动保存的历史分析；只读重开不重新取数或计算。',payload})
}
