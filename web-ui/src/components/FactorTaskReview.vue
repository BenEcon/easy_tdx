<script setup lang="ts">
import {ref,shallowRef,nextTick,watch,onBeforeUnmount} from 'vue'
import {fetchTask,formatError} from '../api'
import {useAuth} from '../auth'
import {factorTaskArchive} from '../factor-task-review'
import type {FactorArchive} from '../factor-archive'
import FactorArchivePreview from './FactorArchivePreview.vue'
import FactorArchiveTools from './FactorArchiveTools.vue'

const props=defineProps<{taskId:string}>(),{currentUser}=useAuth()
const dialog=ref<HTMLDialogElement>(),trigger=ref<HTMLButtonElement>(),payload=shallowRef<FactorArchive|null>(null),loading=ref(false),error=ref('')
let generation=0,controller:AbortController|undefined,returnFocus:HTMLElement|null=null
function close(){
  const stamp=++generation,target=returnFocus;returnFocus=null
  controller?.abort();controller=undefined;loading.value=false;dialog.value?.close();payload.value=null
  // Descendant dialogs restore their own focus while unmounting. Restore the
  // surviving launcher afterwards, including Safari pointer activation.
  void nextTick(()=>{if(generation===stamp&&target?.isConnected)target.focus({preventScroll:true})})
}
watch([()=>props.taskId,()=>currentUser.value?.id],()=>{close();error.value=''},{flush:'sync'})
onBeforeUnmount(close)
async function open(){
  close();error.value='';const owner=currentUser.value?.id,stamp=generation
  if(!owner){error.value='请先登录';return}
  const current=()=>generation===stamp&&currentUser.value?.id===owner
  controller=new AbortController();loading.value=true;returnFocus=trigger.value??null
  try{
    const result=await fetchTask(props.taskId,{owner,signal:controller.signal})
    if(!current())return
    payload.value=factorTaskArchive(result,props.taskId)
    await nextTick();if(current())dialog.value?.showModal()
  }catch(e){if(current())error.value=formatError(e)}
  finally{if(current())loading.value=false}
}
</script>
<template><div class="factor-task-review">
  <button ref="trigger" class="sm" :disabled="loading" @click="open">{{ loading?'正在读取…':'打开因子结果' }}</button>
  <p v-if="error" role="alert">{{ error }}</p>
  <Teleport to="body"><dialog ref="dialog" class="factor-task-dialog" aria-label="后台因子研究结果" @cancel.prevent="close">
    <template v-if="payload"><header><div><strong>后台{{ payload.mode==='series'?'因子序列':'因子检验' }} · 只读结果</strong><p>保留任务计算时的行情、参数和数值。保存为个人研究档后，不受任务清理影响。</p></div><button @click="close">关闭结果</button></header>
    <div class="result-scroll"><FactorArchiveTools :mode="payload.mode" :result="payload.result" :payload="payload" /><FactorArchivePreview :payload="payload" /></div></template>
  </dialog></Teleport>
</div></template>
<style scoped>
.factor-task-review{min-width:0}p{font-size:11px;line-height:1.8;color:var(--text-muted);overflow-wrap:anywhere}[role=alert]{color:var(--red)}.factor-task-dialog{margin:auto;width:min(1160px,calc(100vw - 32px));height:min(900px,calc(100dvh - 40px));max-width:none;max-height:none;padding:0;border:1px solid var(--border);border-radius:14px;background:var(--bg-panel,#1c1e23);color:var(--text)}.factor-task-dialog[open]{display:flex;flex-direction:column}.factor-task-dialog::backdrop{background:#0009}header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:18px 22px;border-bottom:1px solid var(--border);flex-shrink:0}header strong{font-size:14px}header>div{min-width:0}header button{flex-shrink:0}.result-scroll{flex:1;min-height:0;overflow:auto;padding:16px 22px;overflow-wrap:anywhere}.result-scroll :deep(.factor-archive-tools){margin-bottom:20px}.sm{white-space:nowrap;font-size:11px}@media(max-width:600px){.factor-task-dialog{width:calc(100vw - 16px);height:calc(100dvh - 20px)}header,.result-scroll{padding:12px}}
</style>
