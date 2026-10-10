import type {MarketDataMetadata} from './market-data-contract'
import type {FactorValidationResult} from './factor-validation'
import type {HorizonComparison} from './factor-horizons'
import type {FactorComposition} from './factor-composition'

export interface FactorEvaluation {composition?:FactorComposition|null}

export function factorSearchKey(value:string):string {
  return value.toLowerCase().replace(/[\s_-]+/g,'')
}

export function factorAliasVisible(factor:Record<string,unknown>,query:string,selected:readonly string[]=[]):boolean {
  return !factor.alias_of||selected.includes(String(factor.name))||factorSearchKey(query)===factorSearchKey(String(factor.name))
}

export interface FactorDay {date:string;n:number;factor_n?:number;label_end?:string|null;fold?:number;ic:number|null;rank_ic:number|null;rolling_rank_ic:number|null;layers:Array<number|null>;layer_spread?:number|null;reason:string|null}
export interface FactorReport {name:string;coverage:number;observations:number;ic_mean:number|null;rank_ic_mean:number|null;rank_ic_ir:number|null;positive_rate:number|null;layer_means:Array<number|null>;spread:number|null;layer_dates:number;diagnostics:Record<string,number>;daily:FactorDay[]}
export interface FactorEvaluation {version:string;statistics_version?:string;numeric_policy?:Record<string,unknown>;validation?:FactorValidationResult|null;horizon_comparison?:HorizonComparison|null;settings:{factors:string[];horizon:number;horizons?:number[]|null;groups:number;preprocess:string};factor_definitions?:Record<string,Record<string,unknown>>;reports:FactorReport[];errors:Record<string,string>;latest:Array<Record<string,string|number|null>>;redundancy:Array<{left:string;right:string;correlation:number|null;dates:number}>;input_fingerprint:string;start:string;end:string;date_count:number;assets:number;missing_bars:number;trade_eligible:false;limitations:string[];adjust:string;provenance:Array<{code:string;count:number;metadata:MarketDataMetadata}>}

export function factorStatisticsLabel(result:{statistics_version?:unknown}):string {
  return typeof result.statistics_version==='string'&&result.statistics_version
    ? result.statistics_version : '旧版原档未记录 · 不自动套用当前规则'
}

export function factorValue(value:unknown,percent=false,precision:'auto'|'raw'='auto'):string {
  if(typeof value!=='number'||!Number.isFinite(value))return '—'
  const scaled=value*(percent?100:1)
  const rendered=precision==='raw'?String(scaled):scaled!==0&&Math.abs(scaled)<0.005?scaled.toExponential(2):scaled.toFixed(2)
  return `${rendered}${percent?'%':''}`
}

export function sortedFactorRows(rows:FactorEvaluation['latest'],name:string,direction:1|-1) {
  return [...rows].sort((a,b)=>{
    const av=a[name],bv=b[name]
    const va=typeof av==='number'&&Number.isFinite(av),vb=typeof bv==='number'&&Number.isFinite(bv)
    if(!va)return vb?1:String(a.code).localeCompare(String(b.code))
    if(!vb)return -1
    return direction*(av-bv)||String(a.code).localeCompare(String(b.code))
  })
}
