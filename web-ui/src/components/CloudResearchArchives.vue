<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useAuth } from '../auth'
import { archiveClient, freezeArchiveDraft, type ArchiveDirectory, type ArchiveDraft, type ArchiveRecord } from '../cloud-archives'
import CloudArchivePreview from './CloudArchivePreview.vue'
import LocalArchiveMigration from './LocalArchiveMigration.vue'
import { prepareArchiveImport, type PreparedArchiveImport } from '../archive-import'
const props=withDefaults(defineProps<{ capture?:()=>ArchiveDraft; busy?:boolean; kindFilter?:string; refreshKey?:string }>(),{busy:false})
const {currentUser}=useAuth()
const request=archiveClient(()=>currentUser.value?.id)
const opened=ref(false), loading=ref(false), message=ref(''), failure=ref(false), trash=ref(false)
const directory=shallowRef<ArchiveDirectory|null>(null), viewing=shallowRef<ArchiveRecord|null>(null)
const editing=ref<{id:string;revision:number;name:string;note:string}|null>(null)
const pending=shallowRef<{id:string;owner:string;draft:ArchiveDraft}|null>(null)
const importing=shallowRef<{owner:string;filename:string;prepared:PreparedArchiveImport}|null>(null)
const preparing=ref(false),importInput=ref<HTMLInputElement>()
const migrationBusy=ref(false)
const confirm=ref(''), dialog=ref<HTMLDialogElement>(), returnFocus=ref<HTMLElement|null>(null)
let generation=0, controller:AbortController|null=null
const rows=computed(()=>directory.value?.items.filter(item=>item.state===(trash.value?'deleted':'active')&&(!props.kindFilter||item.kind===props.kindFilter))??[])
watch(()=>props.refreshKey,()=>{directory.value=null;if(opened.value)void refresh()})
function close(){dialog.value?.close();viewing.value=null;returnFocus.value?.focus({preventScroll:true})}
function clear(){generation++;controller?.abort();controller=null;loading.value=false;migrationBusy.value=false;preparing.value=false;importing.value=null;directory.value=null;pending.value=null;editing.value=null;confirm.value='';message.value='';close()}
watch(()=>currentUser.value?.id,()=>{clear();if(opened.value&&currentUser.value)void refresh()})
onBeforeUnmount(clear)
async function operation(work:(signal:AbortSignal,valid:()=>boolean)=>Promise<void>){
  if(loading.value||preparing.value||migrationBusy.value)return
  const version=++generation;controller=new AbortController();loading.value=true;message.value='';failure.value=false
  const valid=()=>version===generation
  try{await work(controller.signal,valid)}catch(error){if(valid()){failure.value=true;message.value=error instanceof Error?error.message:String(error)}}
  finally{if(valid())loading.value=false}
}
async function refresh(){await operation(async(signal,valid)=>{const data=await request<ArchiveDirectory>('',{signal});if(valid()){directory.value=data;confirm.value=''}})}
function toggle(event:Event){opened.value=(event.target as HTMLDetailsElement).open;if(opened.value&&!directory.value)void refresh()}
async function save(){
  if(props.busy||loading.value||preparing.value||importing.value||pending.value||!props.capture)return
  try{if(!pending.value){const owner=currentUser.value?.id;if(!owner)throw Error('请先登录');pending.value={id:crypto.randomUUID(),owner,draft:freezeArchiveDraft(props.capture())}}}
  catch(error){failure.value=true;message.value=String(error);return}
  await uploadPending()
}
async function uploadPending(){
  if(loading.value||preparing.value||!pending.value)return
  const upload=pending.value!
  if(upload.owner!==currentUser.value?.id){clear();return}
  await operation(async(signal,valid)=>{
    const saved=await request<ArchiveRecord>(`/${upload.id}`,{method:'PUT',body:JSON.stringify(upload.draft),signal})
    if(!valid())return
    pending.value=null
    message.value=saved.state==='active'?'已保存到当前账户，可在其他设备刷新云目录查看。':'此存档已在其他设备移入回收站，未自动恢复。'
    try{const data=await request<ArchiveDirectory>('',{signal});if(valid())directory.value=data}
    catch(error){if(valid()){failure.value=true;message.value=`原存档已保存，但目录刷新失败；请刷新目录，不必重新上传。${error instanceof Error?error.message:String(error)}`}}
  })
}
async function importFile(event:Event){
  const input=event.target as HTMLInputElement,file=input.files?.[0],owner=currentUser.value?.id
  if(!file||!owner||loading.value||pending.value||preparing.value){input.value='';return}
  const version=++generation;preparing.value=true;importing.value=null;message.value='';failure.value=false
  try{
    if(file.size>25*1024*1024)throw Error('备份文件不能超过 25MiB，未读取或上传内容')
    const text=await file.text()
    if(version!==generation||owner!==currentUser.value?.id)return
    const prepared=prepareArchiveImport(JSON.parse(text),file.name)
    if(props.kindFilter&&prepared.draft.kind!==props.kindFilter)throw Error('此处仅导入追踪分析备份；其他类型请到个人账户的云存档导入')
    importing.value={owner,filename:file.name,prepared}
  }catch(error){if(version===generation){failure.value=true;message.value=`导入检查失败：${error instanceof Error?error.message:String(error)}`}}
  finally{if(version===generation)preparing.value=false;input.value=''}
}
async function confirmImport(){
  const draft=importing.value
  if(!draft||loading.value||preparing.value||pending.value)return
  if(draft.owner!==currentUser.value?.id){clear();return}
  pending.value={id:crypto.randomUUID(),owner:draft.owner,draft:draft.prepared.draft}
  importing.value=null
  await uploadPending()
}
async function mutate(row:ArchiveRecord,action:'edit'|'delete'|'restore'|'purge'){
  if(action==='purge'&&confirm.value!==row.id){confirm.value=row.id;return}
  await operation(async(signal,valid)=>{
    await request(`/${row.id}/actions`,{method:'POST',body:JSON.stringify({revision:row.revision,action,...(action==='edit'?{name:editing.value!.name,note:editing.value!.note}:{})}),signal})
    if(!valid())return
    editing.value=null;confirm.value=''
    const data=await request<ArchiveDirectory>('',{signal});if(!valid())return
    directory.value=data;message.value=action==='purge'?'已永久删除云端内容，不能恢复；已有导出文件不受影响。':action==='delete'?'已移入回收站，可恢复。':action==='restore'?'已恢复存档。':'名称与备注已保存，原始行情和结果未改变。'
  })
}
async function read(row:ArchiveRecord,download=false){
  await operation(async(signal,valid)=>{
    const data=await request<ArchiveRecord>(`/${row.id}`,{signal});if(!valid())return
    if(download){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`tdx-cloud-${row.id}.json`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
    else{returnFocus.value=document.activeElement as HTMLElement;viewing.value=data;await nextTick();if(valid())dialog.value?.showModal()}
  })
}
const mib=(bytes:number)=>(bytes/1024/1024).toFixed(2)
</script>
<template>
  <details class="cloud-archives research-panel research-hierarchy" @toggle="toggle">
    <summary><strong>{{ kindFilter==='tracking'?'追踪分析历史':'账户云存档' }}</strong><span>{{ kindFilter==='tracking'?'每批自动保存 · 只读核验':'手动保存 · 跨设备查看' }}</span></summary>
    <div class="archive-body">
      <p>仅本人账户可访问；保存原始行情、参数及分析结果，不自动重算。云端与本地副本独立，刷新目录不会覆盖当前研究。</p>
      <LocalArchiveMigration v-if="opened&&!kindFilter" :disabled="loading||preparing||!!pending||!!importing||!!editing" @busy="migrationBusy=$event" @finished="refresh" />
      <div class="archive-controls" :inert="migrationBusy || undefined">
      <div class="archive-toolbar"><button v-if="capture&&!pending" :disabled="busy||loading||preparing||!!importing||!currentUser" @click="save">保存当前结果到云端</button><button :disabled="loading||preparing||!!pending||!currentUser" @click="importInput?.click()">导入研究备份</button><button :disabled="loading||preparing" @click="refresh">刷新云目录</button><button :aria-pressed="trash" @click="trash=!trash;editing=null;confirm=''">{{ trash?'返回存档':'回收站' }}</button></div>
      <input ref="importInput" type="file" accept="application/json,.json" aria-label="选择研究备份文件" hidden @change="importFile" />
      <p v-if="preparing" role="status">正在检查备份文件，尚未上传…</p>
      <section v-if="importing" class="import-preview" aria-label="待导入研究备份"><h4>{{ importing.prepared.draft.name }}</h4><p>{{ importing.filename }} · {{ importing.prepared.description }}</p><p v-for="warning in importing.prepared.warnings" :key="warning">{{ warning }}</p><div class="archive-actions"><button :disabled="loading||preparing" @click="confirmImport">确认导入到当前账户</button><button :disabled="loading" @click="importing=null">取消导入</button></div></section>
      <p v-if="pending">{{ pending.draft.name }} · 重试会使用首次点击时的原始内容和同一 ID，不会重复创建。<button :disabled="loading||preparing" @click="uploadPending">重试原存档上传</button><button :disabled="loading" @click="pending=null;message='已放弃重试；若服务器已收到，请刷新目录核查。'">放弃本次重试</button></p>
      <p v-if="directory">{{ directory.quota.used_items }} / {{ directory.quota.max_items }} 份 · {{ mib(directory.quota.used_bytes) }} / {{ mib(directory.quota.max_bytes) }} MiB（含回收站）</p>
      <p v-if="message" :role="failure?'alert':'status'" :class="{failure}">{{ message }}<span v-if="failure&&editing"> 你的编辑仍保留。可先复制文字，再取消编辑、刷新目录后核对最新版本。</span></p>
      <p v-if="loading" role="status">正在同步云存档…</p>
      <ul><li v-for="row in rows" :key="row.id">
        <div class="archive-label"><strong>{{ row.name }}</strong><small>{{ row.kind==='chart'?'图表快照':row.kind==='backtest'?'回测原档':row.kind==='portfolio'?'组合原档':row.kind==='factor'?'因子研究':row.kind==='tracking'?'追踪分析':'多周期研究' }} · {{ row.updated_at.replace('T',' ').slice(0,19) }} UTC · v{{ row.revision }}</small><p v-if="row.note">{{ row.note }}</p></div>
        <div class="archive-actions"><button :disabled="loading" @click="read(row)">查看原档</button><button :disabled="loading" @click="read(row,true)">导出</button><button v-if="!trash" :disabled="loading" @click="editing={id:row.id,revision:row.revision,name:row.name,note:row.note}">编辑备注</button><button :disabled="loading" @click="mutate(row,trash?'restore':'delete')">{{ trash?'恢复':'移入回收站' }}</button><button v-if="trash" :disabled="loading" @click="mutate(row,'purge')">{{ confirm===row.id?'确认永久删除':'永久删除' }}</button><button v-if="confirm===row.id" @click="confirm=''">取消</button></div>
        <form v-if="editing?.id===row.id" class="archive-editor" @submit.prevent="mutate({...row,revision:editing.revision},'edit')"><label>存档名称<input v-model="editing.name" maxlength="120" required /></label><label>存档备注<textarea v-model="editing.note" maxlength="4000" rows="3" /></label><div class="archive-actions"><button :disabled="loading">保存备注</button><button type="button" @click="editing=null">取消编辑</button></div></form>
      </li></ul>
      <p v-if="directory&&!rows.length&&!loading">{{ trash?'回收站为空。':'尚无云存档。' }}</p>
      </div>
    </div>
  </details>
  <Teleport to="body"><dialog ref="dialog" class="cloud-dialog" aria-label="云端研究原档" @cancel.prevent="close"><template v-if="viewing"><header><div><strong>{{ viewing.name }}</strong><p>保存于 {{ viewing.created_at }} · 原档 {{ viewing.digest.slice(0,12) }}</p></div><button @click="close">关闭云存档</button></header><div class="cloud-scroll"><p v-if="viewing.note">{{ viewing.note }}</p><CloudArchivePreview :key="viewing.id" :record="viewing" /></div></template></dialog></Teleport>
</template>
<style scoped>
.archive-controls>p{font-size:11px;line-height:1.9;color:var(--text-muted)}
.import-preview{margin:16px 0;padding:14px 0;border-block:1px solid var(--border);overflow-wrap:anywhere}.import-preview h4{font-size:12px;font-weight:600;margin:0 0 8px}.import-preview p{font-size:11px;line-height:1.8;color:var(--text-muted);margin:7px 0}.import-preview .archive-actions{margin-top:12px}
.cloud-archives{margin-block:18px}.archive-body{padding:14px 0 10px 20px;min-width:0}.archive-body>p{font-size:11px;line-height:1.9;color:var(--text-muted)}.archive-toolbar,.archive-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}button{padding:6px 10px;min-height:32px;font-size:11px;border:1px solid var(--border);border-radius:7px;color:var(--text-muted);background:var(--bg-elevated);cursor:pointer}button:disabled{opacity:.5;cursor:default}button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}button[aria-pressed=true]{color:var(--accent)}ul{padding:0;list-style:none}li{display:flex;flex-wrap:wrap;gap:12px 20px;padding:16px 0;border-top:1px solid var(--border)}.archive-label{flex:1;min-width:180px;overflow-wrap:anywhere}.archive-label strong{font-size:12px;font-weight:550}.archive-label small{display:block;margin-top:7px;font-size:10px;color:var(--text-muted)}.archive-label p{font-size:11px;white-space:pre-wrap;line-height:1.8;margin-bottom:0}.archive-editor{flex-basis:100%;display:grid;gap:12px}.archive-editor label{display:grid;gap:7px;font-size:11px;color:var(--text-muted)}input,textarea{width:100%;box-sizing:border-box;background:var(--bg-deep);border:1px solid var(--border);border-radius:6px;padding:8px;color:var(--text);font:inherit}.failure{color:#e9ab9f!important}.cloud-dialog{width:min(1160px,calc(100vw - 32px));height:min(900px,calc(100dvh - 40px));padding:0;border:1px solid var(--border);border-radius:14px;color:var(--text);background:var(--bg-panel,#1c1e23);max-width:none;max-height:none}.cloud-dialog::backdrop{background:#0009}.cloud-dialog>header{display:flex;align-items:start;justify-content:space-between;gap:16px;padding:18px 22px;border-bottom:1px solid var(--border)}.cloud-dialog header strong{font-size:14px}.cloud-dialog header p{font-size:10px;color:var(--text-muted)}.cloud-scroll{height:calc(100% - 92px);overflow:auto;padding:16px 22px;box-sizing:border-box;overflow-wrap:anywhere}@media(max-width:600px){.archive-body{padding-left:0}.archive-label{flex-basis:100%}.archive-actions{width:100%}.cloud-dialog{width:calc(100vw - 16px);height:calc(100dvh - 20px)}.cloud-dialog>header,.cloud-scroll{padding:12px}.cloud-dialog>header strong{overflow-wrap:anywhere}.cloud-dialog>header>div{min-width:0}.cloud-dialog>header>button{flex-shrink:0}}
</style>
<style scoped>
.cloud-archives>summary{display:flex;align-items:center;gap:10px;flex-wrap:wrap;cursor:pointer;min-height:40px;list-style:none}.cloud-archives>summary::-webkit-details-marker{display:none}.cloud-archives>summary::before{content:'›';width:12px;flex:0 0 12px;text-align:center;color:var(--text-muted);transition:transform .15s ease}.cloud-archives[open]>summary::before{transform:rotate(90deg)}.cloud-archives>summary strong{font-size:13px;font-weight:600}.cloud-archives>summary span{font-size:11px;color:var(--text-muted)}.cloud-archives>summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:4px}@media(prefers-reduced-motion:reduce){.cloud-archives>summary::before{transition:none}}
.cloud-dialog{margin:auto}.cloud-dialog[open]{display:flex;flex-direction:column}.cloud-dialog>header{flex-shrink:0}.cloud-scroll{height:auto;flex:1;min-height:0}
</style>
