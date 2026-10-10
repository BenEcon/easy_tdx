import { savedStrategyInput, type SavedInputDefaults } from './saved-strategy-input.ts'
import type { SavedStrategy, OptimizeAllBacktestRequest, MultiStrategyBacktestRequest } from './types'

export const executionDefaults = {cash:1000000,commission:.0003,min_commission:5,stamp_tax:.001,slippage:0,execution:'next_open'} as const
const defaults:SavedInputDefaults={category:'DAY',adjust:'QFQ',startDate:'2020-01-06',endDate:'2020-01-06',cash:executionDefaults.cash,commission:executionDefaults.commission,minCommission:executionDefaults.min_commission,stampTax:executionDefaults.stamp_tax,slippage:executionDefaults.slippage,execution:executionDefaults.execution}
const object=(value:unknown):value is Record<string,unknown>=>Boolean(value)&&typeof value==='object'&&!Array.isArray(value)
function record(value:unknown):SavedStrategy {if(!object(value))throw Error('执行上下文格式无效');return value as unknown as SavedStrategy}

export function optimizationQuery(request:OptimizeAllBacktestRequest,strategy:string,params:Record<string,number|string>) {
  return {optimizationContext:JSON.stringify({version:1,strategy,params,
    context:{symbol:request.symbol,category:request.category,adjust:request.adjust,start_date:request.start_date,end_date:request.end_date},
    trade_config:{...executionDefaults,...Object.fromEntries(['cash','commission','min_commission','stamp_tax','slippage','execution'].filter(k=>request[k as keyof typeof request]!==undefined).map(k=>[k,request[k as keyof typeof request]]))}})}
}
export function readOptimizationQuery(query:Record<string,unknown>,strategies:readonly string[]) {
  if(Object.keys(query).length!==1||typeof query.optimizationContext!=='string'||query.optimizationContext.length>12000)throw Error('寻优载入链接无效或混用了其他参数')
  let raw:SavedStrategy&{version?:unknown}
  try{raw=record(JSON.parse(query.optimizationContext))}catch{throw Error('寻优执行上下文无法解析')}
  if(raw.version!==1)throw Error('寻优执行上下文版本不支持')
  const input=savedStrategyInput({...raw,kind:'single'},defaults,strategies)
  if(input.warnings.length)throw Error('寻优执行上下文不完整，请从完整结果重新打开')
  return input
}

/** Preserve common execution settings and each independent strategy slot. Never repair explicit markets. */
export function savedMultiInput(source:SavedStrategy,strategies:readonly string[],today:string,extend=false) {
  if(!object(source.context)||!object(source.trade_config))throw Error('多策略记录的上下文或交易配置格式无效')
  if(source.kind!=='multi'||!Array.isArray(source.context?.items)||!source.context.items.length||source.context.items.length>20)throw Error('多策略记录必须包含 1 至 20 个完整槽位')
  const ctx=source.context,trade={...source.trade_config},warnings:string[]=[]
  if(trade.cash!==undefined&&ctx.cash!==undefined&&trade.cash!==ctx.cash)throw Error('记录的两处组合资金不一致，请核对原配置')
  if(trade.cash===undefined&&ctx.cash!==undefined)trade.cash=ctx.cash
  const inputs=(ctx.items as unknown[]).map((raw,index)=>{
    if(!object(raw))throw Error(`第 ${index+1} 个槽位无效`)
    if(raw.adjust!==undefined&&raw.adjust!==ctx.adjust)throw Error('槽位与组合复权不一致，不能静默统一')
    const parsed=savedStrategyInput({...source,kind:'single',strategy:raw.strategy as string,params:raw.params as SavedStrategy['params'],context:{...raw,adjust:ctx.adjust},trade_config:trade},{...defaults,endDate:today},strategies)
    if(extend&&parsed.startDate>today)throw Error('开始日期晚于今天，不能重跑到今天')
    warnings.push(...parsed.warnings)
    return {...parsed,label:typeof raw.strategy_label==='string'?raw.strategy_label:parsed.strategy}
  })
  const first=inputs[0]!
  const request:MultiStrategyBacktestRequest={cash:first.cash,commission:first.commission,min_commission:first.minCommission,stamp_tax:first.stampTax,slippage:first.slippage,execution:first.execution,adjust:first.adjust,
    items:inputs.map(v=>({strategy:v.strategy,strategy_label:v.label,params:v.params,symbol:`${v.market}:${v.code}`,category:v.category,start_date:v.startDate,end_date:extend?today:v.endDate}))}
  return{request,warnings:[...new Set(warnings)].map(w=>w.replace('本页设置','明确默认值'))}
}

export function combineSavedSingles(sources:SavedStrategy[],strategies:readonly string[],today:string) {
  if(!sources.length||sources.length>20)throw Error('请选择 1 至 20 个单标的策略')
  const inputs=sources.map(s=>savedStrategyInput(s,{...defaults,endDate:today},strategies)),first=inputs[0]!
  for(const item of inputs)for(const key of ['cash','commission','minCommission','stampTax','slippage','execution','adjust'] as const){
    if(item[key]!==first[key])throw Error('所选策略的资金、成本、成交方式或复权不一致；等额分仓不能原样还原，请先统一保存配置或分别回测')
  }
  const total=first.cash*inputs.length
  if(!Number.isFinite(total))throw Error('组合资金超出有效范围')
  return {request:{cash:total,commission:first.commission,min_commission:first.minCommission,stamp_tax:first.stampTax,slippage:first.slippage,execution:first.execution,adjust:first.adjust,
    items:inputs.map((v,i)=>({strategy:v.strategy,strategy_label:sources[i]!.strategy_label||v.strategy,params:v.params,symbol:`${v.market}:${v.code}`,category:v.category,start_date:v.startDate,end_date:v.endDate}))} as MultiStrategyBacktestRequest,
    warnings:[...new Set(inputs.flatMap(v=>v.warnings))].map(w=>w.replace('本页设置','明确默认值'))}
}

export function multiExecutionSummary(request:MultiStrategyBacktestRequest,warnings:string[]) {
  const ranges=[...new Set(request.items.map(v=>`${v.start_date} 至 ${v.end_date}`))].join('；')
  return `${request.items.length} 个槽位，组合资金 ${request.cash}，每槽位等额分仓。\n区间：${ranges}。\n复权 ${request.adjust}；${request.execution==='next_close'?'次根收盘价':'次根开盘价'}；佣金率 ${request.commission}；最低佣金 ${request.min_commission}；印花税率 ${request.stamp_tax}；滑点 ${request.slippage}。\n${warnings.length?'旧记录缺项：'+warnings.join('；')+'。\n':''}使用当前可取得的行情重新计算，不是原版本成绩回放。回测信号不等同于实际持仓或交易建议。`
}
