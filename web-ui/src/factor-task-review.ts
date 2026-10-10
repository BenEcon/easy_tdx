import {factorArchiveDraft,factorRecomputedArchive,type FactorArchive} from './factor-archive.ts'
import type {TaskState} from './types'

/** Frozen result only. No catalog lookup, live data fetch or recalculation. */
export function factorTaskArchive(state:TaskState,expectedId:string):FactorArchive {
  if(state.task_id!==expectedId||state.status!=='done'||!['factor_evaluation','factor_series','factor_recompute'].includes(state.kind??''))throw Error('任务尚未完整完成或不是所选因子研究')
  if(state.kind==='factor_recompute')return factorRecomputedArchive(state.result)
  return factorArchiveDraft(state.kind==='factor_series'?'series':'evaluation',state.result).payload as unknown as FactorArchive
}
