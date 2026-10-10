import {ref,shallowRef} from 'vue'
import {archiveClient,type ArchiveRecord} from './cloud-archives.ts'
import {trackingArchiveDraft,type TrackingArchive} from './tracking-archive.ts'

/** One immutable upload identity per finished batch. Never switch account on retry. */
export function createTrackingAutoSave(owner:()=>string|undefined,transport:typeof fetch=fetch) {
  const pending=shallowRef<{id:string;owner:string;payload:TrackingArchive}|null>(null)
  const busy=ref(false),error=ref(''),saved=shallowRef<ArchiveRecord|null>(null)
  let generation=0,controller:AbortController|undefined
  const request=archiveClient(owner,transport)
  function clear(){generation++;controller?.abort();controller=undefined;pending.value=null;busy.value=false;error.value='';saved.value=null}
  async function retry(){
    const upload=pending.value
    if(!upload||busy.value)return
    if(upload.owner!==owner()){clear();return}
    const version=generation;controller=new AbortController();busy.value=true;error.value=''
    try{
      const draft=trackingArchiveDraft(upload.payload)
      const record=await request<ArchiveRecord>(`/${upload.id}`,{method:'PUT',body:JSON.stringify(draft),signal:controller.signal})
      if(version!==generation)return
      saved.value=record;pending.value=null
    }catch(e){if(version===generation)error.value=e instanceof Error?e.message:String(e)}
    finally{if(version===generation){busy.value=false;controller=undefined}}
  }
  async function save(payload:TrackingArchive){
    if(pending.value)throw Error('上一批记录尚未保存，请先重试或导出')
    const account=owner();if(!account)return
    clear()
    // Retain the original even when server quota/size validation fails.
    pending.value={id:crypto.randomUUID(),owner:account,payload}
    try{
      pending.value={...pending.value,payload:JSON.parse(JSON.stringify(payload,(_key,value)=>{
        if(typeof value==='number'&&!Number.isFinite(value))throw Error('原结果包含非有限数值，未将其替换为空值保存')
        return value
      }))}
    }catch(e){error.value=e instanceof Error?e.message:String(e);return}
    await retry()
  }
  return {pending,busy,error,saved,clear,retry,save}
}
