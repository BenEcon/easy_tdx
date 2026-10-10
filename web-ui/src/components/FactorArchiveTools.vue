<script setup lang="ts">
import {ref,watch} from 'vue'
import {factorArchiveDraft,validateFactorArchive,type FactorArchive} from '../factor-archive'
import {freezeArchiveDraft} from '../cloud-archives'
import CloudResearchArchives from './CloudResearchArchives.vue'
const props=defineProps<{mode:FactorArchive['mode'];result:unknown;payload?:FactorArchive;busy?:boolean}>()
const error=ref('')
watch(()=>props.result,()=>{error.value=''})
function capture(){
  if(props.payload){const payload=validateFactorArchive(props.payload);return freezeArchiveDraft({kind:'factor',name:payload.title,note:'',payload})}
  return factorArchiveDraft(props.mode,props.result)
}
function download(){
  error.value=''
  try{const draft=capture(),url=URL.createObjectURL(new Blob([JSON.stringify(draft.payload,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`${draft.name}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  catch(e){error.value=e instanceof Error?e.message:String(e)}
}
</script>
<template><section class="factor-archive-tools" aria-label="因子研究存档">
  <div class="archive-actions"><button :disabled="!result||busy" @click="download">导出完整研究</button><p>保存原始输入、实际参数、公式版本及结果；重开只读，不自动取数或计算。</p></div>
  <p v-if="error" role="alert">{{ error }}</p>
  <CloudResearchArchives :capture="result?capture:undefined" :busy="busy" />
</section></template>
<style scoped>
.factor-archive-tools{min-width:0;border-top:1px solid var(--border);padding-top:14px}.archive-actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}p{font-size:11px;color:var(--text-muted);line-height:1.8;margin:0;flex:1;min-width:180px}button{border:1px solid var(--border);border-radius:8px;padding:7px 12px;background:var(--bg-card);color:var(--text);font-size:12px;cursor:pointer;transition:background .15s}button:hover:not(:disabled){background:var(--bg-hover)}button:disabled{opacity:.45;cursor:default}[role=alert]{color:var(--red);margin-block:8px}
</style>
