import type {FactorReport} from './factor-research'

export type FactorValidationConfig={mode:'holdout';train_end:string;validation_end:string}|{mode:'walk_forward';training:'expanding'|'rolling';train_bars:number;validation_bars:number;test_bars:number}
export interface ValidationDraft {mode:'full'|'holdout'|'walk_forward';trainEnd:string;validationEnd:string;training:'expanding'|'rolling';trainBars:number;validationBars:number;testBars:number}
export const validationDefaults=():ValidationDraft=>({mode:'full',trainEnd:'',validationEnd:'',training:'expanding',trainBars:120,validationBars:40,testBars:40})
export interface FactorValidationResult {
  version:'factor-time-validation-v1';config:FactorValidationConfig
  folds:Array<{id:number;phases:Array<{phase:'train'|'validation'|'test';start:string;end:string;date_count:number;purged_dates:number;label_eligible_dates:number;partial:boolean;reports:Array<Omit<FactorReport,'daily'>>}>}>
  test_reports:FactorReport[];policy:Record<string,string>;limitations:string[]
}
function validDate(value:string):boolean {
  if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return false
  const date=new Date(`${value}T00:00:00Z`)
  return Number.isFinite(date.getTime())&&date.toISOString().slice(0,10)===value
}
export function validationConfig(draft:ValidationDraft,horizon:number,count:number):FactorValidationConfig|null {
  if(draft.mode==='full')return null
  if(draft.mode==='holdout'){
    if(!validDate(draft.trainEnd)||!validDate(draft.validationEnd)||draft.trainEnd>=draft.validationEnd)throw Error('请填写有效且递增的训练、验证截止日期')
    return {mode:'holdout',train_end:draft.trainEnd,validation_end:draft.validationEnd}
  }
  if(draft.mode!=='walk_forward'||!['expanding','rolling'].includes(draft.training))throw Error('时间划分模式无效')
  for(const [label,n,min,max] of [['训练',draft.trainBars,20,700],['验证',draft.validationBars,10,300],['测试',draft.testBars,10,300]] as const){
    if(!Number.isInteger(n)||n<min||n>max||n<=horizon)throw Error(`${label}区间须为 ${min}—${max} 根整数且长于远期窗口`)
  }
  if(draft.trainBars+draft.validationBars+draft.testBars>count)throw Error('所选历史长度不足一个完整滚动窗口，请增加历史长度或调整区间')
  return {mode:'walk_forward',training:draft.training,train_bars:draft.trainBars,validation_bars:draft.validationBars,test_bars:draft.testBars}
}

/** Structural check only; never apply today's computations to a saved report. */
export function assertValidationResult(value:unknown,config:unknown,names:string[]):void {
  const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
  function require(ok:unknown):asserts ok {if(!ok)throw Error('时间划分原档不完整或不一致')}
  const numeric=(v:unknown)=>v===null||typeof v==='number'&&Number.isFinite(v)
  if(config===null||config===undefined){require(value===null||value===undefined);return}
  require(object(value)&&object(config)&&value.version==='factor-time-validation-v1'&&object(value.config))
  require(Object.keys(config).length===Object.keys(value.config).length&&Object.entries(config).every(([k,v])=>(value.config as Record<string,unknown>)[k]===v))
  require(Array.isArray(value.folds)&&value.folds.length>=1&&value.folds.length<=80&&Array.isArray(value.test_reports)&&Array.isArray(value.limitations)&&object(value.policy))
  function summaries(rows:unknown){
    require(Array.isArray(rows)&&rows.length===names.length)
    for(const [i,row] of rows.entries())require(object(row)&&row.name===names[i]&&['coverage','ic_mean','rank_ic_mean','rank_ic_ir','positive_rate','spread'].every(k=>numeric(row[k]))&&Number.isInteger(row.observations)&&Array.isArray(row.layer_means)&&row.layer_means.every(numeric)&&object(row.diagnostics))
  }
  for(const [i,fold] of value.folds.entries()){
    require(object(fold)&&fold.id===i+1&&Array.isArray(fold.phases)&&fold.phases.length===3)
    for(const [j,phase] of fold.phases.entries()){
      require(object(phase)&&phase.phase===['train','validation','test'][j]&&typeof phase.start==='string'&&validDate(phase.start)&&typeof phase.end==='string'&&validDate(phase.end)&&phase.start<=phase.end&&Number.isInteger(phase.date_count)&&Number(phase.date_count)>0&&Number.isInteger(phase.purged_dates)&&Number.isInteger(phase.label_eligible_dates)&&typeof phase.partial==='boolean')
      summaries(phase.reports)
    }
  }
  summaries(value.test_reports)
  for(const r of value.test_reports){
    require(object(r)&&Array.isArray(r.daily)&&r.daily.length<=800)
    for(const day of r.daily)require(object(day)&&typeof day.date==='string'&&validDate(day.date)&&Number.isInteger(day.fold)&&['ic','rank_ic','rolling_rank_ic','layer_spread'].every(k=>numeric(day[k]))&&Array.isArray(day.layers)&&day.layers.every(numeric))
  }
}
