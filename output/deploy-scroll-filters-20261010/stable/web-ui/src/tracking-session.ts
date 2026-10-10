import {computed, ref, shallowRef} from 'vue'
import {analyzeTrackingEntries, expandTrackingGroup, type TrackingAnalysis, type TrackingGroup, type TrackingTarget, type ExpansionIssue} from './tracking.ts'
import type {Study, StudyPeriod} from './research-study.ts'
import type {TrackingArchive} from './tracking-archive.ts'

export interface TrackingRunAdapter {
  now:()=>string
  members:(code:string,signal:AbortSignal,owner:string)=>Promise<{data:Record<string,unknown>[];count:number}>
  analyze:(target:TrackingTarget,periods:StudyPeriod[],cutoff:string,signal:AbortSignal,owner:string)=>Promise<Study>
}
/** Owned by the application, not by a route component. No timers or persistence
 * across browser reloads; all async publications are fenced by owner + generation. */
export function createTrackingSession(onFinished?:(payload:TrackingArchive)=>Promise<void>,canStart:()=>boolean=()=>true) {
  const owner=ref(''),selectedId=ref(''),periods=ref<StudyPeriod[]>(['DAY'])
  const rows=shallowRef<TrackingAnalysis[]>([]),issues=shallowRef<ExpansionIssue[]>([])
  const loading=ref(false),phase=ref(''),cutoff=ref(''),expandedAt=ref(''),error=ref('')
  const snapshot=shallowRef<{group:TrackingGroup;periods:StudyPeriod[];revision:string}|null>(null)
  const archive=shallowRef<TrackingArchive|null>(null)
  const completed=computed(()=>rows.value.filter(row=>row.state==='done'||row.state==='error').length)
  const successful=computed(()=>rows.value.filter(row=>row.state==='done').length)
  const failed=computed(()=>rows.value.filter(row=>row.state==='error').length)
  let generation=0,controller:AbortController|undefined,stopReason=''
  function clearResults() {
    generation++;controller?.abort();controller=undefined
    loading.value=false;rows.value=[];issues.value=[];phase.value='';cutoff.value='';expandedAt.value='';error.value='';snapshot.value=null;archive.value=null
  }
  function setOwner(next:string) {
    if(next===owner.value)return
    clearResults();owner.value=next;selectedId.value='';periods.value=['DAY']
  }
  function stop(reason='已停止 · 已完成结果保留') {
    if(!loading.value)return
    stopReason=reason;controller?.abort();phase.value='正在停止，已完成结果将保留'
  }
  async function run(group:TrackingGroup,revision:string,adapter:TrackingRunAdapter) {
    if(loading.value||!owner.value||!group.targets.length||!periods.value.length||!canStart())return
    selectedId.value=group.id
    clearResults()
    const version=generation,account=owner.value
    const selected=JSON.parse(JSON.stringify(group)) as TrackingGroup,chosen=[...periods.value]
    const asOf=adapter.now()
    snapshot.value={group:selected,periods:chosen,revision}
    controller=new AbortController();const signal=controller.signal
    const valid=()=>version===generation&&owner.value===account
    loading.value=true;cutoff.value=asOf;stopReason='已停止 · 已完成结果保留'
    phase.value='正在展开板块全部成员…'
    try {
      const expanded=await expandTrackingGroup(selected,code=>adapter.members(code,signal,account),signal)
      if(!valid())return
      signal.throwIfAborted();issues.value=expanded.issues;expandedAt.value=adapter.now()
      phase.value='按统一截止时间逐标的分析'
      await analyzeTrackingEntries(expanded.entries,
        (target,signal)=>adapter.analyze(target,chosen,asOf,signal,account),signal,
        next=>{if(valid())rows.value=next})
      if(valid())phase.value=signal.aborted?stopReason:issues.value.length||failed.value?'分析结束 · 存在未完成项目，请查看失败原因':'分析完成'
    } catch(e) {
      if(valid()) {
        if(signal.aborted)phase.value=stopReason
        else {error.value=e instanceof Error?e.message:String(e);phase.value='分析未完成'}
      }
    } finally {
      if(valid()){
        try{
          archive.value={
            format:'tracking-analysis-v2',group:selected,revision,periods:chosen,cutoff:asOf,
            finished_at:new Date().toISOString(),membership_observed_at:expandedAt.value,
            state:signal.aborted?'cancelled':error.value?'failed':issues.value.length||failed.value?'partial':'completed',
            phase:phase.value,error:error.value,rows:rows.value,issues:issues.value,
          }
          loading.value=false;controller=undefined
          if(onFinished)await onFinished(archive.value)
        } finally {if(valid()){loading.value=false;controller=undefined}}
      }
    }
  }
  return {owner,selectedId,periods,rows,issues,loading,phase,cutoff,expandedAt,error,snapshot,archive,completed,successful,failed,clearResults,setOwner,stop,run}
}
