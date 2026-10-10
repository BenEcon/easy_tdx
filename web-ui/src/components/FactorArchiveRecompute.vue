<script setup lang="ts">
import {computed,onBeforeUnmount,ref,shallowRef,watch} from 'vue'
import {useAuth} from '../auth'
import {archiveClient,freezeArchiveDraft,type ArchiveDraft,type ArchiveRecord} from '../cloud-archives'
import {validateFactorArchive,factorRecomputedArchive,type FactorArchive} from '../factor-archive'
import {submitFactorRecomputeTask,fetchTask,cancelTask} from '../api'
import {taskExecution} from '../task-execution'
import {taskStatusLabel,taskElapsed} from '../task-state'
import {taskProgressLabel} from '../task-progress'
import FactorArchivePreview from './FactorArchivePreview.vue'
const props=defineProps<{record:ArchiveRecord}>()
const {currentUser}=useAuth(),request=archiveClient(()=>currentUser.value?.id)
const confirmed=ref(false),saving=ref(false),message=ref(''),saved=ref(false)
const task=taskExecution<Parameters<typeof submitFactorRecomputeTask>[0],FactorArchive>({owner:()=>currentUser.value?.id,submit:submitFactorRecomputeTask,poll:fetchTask,cancel:cancelTask,timeout:12*60*1000,interval:1000})
const {running,state,taskId,error:taskError,cancelError,cancelling}=task
const busy=computed(()=>running.value||saving.value)
const taskStatus=computed(()=>state.value?`${taskStatusLabel(state.value)} · ${taskElapsed(state.value.elapsed??0)}`:running.value?'正在冻结原档并提交任务…':'')
const result=shallowRef<FactorArchive|null>(null),pending=shallowRef<{id:string;owner:string;draft:ArchiveDraft}|null>(null)
let generation=0,controller:AbortController|undefined
function reset(){generation++;controller?.abort();task.clear();saving.value=false;confirmed.value=false;message.value='';result.value=null;pending.value=null;saved.value=false}
watch([()=>props.record.id,()=>props.record.digest,()=>props.record.revision,()=>currentUser.value?.id],reset,{flush:'sync'});onBeforeUnmount(reset)
function cancel(){generation++;controller?.abort();task.clear();saving.value=false;message.value='已停止等待，后台工作可能继续；请到个人账户查看。原档未覆盖，未将停止等待视为完成。'}
async function run(){
  const owner=currentUser.value?.id;if(!owner||!confirmed.value||busy.value||pending.value)return
  const stamp=++generation;message.value='';result.value=null;saved.value=false
  const source={id:props.record.id,digest:props.record.digest,revision:props.record.revision}
  try{
    validateFactorArchive(props.record.payload)
    const completed=await task.run({source_archive_id:source.id,expected_digest:source.digest,expected_revision:source.revision},true)
    if(stamp!==generation||currentUser.value?.id!==owner||!completed)return
    const checked=factorRecomputedArchive(task.result.value,source)
    result.value=checked;message.value='重算已返回。请核对下方成功与失败结果，再保存为新版本；原档未改变。'
  }catch(e){if(stamp===generation)message.value=e instanceof Error?e.message:String(e)}
}
async function save(){
  const owner=currentUser.value?.id;if(!owner||busy.value||saved.value||!result.value)return
  if(!pending.value)pending.value={id:crypto.randomUUID(),owner,draft:freezeArchiveDraft({kind:'factor',name:`${props.record.name.slice(0,110)} · 重算`,note:props.record.note,payload:result.value})}
  if(pending.value.owner!==owner){reset();return}
  const upload=pending.value,stamp=++generation;controller=new AbortController();saving.value=true
  try{const stored=await request<ArchiveRecord>(`/${upload.id}`,{method:'PUT',body:JSON.stringify(upload.draft),signal:controller.signal});if(stamp!==generation)return;pending.value=null;saved.value=true;message.value=stored.state==='active'?'新版本已保存；关闭后刷新云目录查看，原档未改变。':'新版本已在回收站，未自动恢复。'}
  catch(e){if(stamp===generation)message.value=`尚未确认保存，可用同一 ID 重试。${String(e)}`}
  finally{if(stamp===generation)saving.value=false}
}
</script>
<template><details class="factor-recompute"><summary>按原始输入显式重算</summary>
  <p>使用本机当前公式实现与存档中的实际参数，不刷新行情。原始输入由账户存档提供，未经行情真实性验证。结果可能与旧版本不同；保存时创建独立新版本，不覆盖原档。</p>
  <label><input v-model="confirmed" type="checkbox" :disabled="busy||!!pending"> 我已确认使用原输入与当前实现</label>
  <div class="actions"><button :disabled="!confirmed||busy||!!pending||record.state!=='active'" @click="run">开始重算</button><button v-if="running&&taskId" :disabled="cancelling||state?.status==='cancelling'" @click="task.cancel">{{ cancelling?'正在提交取消…':'取消后台任务' }}</button><button v-if="busy" @click="cancel">停止等待</button><button v-if="result" :disabled="busy||saved" @click="save">{{ pending?'重试保存新版本':'保存为新版本' }}</button></div>
  <div v-if="running||taskId||taskError" class="task-status">
    <p role="status" aria-live="polite">{{ taskStatus }}</p>
    <p v-if="state?.progress">{{ taskProgressLabel(state.progress) }} · 本阶段处理量，不是总体完成比例</p>
    <p>关闭原档或停止等待不会取消后台计算。关闭原档后，可在个人账户 → 后台计算核实提交状态、取回完整结果。</p>
    <p v-if="taskError" role="alert">{{ taskError }}</p><p v-if="cancelError" role="alert">取消未确认：{{ cancelError }}</p>
  </div>
  <p v-if="message" role="status">{{ message }}</p>
  <details v-if="result"><summary>本次重算结果（尚不替换原档）</summary><FactorArchivePreview :payload="result" /></details>
</details></template>
<style scoped>
.factor-recompute{border-block:1px solid var(--border);padding:14px 0;margin:16px 0;min-width:0}summary{font-size:12px;cursor:pointer}p{color:var(--text-muted);font-size:12px;line-height:1.8}label{display:flex;align-items:center;gap:8px;font-size:12px}input{width:14px;height:14px;min-height:0;accent-color:var(--accent)}.actions{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}button{font-size:12px;padding:7px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-card);color:var(--text);cursor:pointer}button:disabled{opacity:.45;cursor:default}details>details{padding:14px 0 0 12px}
</style>
