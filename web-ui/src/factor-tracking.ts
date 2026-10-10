import {archiveClient,ArchiveRequestError,type ArchiveDraft,type ArchiveRecord} from './cloud-archives.ts'
import type {FactorEvaluation} from './factor-research'
import {readTrackingBook,type TrackingGroup} from './tracking.ts'

export interface FactorTrackingSource {
  format:'factor-tracking-source-v1';archive_id:string;archive_digest:string;archive_revision:number
  title:string;score_key:string;score_label:string;date:string;input_fingerprint:string
  selection:Array<{symbol:string;score:number}>;provenance:'client_archive_not_server_verified'
  names:'user_display_labels_not_historical_security_master'
}
export const trackingEquity=(symbol:string)=>/^(SH:6\d{5}|SZ:(00|30)\d{4}|BJ:(43|83|87|92)\d{4})$/.test(symbol)
export function trackingScoreOptions(result:FactorEvaluation){
  return [...(result.composition&&!result.composition.error?[{value:'composite_score',label:'固定权重组合评分'}]:[]),
    ...result.settings.factors.filter(k=>!result.errors[k]).map(value=>({value,label:String(result.factor_definitions?.[value]?.display_name??value)}))]
}
export function trackingScoreRows(result:FactorEvaluation,key:string){
  if(!trackingScoreOptions(result).some(o=>o.value===key))return []
  const rows=key==='composite_score'?result.composition!.latest.map(r=>({code:r.code,value:r.score})):result.latest.map(r=>({code:String(r.code),value:r[key]}))
  return rows.map(r=>({...r,value:typeof r.value==='number'&&Number.isFinite(r.value)?r.value:null,eligible:trackingEquity(r.code)&&typeof r.value==='number'&&Number.isFinite(r.value)}))
    .sort((a,b)=>(a.value===null?1:b.value===null?-1:b.value-a.value)||a.code.localeCompare(b.code))
}
export interface FactorTrackingChoice {name:string;score_key:string;symbols:string[];labels:Record<string,string>}
/** Only explicit calls write. The frozen upload ID is retained by the caller across retries. */
export function factorTrackingClient(owner:()=>string|undefined,transport:typeof fetch=fetch){
  const archives=archiveClient(owner,transport)
  return {
    save:(id:string,draft:ArchiveDraft,signal:AbortSignal)=>archives<ArchiveRecord>(`/${id}`,{method:'PUT',body:JSON.stringify(draft),signal}),
    async create(record:ArchiveRecord,choice:FactorTrackingChoice,signal:AbortSignal):Promise<{group:TrackingGroup;created:boolean}>{
      const identity=owner();if(!identity)throw Error('请先登录')
      if(record.kind!=='factor'||record.state!=='active')throw Error('请使用未删除的因子研究原档')
      const response=await transport(`/api/v1/research/archives/${encodeURIComponent(record.id)}/tracking-group`,{method:'POST',credentials:'same-origin',cache:'no-store',signal,headers:{'Content-Type':'application/json','X-Research-Owner':identity},body:JSON.stringify({...choice,digest:record.digest,revision:record.revision})})
      const value=await response.json().catch(()=>null)
      if(owner()!==identity)throw new ArchiveRequestError(409,'账户已切换，未采用旧账户结果')
      if(!response.ok)throw new ArchiveRequestError(response.status,typeof value?.detail==='string'?value.detail:`建立追踪分组失败（${response.status}）`)
      if(typeof value?.created!=='boolean')throw Error('追踪分组响应不完整，请到追踪页面核实；未自动重试')
      const book=readTrackingBook({version:1,revision:'',groups:[value.group]})
      const source=book.groups[0]?.research_source
      if(source?.archive_id!==record.id||source.archive_digest!==record.digest||source.score_key!==choice.score_key)throw Error('追踪分组来源不一致，请核实')
      return {group:book.groups[0]!,created:value.created}
    },
  }
}
