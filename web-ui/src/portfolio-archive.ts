import { archiveObject as object, archiveNumber as number, archiveTime } from './archive-data-validation.ts'
import { detachBacktest, validateBacktestArchive } from './backtest-archive.ts'
import type { BacktestResult, Bar, PortfolioResult, PortfolioBacktestRequest, MultiStrategyBacktestRequest, Category } from './types'
import type { MarketDataMetadata } from './market-data-contract'

export type PortfolioRequest = PortfolioBacktestRequest | MultiStrategyBacktestRequest
export interface PortfolioReceipt {
  contract:'portfolio-evidence-v1'; kind:'portfolio'|'multi_strategy'; task_id:string
  execution_version:string; current_execution_version:string; storage:'memory'|'persistent'
  request:PortfolioRequest; result:PortfolioResult
  members:Array<{index:number;key:string;symbol:string;category:Category;bars:Bar[];metadata:MarketDataMetadata}>
}
export interface PortfolioArchive {format:'portfolio-research-v1';title:string;savedAt:string;receipt:PortfolioReceipt}
/** Object key order is not evidence; array order and every saved numeric value are. */
export function samePortfolioValue(a:unknown,b:unknown):boolean {
  if(a===b)return true
  if(Array.isArray(a)&&Array.isArray(b))return a.length===b.length&&a.every((v,i)=>samePortfolioValue(v,b[i]))
  if(object(a)&&object(b))return Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>Object.hasOwn(b,k)&&samePortfolioValue(a[k],b[k]))
  return false
}
/** Server defaults may add fields, but may never replace submitted values. */
export function portfolioRequestMatches(sent:unknown,saved:unknown):boolean {
  if(Array.isArray(sent))return Array.isArray(saved)&&sent.length===saved.length&&sent.every((v,i)=>portfolioRequestMatches(v,saved[i]))
  if(object(sent))return object(saved)&&Object.keys(sent).every(k=>Object.hasOwn(saved,k)&&portfolioRequestMatches(sent[k],saved[k]))
  return samePortfolioValue(sent,saved)
}
function requireValue(condition:unknown):asserts condition {if(!condition)throw Error('组合原档的成员、参数、来源或完整结果不一致')}
const metrics=['total_return','annual_return','max_drawdown','max_dd_duration','sharpe','sortino','calmar','total_trades','win_trades','lose_trades','rejected_trades','win_rate','profit_factor','avg_win','avg_loss','max_win','max_loss','avg_holding_days','volatility']
export function validatePortfolioArchive(value:unknown):PortfolioArchive {
  requireValue(object(value)&&value.format==='portfolio-research-v1'&&typeof value.title==='string'&&value.title.trim()&&value.title.length<=500&&archiveTime(value.savedAt,true)!==null)
  const r=value.receipt
  requireValue(object(r)&&r.contract==='portfolio-evidence-v1'&&['portfolio','multi_strategy'].includes(String(r.kind))&&typeof r.kind==='string')
  for(const k of ['task_id','execution_version','current_execution_version'])requireValue(typeof r[k]==='string'&&r[k])
  requireValue(r.storage==='memory'||r.storage==='persistent')
  const request=r.request,result=r.result,members=r.members
  requireValue(object(request)&&object(result)&&Array.isArray(members)&&members.length>0&&members.length<=20&&number(request.cash)&&request.cash>0)
  const evidence=result.data_provenance
  requireValue(object(evidence)&&samePortfolioValue(evidence.request,request)&&Array.isArray(evidence.datasets)&&evidence.datasets.length===members.length)
  const datasets=evidence.datasets,cash=request.cash
  const slots=r.kind==='portfolio'?request.stocks:request.items,individuals=result.individual_results,allocations=result.equity_allocation
  requireValue(Array.isArray(slots)&&slots.length===members.length&&object(individuals)&&object(allocations))
  const keys=new Set<string>()
  members.forEach((m,i)=>{
    requireValue(object(m)&&m.index===i&&typeof m.key==='string'&&m.key&&!keys.has(m.key)&&typeof m.symbol==='string'&&Array.isArray(m.bars)&&m.bars.length)
    const item=r.kind==='portfolio'?request:slots[i]
    requireValue(object(item)&&m.symbol===(r.kind==='portfolio'?slots[i]:item.symbol)&&m.category===item.category)
    for(const k of ['start_date','end_date'])if(item[k]!=null)requireValue(archiveTime(item[k])!==null)
    requireValue(r.kind==='portfolio'?m.key===m.symbol.replace(':',''):m.key.endsWith('@'+m.symbol))
    if(r.kind==='multi_strategy'&&item.strategy_label)requireValue(m.key===item.strategy_label+'@'+m.symbol)
    const dataset=datasets[i]
    requireValue(object(dataset)&&dataset.label===m.key&&dataset.symbol===m.symbol&&dataset.bar_count===m.bars.length&&samePortfolioValue(dataset.metadata,m.metadata))
    const allocation=allocations[m.key]
    requireValue(number(allocation)&&allocation>0)
    const first=m.bars[0],last=m.bars.at(-1)
    requireValue(object(first)&&object(last)&&typeof first.datetime==='string'&&typeof last.datetime==='string')
    validateBacktestArchive({format:'backtest-research-v1',title:m.key,savedAt:value.savedAt,metadata:m.metadata,result:individuals[m.key],request:{...request,...item,symbol:m.symbol,category:m.category,cash:cash*allocation,ohlcv:m.bars,start_date:item.start_date??first.datetime.slice(0,10),end_date:item.end_date??last.datetime.slice(0,10)}})
    keys.add(m.key)
  })
  requireValue(Object.keys(individuals).length===keys.size&&Object.keys(allocations).length===keys.size&&Object.keys(individuals).every(k=>keys.has(k))&&Object.keys(allocations).every(k=>keys.has(k)))
  requireValue(Math.abs(Object.values(allocations).reduce<number>((a,b)=>a+Number(b),0)-1)<1e-12)
  const perf=result.total_performance
  requireValue(object(perf)&&metrics.every(k=>Object.hasOwn(perf,k)&&(perf[k]===null||number(perf[k])))&&perf.total_stocks===members.length&&perf.total_cash===request.cash)
  requireValue(Array.isArray(result.combined_equity)&&result.combined_equity.length)
  let prior=-Infinity
  for(const row of result.combined_equity){
    requireValue(object(row));const stamp=archiveTime(row.datetime,true)
    requireValue(stamp!==null&&stamp>prior&&['total','drawdown','drawdown_pct'].every(k=>number(row[k])));prior=stamp
  }
  detachBacktest(value)
  return value as unknown as PortfolioArchive
}

export function portfolioMemberArchive(saved:PortfolioArchive,index:number) {
  const member=saved.receipt.members[index]
  if(!member)throw Error('原档没有该成员')
  return {member,result:saved.receipt.result.individual_results[member.key] as BacktestResult}
}
