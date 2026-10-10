import type {FactorReport} from './factor-research'
import type {HorizonComparison} from './factor-horizons'
import {assertHorizonComparison} from './factor-horizons.ts'
import type {FactorValidationResult} from './factor-validation'

export interface CompositionComponent {name:string;weight:number;direction:1|-1}
export interface CompositionConfig {method:'rank_centered';components:CompositionComponent[]}
export interface CompositionDraft {enabled:boolean;components:Record<string,{weight:number;direction:number}>}
export interface FactorComposition {
  version:'factor-composition-rank-v1';config:CompositionConfig;score_name:'composite_score'
  effective_components:Array<CompositionComponent&{normalized_weight:number}>
  symbols:string[];scores:Array<{date:string;values:Array<number|null>}>
  coverage:Array<{date:string;complete_assets:number;scored_assets:number;constant_components:string[];reason:string|null}>
  latest:Array<{code:string;score:number|null;reason:string|null;components:Array<{name:string;raw:number|null;rank:number|null;contribution:number|null}>}>
  reports:FactorReport[];validation:FactorValidationResult|null;horizon_comparison:HorizonComparison
  trade_eligible:false;error:string|null;limitations:string[];policy:Record<string,unknown>
}
export const compositionDefaults=():CompositionDraft=>({enabled:false,components:{}})
export function compositionConfig(draft:CompositionDraft,names:string[]):CompositionConfig|null {
  if(!draft.enabled)return null
  if(names.length<2||names.length>4||new Set(names).size!==names.length)throw Error('组合需要选择 2—4 个不同因子')
  return {method:'rank_centered',components:names.map(name=>{
    const c=draft.components[name]??{weight:1,direction:1}
    if(!Number.isFinite(c.weight)||c.weight<.01||c.weight>100)throw Error('组合权重须为 0.01—100 的有限数值')
    if(c.direction!==1&&c.direction!==-1)throw Error('组合方向须明确选择正向或反向')
    return {name,weight:c.weight,direction:c.direction}
  })}
}

/** Shape/consistency only. Never calculate ranks, fit weights or refresh an archive. */
export function assertComposition(result:Record<string,unknown>,settings:Record<string,unknown>,symbols:string[]):void {
  const obj=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
  const num=(v:unknown)=>v===null||typeof v==='number'&&Number.isFinite(v)
  const eq=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b)
  function require(ok:unknown):asserts ok{if(!ok)throw Error('组合原档不完整或不一致')}
  const config=settings.composition,c=result.composition
  if(config==null){require(c==null);return}
  require(obj(config)&&config.method==='rank_centered'&&Object.keys(config).length===2&&Array.isArray(config.components)&&Array.isArray(settings.factors)&&config.components.length===settings.factors.length&&config.components.length>=2&&config.components.length<=4)
  const components=config.components
  let total=0
  for(const [i,item] of components.entries()){
    require(obj(item)&&Object.keys(item).length===3&&item.name===settings.factors[i]&&typeof item.weight==='number'&&Number.isFinite(item.weight)&&item.weight>=.01&&item.weight<=100&&(item.direction===1||item.direction===-1))
    total+=item.weight
  }
  require(obj(c)&&c.version==='factor-composition-rank-v1'&&eq(c.config,config)&&c.score_name==='composite_score'&&c.trade_eligible===false&&eq(c.symbols,symbols)&&Array.isArray(c.effective_components)&&c.effective_components.length===components.length)
  for(const [i,item] of c.effective_components.entries()){
    const input=components[i]!
    require(obj(item)&&Object.keys(item).length===4&&item.name===input.name&&item.weight===input.weight&&item.direction===input.direction&&typeof item.normalized_weight==='number'&&Math.abs(item.normalized_weight-Number(input.weight)/total)<1e-12)
  }
  require(obj(c.policy)&&c.policy.pool==='same_date_complete_intersection'&&c.policy.minimum_assets===5&&c.policy.missing==='no_imputation_no_weight_renormalization'&&c.policy.fit==='fixed_user_weights_no_return_fitting'&&Array.isArray(c.limitations)&&c.limitations.length>0&&(c.error===null||typeof c.error==='string'&&!!c.error))
  require(Array.isArray(c.scores)&&c.scores.length===result.date_count&&c.scores.length>0&&c.scores.length<=800&&Array.isArray(c.coverage)&&c.coverage.length===c.scores.length)
  for(const [i,row] of c.scores.entries()){
    require(obj(row)&&typeof row.date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(row.date)&&(!i||String(c.scores[i-1].date)<row.date)&&Array.isArray(row.values)&&row.values.length===symbols.length&&row.values.every(v=>num(v)&&(v===null||Math.abs(Number(v))<=1+1e-12)))
    const cv=c.coverage[i],n=row.values.filter(v=>v!==null).length
    require(obj(cv)&&cv.date===row.date&&Number.isInteger(cv.complete_assets)&&Number(cv.complete_assets)>=0&&Number(cv.complete_assets)<=symbols.length&&cv.scored_assets===n&&(n===0||n>=5)&&n===(Number(cv.complete_assets)>=5&&c.error===null?cv.complete_assets:0)&&Array.isArray(cv.constant_components)&&cv.constant_components.every(v=>(settings.factors as unknown[]).includes(v)))
  }
  require(c.scores[0].date===result.start&&c.scores.at(-1).date===result.end&&Array.isArray(c.latest)&&c.latest.length===symbols.length)
  for(const [i,row] of c.latest.entries()){
    require(obj(row)&&row.code===symbols[i]&&row.score===c.scores.at(-1).values[i]&&Array.isArray(row.components)&&row.components.length===components.length)
    let sum=0
    for(const [j,item] of row.components.entries()){
      const w=c.effective_components[j]
      require(obj(item)&&item.name===components[j].name&&['raw','rank','contribution'].every(k=>num(item[k])))
      if(row.score===null)require(item.rank===null&&item.contribution===null)
      else{require(item.raw!==null&&typeof item.rank==='number'&&Math.abs(item.rank)<=1+1e-12&&typeof item.contribution==='number'&&Math.abs(item.contribution-item.rank*Number(w.direction)*Number(w.normalized_weight))<1e-12);sum+=item.contribution}
    }
    if(row.score!==null)require(Math.abs(Number(row.score)-sum)<1e-12)
  }
  require(Array.isArray(c.reports)&&c.reports.length===1&&c.reports[0].name==='composite_score')
  assertHorizonComparison({...result,reports:c.reports,validation:c.validation,horizon_comparison:c.horizon_comparison},
    {...settings,horizons:settings.horizons??[settings.horizon]},['composite_score'])
}
