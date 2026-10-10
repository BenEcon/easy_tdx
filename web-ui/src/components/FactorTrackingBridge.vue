<script setup lang="ts">
import {computed,onBeforeUnmount,ref,shallowRef,watch} from 'vue'
import {useAuth,refreshCurrentUser} from '../auth'
import {canUseTracking} from '../feature-access'
import {factorArchiveDraft} from '../factor-archive'
import type {ArchiveDraft,ArchiveRecord} from '../cloud-archives'
import type {FactorEvaluation} from '../factor-research'
import {factorValue} from '../factor-research'
import {factorTrackingClient,trackingScoreOptions,trackingScoreRows} from '../factor-tracking'
import {stockDisplayName} from '../stock-history'
import MacSelect from './MacSelect.vue'
const props=defineProps<{result:FactorEvaluation;record?:ArchiveRecord}>()
const {currentUser}=useAuth(),client=factorTrackingClient(()=>currentUser.value?.id)
const allowed=computed(()=>canUseTracking(currentUser.value))
const options=computed(()=>trackingScoreOptions(props.result))
const choice=ref(''),selected=ref<string[]>([]),name=ref('因子研究观察'),error=ref(''),busy=ref(false),message=ref(''),groupId=ref('')
const key=computed(()=>options.value.some(o=>o.value===choice.value)?choice.value:options.value[0]?.value??'')
const rows=computed(()=>trackingScoreRows(props.result,key.value))
const saved=shallowRef<ArchiveRecord|null>(null),pending=shallowRef<{id:string;draft:ArchiveDraft}|null>(null)
let generation=0,controller:AbortController|null=null
function clear(){generation++;controller?.abort();controller=null;busy.value=false;saved.value=null;pending.value=null;selected.value=[];error.value='';message.value='';groupId.value=''}
watch([()=>props.result,()=>props.record,()=>currentUser.value?.id,allowed],clear,{flush:'sync'})
watch(key,()=>{selected.value=[];message.value='';groupId.value=''},{flush:'sync'})
onBeforeUnmount(clear)
function toggle(symbol:string){selected.value=selected.value.includes(symbol)?selected.value.filter(s=>s!==symbol):[...selected.value,symbol];message.value='';groupId.value=''}
function display(symbol:string){const code=symbol.split(':')[1]??symbol;return `${symbol.split(':')[0]} · ${stockDisplayName(code)}`}
async function create(){
  if(busy.value||!allowed.value||!selected.value.length||!name.value.trim())return
  const stamp=++generation,owner=currentUser.value?.id
  controller=new AbortController();const signal=controller.signal
  const valid=()=>stamp===generation&&currentUser.value?.id===owner&&allowed.value
  const labels=Object.fromEntries(selected.value.map(symbol=>{const code=symbol.split(':')[1]!,label=stockDisplayName(code);return [symbol,label.startsWith(`${code}-`)?label.slice(code.length+1):'']}))
  const selection={name:name.value.trim(),score_key:key.value,symbols:[...selected.value],labels}
  busy.value=true;error.value='';message.value='';groupId.value=''
  try{
    if(!props.record&&!saved.value){
      if(!pending.value)pending.value={id:crypto.randomUUID(),draft:factorArchiveDraft('evaluation',props.result)}
      const record=await client.save(pending.value.id,pending.value.draft,signal)
      if(!valid())return
      saved.value=record;pending.value=null
    }
    const record=props.record??saved.value!
    const result=await client.create(record,selection,signal)
    if(!valid())return
    groupId.value=result.group.id
    message.value=result.created?'已建立观察清单，保留原档和初始评分。':'该原档与选择已建立过分组；保留现有分组，不覆盖后续编辑。'
    try{await refreshCurrentUser()}catch{if(valid())message.value+=' 账户清单刷新失败，请到追踪页面刷新核实。'}
  }catch(e){if(valid())error.value=`${saved.value?'原研究已保存；建立分组未完成，可重试。':''}${e instanceof Error?e.message:String(e)}`}
  finally{if(valid())busy.value=false}
}
</script>
<template><details class="factor-tracking-bridge"><summary>从评分建立追踪分组 <span>手动选择 · 保留原档</span></summary>
  <div class="bridge-body">
    <p>仅使用 {{ result.end }} 的已保存评分。不自动选股、不下单、不启动分析；分组后续行情与本次原档分别保留。</p>
    <p v-if="!allowed" role="status">追踪标的仅向管理员和已授权用户开放；不影响保存和查看因子研究。</p>
    <template v-else>
      <div class="bridge-controls"><label>评分依据<MacSelect :model-value="key" aria-label="追踪评分依据" :disabled="busy" :options="options" @update:model-value="choice=$event" /></label><label>新分组名称<input v-model="name" aria-label="因子追踪分组名称" maxlength="40" :disabled="busy"></label></div>
      <div class="bridge-table" tabindex="0" aria-label="选择评分标的"><table><thead><tr><th>选择</th><th>标的</th><th>原始评分</th></tr></thead><tbody><tr v-for="row in rows" :key="row.code"><td><input type="checkbox" :checked="selected.includes(row.code)" :disabled="busy||!row.eligible" :aria-label="`追踪 ${row.code}`" @change="toggle(row.code)"></td><th>{{ display(row.code) }}<small v-if="!row.eligible">{{ row.value===null?'此日评分缺失，不能选择':'此入口仅支持 A 股，请按正确类型手动追踪' }}</small></th><td :title="String(row.value??'缺失')">{{ factorValue(row.value) }}</td></tr></tbody></table></div>
      <footer><span>已选择 {{ selected.length }} / {{ rows.length }} 个标的</span><button :disabled="busy||!selected.length||!name.trim()" @click="create">{{ busy?'正在保存来源与分组…':record||saved?'由此原档创建追踪分组':'保存原档并创建追踪分组' }}</button></footer>
      <p v-if="saved" class="saved-reference">来源原档 {{ saved.id }} · v{{ saved.revision }}。重试复用同一原档。</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="message" role="status">{{ message }} <RouterLink v-if="groupId" :to="{path:'/tracking',query:{group:groupId}}">查看追踪分组 →</RouterLink></p>
    </template>
  </div>
</details></template>
<style scoped>
.factor-tracking-bridge{border-top:1px solid var(--border);padding-top:14px;min-width:0}summary{cursor:pointer;font-size:12px;line-height:1.8}summary span{margin-left:10px;font-size:11px;color:var(--text-muted)}.bridge-body{padding:12px 0 0 12px;min-width:0}p{font-size:11px;line-height:1.8;color:var(--text-muted);overflow-wrap:anywhere;margin:8px 0}.bridge-controls{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0}label{display:flex;flex-direction:column;gap:7px;font-size:11px;color:var(--text-muted);min-width:0}label input{width:100%;min-width:0}.bridge-table{overflow:auto;max-height:300px;border-block:1px solid var(--border)}table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:10px 12px;border-bottom:1px solid var(--border);text-align:left;font-weight:400}thead th{position:sticky;top:0;background:var(--bg-panel);color:var(--text-muted);z-index:1}td:last-child,th:last-child{text-align:right;font-variant-numeric:tabular-nums}td:first-child{width:40px}input[type=checkbox]{width:16px;height:16px;min-height:0;accent-color:var(--accent)}small{display:block;font-size:10px;line-height:1.7;color:var(--text-muted)}footer{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-top:12px}footer span{font-size:11px;color:var(--text-muted)}button{font-size:12px;padding:8px 12px;min-height:34px;border-radius:8px}button:disabled{opacity:.45}.error{color:var(--red)}a{color:var(--accent)}.saved-reference{font-size:10px}.bridge-table:focus-visible{outline:2px solid var(--accent)}@media(max-width:550px){.bridge-controls{grid-template-columns:1fr}.bridge-body{padding-left:0}summary span{display:block;margin-left:15px}td,th{padding:10px 8px}}
</style>
<style scoped>
.bridge-table th:first-child,.bridge-table td:first-child{width:56px;min-width:56px;white-space:nowrap}
</style>
