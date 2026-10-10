<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useAuth } from '../auth'
import { archiveClient, type ArchiveDraft, type ArchiveRecord } from '../cloud-archives'
import { planArchiveRecompute, checkRecomputeResult, compareArchiveValues, recomputeComparable, recomputedArchiveDraft, type RecomputePlan, type RecomputeResult, type ArchiveDifference } from '../archive-recompute'
import { compareArchiveEvents, type ArchiveEventComparison as EventReport } from '../archive-event-comparison'
import ArchiveEventComparison from './ArchiveEventComparison.vue'

const props=defineProps<{record:ArchiveRecord}>()
const {currentUser}=useAuth(), request=archiveClient(()=>currentUser.value?.id)
const plan=shallowRef<RecomputePlan|null>(null), message=ref(''), busy=ref(false), complete=ref(false), saved=ref(false)
const results=shallowRef<Array<{category:string;response:RecomputeResult;differences:ArchiveDifference[];events:EventReport}>>([])
const pending=shallowRef<{owner:string;id:string;draft:ArchiveDraft}|null>(null)
const selected=ref(0), page=ref(0), finishedAt=ref('')
const active=computed(()=>results.value[selected.value]), differences=computed(()=>active.value?.differences??[])
const visible=computed(()=>differences.value.slice(page.value*100,(page.value+1)*100))
let generation=0, controller:AbortController|null=null
function reset(){generation++;controller?.abort();busy.value=false;plan.value=null;results.value=[];pending.value=null;message.value='';complete.value=false;saved.value=false;selected.value=0;page.value=0}
watch(()=>props.record,reset);watch(()=>currentUser.value?.id,reset);watch(selected,()=>page.value=0);onBeforeUnmount(reset)
function inspect(){if(busy.value||pending.value)return;reset();try{plan.value=planArchiveRecompute(props.record)}catch(error){message.value=error instanceof Error?error.message:String(error)}}
function cancel(){generation++;controller?.abort();busy.value=false;complete.value=false;message.value='已取消等待；服务端已开始的计算或保存可能继续。原档未修改，未将未完成重算标为完成。'}
async function run(){
  const owner=currentUser.value?.id, captured=plan.value
  if(!owner||!captured||busy.value||pending.value)return
  const version=++generation;controller=new AbortController();const signal=controller.signal,valid=()=>version===generation&&currentUser.value?.id===owner
  busy.value=true;complete.value=false;saved.value=false;results.value=[];selected.value=0;page.value=0;message.value='正在使用保存的原行情重算…'
  try{
    for(const job of captured.jobs){
      if(!valid())return
      const requestId=crypto.randomUUID()
      const response=await fetch('/api/v1/chanlun/archive-recompute',{method:'POST',headers:{'Content-Type':'application/json','X-Query-Origin':'user','X-Research-Owner':owner},body:JSON.stringify({...job.request,request_id:requestId}),signal,credentials:'same-origin',cache:'no-store'})
      const body:unknown=await response.json().catch(()=>null)
      if(!valid())return
      if(!response.ok)throw Error(body&&typeof body==='object'&&'detail' in body&&typeof body.detail==='string'?body.detail:`重算接口返回 ${response.status}；请检查原档参数或稍后重试`)
      const next=checkRecomputeResult(body,job,requestId)
      if(results.value.length&&results.value[0]!.response.execution_version!==next.execution_version)throw Error('各周期执行版本不一致，未标记为完整重算，请重试')
      results.value=[...results.value,{category:job.category,response:next,differences:compareArchiveValues(job.before,recomputeComparable(next)),events:compareArchiveEvents(job.before,next.result)}]
    }
    if(valid()){finishedAt.value=new Date().toISOString();complete.value=true;message.value='所选原档的可重算内容已计算完成；原档未覆盖。请核对差异后决定是否保存新副本。'}
  }catch(error){if(valid())message.value=error instanceof Error?error.message:String(error)}finally{if(valid())busy.value=false}
}
async function save(){
  const owner=currentUser.value?.id
  if(!owner||!plan.value||busy.value||saved.value||(!complete.value&&!pending.value))return
  try{if(!pending.value)pending.value={owner,id:crypto.randomUUID(),draft:recomputedArchiveDraft(props.record,plan.value,results.value.map(row=>row.response),finishedAt.value)}}
  catch(error){message.value=error instanceof Error?error.message:String(error);return}
  const upload=pending.value!;if(upload.owner!==owner){reset();return}
  const version=++generation;controller=new AbortController();busy.value=true
  try{
    const result=await request<ArchiveRecord>(`/${upload.id}`,{method:'PUT',body:JSON.stringify(upload.draft),signal:controller.signal})
    if(version!==generation)return
    pending.value=null;saved.value=true;message.value=result.state==='active'?'重算新副本已保存，关闭后刷新云目录查看；来源原档未修改。':'该新副本已在回收站，未自动恢复。'
  }catch(error){if(version===generation)message.value=`新副本尚未确认保存，可用同一 ID 重试。${error instanceof Error?error.message:String(error)}`}
  finally{if(version===generation)busy.value=false}
}
function exportReport(){
  if(!results.value.length||busy.value)return
  const report={format:'archive-recompute-comparison-v1',complete:complete.value,finished_at:finishedAt.value||null,source:props.record,requests:plan.value?.jobs.map(job=>job.request),warnings:plan.value?.warnings,runs:results.value}
  const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),anchor=document.createElement('a')
  anchor.href=url;anchor.download=`tdx-recompute-${props.record.id}.json`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
const valueText=(value:unknown,present:boolean)=>!present?'〈字段缺失〉':JSON.stringify(value)
</script>
<template>
  <details class="archive-recompute" aria-label="存档重算与版本对照">
    <summary>按当前版本重算与对照 <span>手动确认 · 不覆盖原档</span></summary>
    <div class="recompute-content">
      <p>查看原档不会计算。确认后使用保存的行情与指标参数重算，对照结构、均线及技术指标；旧档缺少参数的范围会明确列出。</p>
      <button :disabled="busy||!!pending||!currentUser" @click="inspect">检查重算条件</button>
      <template v-if="plan">
        <ul><li v-for="warning in plan.warnings" :key="warning">{{ warning }}</li></ul>
        <p>计算范围：{{ plan.jobs.map(job=>job.category).join('、') }}。单周期最多 800 根，不自动裁剪。</p>
        <ul v-if="record.kind==='chart'" class="indicator-scope"><li v-for="job in plan.jobs" :key="job.category">{{ job.category }} · {{ job.frozenBefore ? `${job.frozenBefore.averages.length} 条均线 · ${job.frozenBefore.indicators.map(item=>item.label).join('、') || '无副图指标'}` : '原档无冻结指标参数，仅结构与 MACD' }}</li></ul>
        <div class="recompute-actions"><button :disabled="busy||!!pending" @click="run">确认按当前版本重算</button><button v-if="busy" @click="cancel">取消等待</button><button v-if="complete||pending" :disabled="busy||saved" @click="save">{{ saved?'新副本已保存':pending?'重试保存新副本':'另存重算新副本' }}</button><button v-if="results.length" :disabled="busy" @click="exportReport">导出完整对照记录</button></div>
      </template>
      <p v-if="message" role="status" aria-live="polite">{{ message }}</p>
      <template v-if="results.length">
        <div class="recompute-tabs" aria-label="选择对照周期"><button v-for="(row,i) in results" :key="row.category" :aria-pressed="selected===i" @click="selected=i">{{ row.category }} · {{ row.differences.length }} 处差异</button></div>
        <template v-if="active">
          <details><summary>本次执行版本与参数</summary><pre>{{ JSON.stringify({version:active.response.execution_version,input_digest:active.response.input_digest,scope:active.response.scope,parameters:active.response.parameters},null,2) }}</pre></details>
          <ArchiveEventComparison :report="active.events" />
          <h4>原始字段对照</h4>
          <p>按字段路径与数组原顺序对照，增删可能使后续位置移动，不等同于新增交易信号。数值保留原精度；“字段缺失”与 null 分开。完整内容可导出。</p>
          <p v-if="!differences.length">可比较的结果字段一致；不代表原执行版本或行情真实性已被验证。</p>
          <div v-else class="diff-scroll" role="region" tabindex="0" aria-label="原档与重算差异表"><table><caption>窄屏可在表格内横向滚动查看完整对照</caption><thead><tr><th>字段路径</th><th>原档</th><th>本次重算</th></tr></thead><tbody><tr v-for="row in visible" :key="row.path"><th scope="row">{{ row.path }}</th><td><pre>{{ valueText(row.before,row.beforePresent) }}</pre></td><td><pre>{{ valueText(row.after,row.afterPresent) }}</pre></td></tr></tbody></table></div>
          <div v-if="differences.length>100" class="recompute-actions"><button :disabled="page===0" @click="page--">上一页</button><span>第 {{ page+1 }} / {{ Math.ceil(differences.length/100) }} 页 · 共 {{ differences.length }} 处</span><button :disabled="(page+1)*100>=differences.length" @click="page++">下一页</button></div>
          <details><summary>完整重算结果（原始精度）</summary><pre>{{ JSON.stringify(recomputeComparable(active.response),null,2) }}</pre></details>
        </template>
      </template>
    </div>
  </details>
</template>
<style scoped>
caption{text-align:left;padding:8px 12px;font-size:10px;color:var(--text-muted)}
.archive-recompute{margin:18px 0;border-block:1px solid var(--border);min-width:0}summary{padding:12px 0;font-size:12px;cursor:pointer}summary>span{font-size:10px;color:var(--text-muted);margin-left:10px}.recompute-content{padding:0 0 14px 18px;min-width:0}p,li{font-size:11px;color:var(--text-muted);line-height:1.8;overflow-wrap:anywhere}ul{padding-left:18px}.recompute-actions,.recompute-tabs{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}.recompute-actions span{font-size:11px;color:var(--text-muted)}button{font-size:11px;padding:6px 10px;min-height:32px;border:1px solid var(--border);border-radius:7px;background:var(--bg-elevated);color:var(--text-muted);cursor:pointer;transition:color .15s,border-color .15s}button:disabled{opacity:.5;cursor:default}button[aria-pressed=true],button:hover:not(:disabled){color:var(--accent);border-color:var(--accent)}pre{font-size:11px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}details details{border-top:1px solid var(--border)}.diff-scroll{max-width:100%;overflow:auto;max-height:480px;border-block:1px solid var(--border)}table{border-collapse:collapse;table-layout:fixed;width:100%;min-width:620px;font-size:11px}th,td{padding:9px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border);overflow-wrap:anywhere}th{font-weight:500;color:var(--text-muted)}thead{position:sticky;top:0;background:var(--bg-panel,#1c1e23)}td pre{margin:0;max-height:160px}button:focus-visible,summary:focus-visible,.diff-scroll:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:600px){.recompute-content{padding-left:0}.recompute-actions button{min-height:36px}summary>span{display:block;margin:5px 0 0 14px}}@media(prefers-reduced-motion:reduce){button{transition:none}}
</style>
