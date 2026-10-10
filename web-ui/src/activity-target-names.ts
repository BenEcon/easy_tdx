import {fetchStockNames, fetchBoardList} from './api.ts'
import {indexTargets} from './chanlun-target.ts'
import type {ActivityTarget} from './activity.ts'
import {queryAction} from './query-origin.ts'

/** Display-only enrichment. Never borrow the administrator's own stock history,
 * guess an absent market, or set manual query intent for these helper requests. */
export async function activityTargetNames(targets:ActivityTarget[], signal:AbortSignal):Promise<Record<string,string>> {
  const names:Record<string,string>={}
  const unique=[...new Map(targets.map(t=>[t.key,t])).values()].slice(0,200)
  for(const index of indexTargets) {
    if(unique.some(t=>t.key===index.value)) names[index.value]=index.label.slice(index.label.indexOf('-')+1)
  }
  for(const market of ['SH','SZ','BJ']) {
    const missing=unique.filter(t=>t.market===market&&!names[t.key]&&/^\d{6}$/.test(t.code))
    // Bound fallback fan-out; no market/code collision even for SH/SZ:000001.
    for(let start=0;start<missing.length&&!signal.aborted;start+=20) {
      const batch=missing.slice(start,start+20)
      try {
        const result=await queryAction(false)(()=>fetchStockNames(batch,signal))
        if(signal.aborted)return {}
        for(const target of batch)if(result[target.code])names[target.key]=result[target.code]!
      } catch { if(signal.aborted)return {} }
    }
  }
  if(!signal.aborted&&unique.some(t=>t.market==='BOARD')) {
    try {
      const response=await queryAction(false)(()=>fetchBoardList({boardType:'ALL',count:5000},signal))
      if(signal.aborted)return {}
      for(const row of response.data) {
        const key=`BOARD:${String(row.board_code??row.code??row.symbol??'')}`
        const name=String(row.board_name??row.name??'').trim()
        if(name&&unique.some(t=>t.key===key))names[key]=name
      }
    } catch { /* Keep code and a visible unresolved-name label; queries remain usable. */ }
  }
  return names
}
