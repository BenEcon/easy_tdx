<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useAuth } from '../auth'
import { detachBacktest } from '../backtest-archive'
import { portfolioRequestMatches, samePortfolioValue, validatePortfolioArchive, type PortfolioArchive, type PortfolioRequest } from '../portfolio-archive'
import type { PortfolioResult } from '../types'
import type { ArchiveDraft } from '../cloud-archives'
import CloudResearchArchives from './CloudResearchArchives.vue'
const props=defineProps<{kind:'portfolio'|'multi_strategy';taskId:string;request:PortfolioRequest|null;result:PortfolioResult|null;busy:boolean}>()
const {currentUser}=useAuth()
const reading=ref(false),error=ref(''),prepared=shallowRef<{owner:string;archive:PortfolioArchive}|null>(null)
let generation=0,controller:AbortController|null=null
function clear(){generation++;controller?.abort();controller=null;reading.value=false;error.value='';prepared.value=null}
watch(()=>[currentUser.value?.id,props.taskId,props.request,props.result,props.busy,props.kind],clear,{flush:'sync'})
onBeforeUnmount(clear)
async function prepare(){
  if(reading.value||props.busy||!props.result||!props.request)return
  clear()
  const owner=currentUser.value?.id,id=props.taskId,kind=props.kind
  if(!owner||!id){error.value='没有可读取的原任务，请保留现有结果；不会自动重跑。';return}
  const version=generation,request=detachBacktest(props.request),result=detachBacktest(props.result)
  controller=new AbortController();reading.value=true
  const current=()=>version===generation&&owner===currentUser.value?.id&&props.taskId===id&&!props.busy&&samePortfolioValue(props.request,request)&&samePortfolioValue(props.result,result)
  try{
    const response=await fetch(`/api/v1/backtest/tasks/${encodeURIComponent(id)}/portfolio-evidence`,{signal:controller.signal,credentials:'same-origin',cache:'no-store',headers:{'X-Task-Owner':owner,'X-Query-Origin':'system'}})
    const receipt=await response.json()
    if(!current())return
    if(!response.ok)throw Error(typeof receipt?.detail==='string'?receipt.detail:`原档读取失败（${response.status}），未重新取数或计算`)
    const archive=validatePortfolioArchive({format:'portfolio-research-v1',title:`${kind==='portfolio'?'组合':'多策略'}回测原档`,savedAt:new Date().toISOString(),receipt})
    if(archive.receipt.task_id!==id||archive.receipt.kind!==kind||!portfolioRequestMatches(request,archive.receipt.request)||!samePortfolioValue(result,archive.receipt.result))throw Error('原任务与当前回测结果不一致，未拼接保存')
    prepared.value={owner,archive:detachBacktest(archive)}
  }catch(e){if(current())error.value=e instanceof Error?e.message:String(e)}
  finally{if(version===generation){reading.value=false;controller=null}}
}
function capture():ArchiveDraft {
  const saved=prepared.value
  if(props.busy||!saved||saved.owner!==currentUser.value?.id||saved.archive.receipt.task_id!==props.taskId||!portfolioRequestMatches(props.request,saved.archive.receipt.request)||!samePortfolioValue(props.result,saved.archive.receipt.result))throw Error('请先读取当前任务的完整原档')
  return {kind:'portfolio',name:saved.archive.title,note:'',payload:detachBacktest(saved.archive)}
}
function download(){
  try{const draft=capture(),url=URL.createObjectURL(new Blob([JSON.stringify(draft.payload,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`tdx-${props.kind}-${props.taskId}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  catch(e){error.value=e instanceof Error?e.message:String(e)}
}
</script>
<template>
  <section class="portfolio-archive-tools" aria-label="完整组合原档">
    <div class="archive-actions"><strong>完整回测原档</strong><button :disabled="reading||busy||!result||!request" @click="prepare">{{ reading?'正在读取原任务…':prepared?'重新读取原档':'读取完整原档' }}</button><button v-if="prepared" :disabled="busy||reading" @click="download">导出完整 JSON</button></div>
    <p v-if="prepared" role="status">已读取 {{ prepared.archive.receipt.members.length }} 个成员的原行情、参数、成交、持仓及组合结果，可导出或保存到云端。原任务清理后，已保存的副本仍可查看。</p>
    <p v-else>读取原任务后再保存；不补取行情、不重新计算。旧任务缺少原输入时将说明原因。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <CloudResearchArchives :capture="prepared?capture:undefined" :busy="busy||reading" />
  </section>
</template>
<style scoped>
.portfolio-archive-tools{min-width:0;border-block:1px solid var(--border);padding:14px 0;display:grid;grid-template-columns:minmax(0,1fr);gap:10px}.archive-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.archive-actions strong{font-size:13px;margin-right:auto}button{font:inherit;font-size:12px;line-height:1.4;border:1px solid var(--border);border-radius:8px;padding:7px 12px;color:var(--text);background:var(--bg-card);cursor:pointer;transition:background .15s}button:hover:not(:disabled){background:var(--bg-hover)}button:disabled{opacity:.45;cursor:default}p{margin:0;color:var(--text-muted);font-size:12px;line-height:1.8;overflow-wrap:anywhere}[role=alert]{color:var(--red)}
</style>
