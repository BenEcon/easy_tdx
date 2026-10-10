import type {FactorEvaluation,FactorReport} from './factor-research'
import {assertValidationResult,type FactorValidationResult} from './factor-validation.ts'

export interface HorizonResult {horizon:number;reports:FactorReport[];validation:FactorValidationResult|null}
export interface HorizonComparison {version:'factor-multi-horizon-v1';horizons:number[];results:HorizonResult[];sample_policy:'each_horizon_own_complete_labels'}
export function selectedHorizons(values:number[]):number[] {
  if(!Array.isArray(values)||!values.length||values.length>4||new Set(values).size!==values.length||values.some(h=>!Number.isInteger(h)||![1,5,10,20].includes(h)))throw Error('请选择不重复的 1／5／10／20 个观测日窗口')
  return [...values].sort((a,b)=>a-b)
}
/** Selecting a saved result changes only the view, never request/configuration/data. */
export function horizonView(result:FactorEvaluation|null,horizon:number):FactorEvaluation|null {
  if(!result)return null
  const selected=result.horizon_comparison?.results.find(r=>r.horizon===horizon)
  return selected?{...result,reports:selected.reports,validation:selected.validation}:result
}
export function assertHorizonComparison(result:Record<string,unknown>,settings:Record<string,unknown>,names:string[]):void {
  const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
  const numeric=(v:unknown)=>v===null||typeof v==='number'&&Number.isFinite(v)
  function require(ok:unknown):asserts ok {if(!ok)throw Error('多远期原档不完整或不一致')}
  const selection=settings.horizons,value=result.horizon_comparison
  if(selection==null){require(value==null);return}
  require(Array.isArray(selection))
  const horizons=selectedHorizons(selection)
  require(horizons.includes(settings.horizon as number)&&JSON.stringify(horizons)===JSON.stringify(selection))
  require(object(value)&&value.version==='factor-multi-horizon-v1'&&value.sample_policy==='each_horizon_own_complete_labels'&&JSON.stringify(value.horizons)===JSON.stringify(horizons)&&Array.isArray(value.results)&&value.results.length===horizons.length)
  for(const [i,item] of value.results.entries()){
    require(object(item)&&item.horizon===horizons[i]&&Array.isArray(item.reports)&&item.reports.length===names.length)
    for(const [j,r] of item.reports.entries()){
      require(object(r)&&r.name===names[j]&&Array.isArray(r.daily)&&r.daily.length===result.date_count&&r.daily.length<=800&&Array.isArray(r.layer_means)&&r.layer_means.length===settings.groups&&r.layer_means.every(numeric)&&object(r.diagnostics)&&Number.isInteger(r.observations)&&Number.isInteger(r.layer_dates))
      require(['coverage','ic_mean','rank_ic_mean','rank_ic_ir','positive_rate','spread'].every(k=>numeric(r[k])))
      const days=r.daily
      for(const [pos,day] of days.entries()){
        require(object(day)&&typeof day.date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(day.date)&&(!pos||String(days[pos-1].date)<day.date)&&['ic','rank_ic','rolling_rank_ic','layer_spread'].every(k=>numeric(day[k]))&&Array.isArray(day.layers)&&day.layers.length===settings.groups&&day.layers.every(numeric))
        require(day.label_end===(days[pos+Number(item.horizon)]?.date??null))
      }
    }
    assertValidationResult(item.validation,settings.validation,names)
    if(item.horizon===settings.horizon)require(JSON.stringify(item.reports)===JSON.stringify(result.reports)&&JSON.stringify(item.validation??null)===JSON.stringify(result.validation??null))
  }
}
