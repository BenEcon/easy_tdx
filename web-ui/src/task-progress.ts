export interface TaskProgress {phase:string;completed:number;total:number;detail:string;sequence:number}
const phases:Record<string,string>={factor_series:'时间序列 · 因子',factor_values:'因子值 · 标的',factor_windows:'截面检验 · 远期窗口',factor_composition:'组合评分 · 观测日',redundancy:'冗余检查 · 因子对',time_validation:'时间划分 · 远期窗口',archive:'冻结存档 · 标的',result_validation:'完整结果校验'}
export function validateTaskProgress(value:unknown):TaskProgress|null {
  if(value==null)return null
  if(typeof value!=='object'||Array.isArray(value))throw Error('任务进度格式异常')
  const p=value as TaskProgress
  if(Object.keys(p).sort().join(',')!=='completed,detail,phase,sequence,total'||typeof p.phase!=='string'||!Object.hasOwn(phases,p.phase)
    ||![p.completed,p.total,p.sequence].every(Number.isSafeInteger)||p.completed<0||p.completed>p.total||p.total<1||p.total>1e6||p.sequence<1||p.sequence>1e6||typeof p.detail!=='string'||[...p.detail].length>96)throw Error('任务进度范围异常')
  return p
}
export function taskProgressLabel(value:unknown):string {
  try{const p=validateTaskProgress(value);return p?`${phases[p.phase]} ${p.completed}/${p.total}${p.detail?` · ${p.detail}`:''}`:''}
  catch{return '进度暂不可读，请以任务状态为准'}
}
