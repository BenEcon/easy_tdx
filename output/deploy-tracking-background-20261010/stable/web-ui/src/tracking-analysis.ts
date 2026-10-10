import {fetchResearchSnapshot, formatError} from './api.ts'
import {assertMarketData} from './market-data-contract.ts'
import {researchTarget,trackingAdjustment,trackingKey,type TrackingTarget} from './tracking.ts'
import type {Study,StudyPeriod,StudyRow} from './research-study.ts'

/** Retains the existing observation algorithm, cutoff and strict market-data checks. */
export async function analyzeTrackingTarget(target:TrackingTarget,chosen:StudyPeriod[],asOf:string,signal:AbortSignal,owner:string,onAccessLost:()=>void):Promise<Study> {
  const series=[],failures:StudyRow[]=[],adjustment=trackingAdjustment(target)
  const accessError=(e:unknown)=>{
    signal.throwIfAborted()
    if(e&&typeof e==='object'&&'status' in e&&[401,403,409].includes(Number(e.status)))onAccessLost()
    signal.throwIfAborted()
  }
  for(const category of chosen) {
    signal.throwIfAborted()
    try {
      const snapshot=await fetchResearchSnapshot(researchTarget(target),category,800,adjustment,signal,owner)
      signal.throwIfAborted()
      assertMarketData(snapshot.metadata,adjustment)
      if(snapshot.metadata.category!==category)throw Error('返回周期与请求不一致')
      if(!snapshot.bars.length)throw Error('暂无行情')
      series.push({category,code:trackingKey(target),bars:snapshot.bars,bar_time:snapshot.metadata.bar_time??'start'})
    } catch(e){accessError(e);failures.push({category,error:formatError(e)} as StudyRow)}
  }
  signal.throwIfAborted()
  let study:Study={as_of:asOf,rows:[],conflicts:[],policy:'',rule_version:'',parameters:{}}
  if(series.length) {
    const response=await fetch('/api/v1/chanlun/observations',{
      method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Query-Origin':'user','X-Tracking-Owner':owner},signal,
      body:JSON.stringify({as_of:asOf,series,window_bars:20,ma_periods:[5,10,20,30,60,120,250]})})
    signal.throwIfAborted()
    if([401,403,409].includes(response.status)){onAccessLost();signal.throwIfAborted()}
    const body=await response.json()
    if(!response.ok)throw Error(typeof body.detail==='string'?body.detail:`分析请求失败（${response.status}）`)
    study=body as Study
    if(!Array.isArray(study.rows))throw Error('研究接口返回格式不正确')
    for(const source of series)if(!study.rows.some(row=>row.category===source.category))failures.push({category:source.category,error:'未返回此周期的分析结果'} as StudyRow)
  }
  study.rows.push(...failures)
  return study
}
