<script setup lang="ts">
import {ref,onBeforeUnmount,watch} from 'vue'
import {useAuth} from '../auth'
import {archiveClient,type ArchiveRecord} from '../cloud-archives'
import type {FactorTrackingSource} from '../factor-tracking'
import {factorValue} from '../factor-research'
const props=defineProps<{source:FactorTrackingSource}>()
const {currentUser}=useAuth(),request=archiveClient(()=>currentUser.value?.id)
const busy=ref(false),error=ref('')
let generation=0,controller:AbortController|null=null
function reset(){generation++;controller?.abort();busy.value=false;error.value=''}
watch([()=>currentUser.value?.id,()=>props.source],reset,{flush:'sync'});onBeforeUnmount(reset)
async function download(){
  if(busy.value)return
  const stamp=++generation;controller=new AbortController();busy.value=true;error.value=''
  try{
    const record=await request<ArchiveRecord>(`/${props.source.archive_id}`,{signal:controller.signal})
    if(stamp!==generation)return
    if(record.kind!=='factor'||record.digest!==props.source.archive_digest)throw Error('来源摘要不一致，未采用该内容')
    const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'})),a=document.createElement('a')
    a.href=url;a.download=`因子原档-${record.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
  }catch(e){if(stamp===generation)error.value=`${e instanceof Error?e.message:String(e)}。来源索引与初始评分仍保留；原档若已清除，需从之前的导出恢复。`}
  finally{if(stamp===generation)busy.value=false}
}
</script>
<template><details class="factor-source"><summary>因子研究来源 · {{ source.date }}</summary><div class="source-body">
  <p>{{ source.title }} · {{ source.score_label }}。以下为建立分组时的选择，不随当前成员或后续行情更新。</p>
  <div class="source-table"><table><thead><tr><th>初始标的</th><th>原始评分</th></tr></thead><tbody><tr v-for="item in source.selection" :key="item.symbol"><td>{{ item.symbol }}</td><td :title="String(item.score)">{{ factorValue(item.score) }}</td></tr></tbody></table></div>
  <p>原档 {{ source.archive_id }} · v{{ source.archive_revision }}<br>内容摘要：{{ source.archive_digest }}<br>计算指纹：{{ source.input_fingerprint }}</p>
  <p>来源是用户保存的研究记录，摘要只用于一致性核验，不代表行情真实性或投资建议。显示名称不是历史证券名称证明。</p>
  <button :disabled="busy" @click="download">{{ busy?'正在读取原档…':'下载完整研究原档' }}</button><p v-if="error" role="alert">{{ error }}</p>
</div></details></template>
<style scoped>
.factor-source{min-width:0;border-block:1px solid var(--border);padding:12px 0;margin-block:12px}summary{font-size:12px;cursor:pointer}.source-body{padding:10px 0 0 12px}p{font-size:11px;color:var(--text-muted);line-height:1.8;overflow-wrap:anywhere}.source-table{overflow:auto;max-height:250px}table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);font-weight:400}td:last-child,th:last-child{text-align:right;font-variant-numeric:tabular-nums}th{color:var(--text-muted)}button{font-size:11px;padding:7px 10px}[role=alert]{color:var(--red)}@media(max-width:550px){.source-body{padding-left:0}}
</style>
