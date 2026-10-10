import { archiveObject as object, archiveNumber as number, archiveTime, validateArchiveBars } from './archive-data-validation.ts'
import { copyRadarSourceForTarget, validateRadarArchiveSource, type RadarArchiveSource } from './radar-archive.ts'
import type { BacktestRequest, BacktestResult } from './types'
import type { MarketDataMetadata } from './market-data-contract'

export interface BacktestArchive {
  format:'backtest-research-v1'; title:string; savedAt:string
  request:BacktestRequest; metadata:MarketDataMetadata; result:BacktestResult
  radarSource?:RadarArchiveSource
}
export function detachBacktest<T>(value:T):T {
  return JSON.parse(JSON.stringify(value,(_key,item)=>{
    if(typeof item==='number'&&!Number.isFinite(item))throw Error('回测原档含非有限数值，未转换为空值')
    return item
  })) as T
}
const periods=new Set(['DAY','WEEK','MONTH','MIN_1','MIN_5','MIN_15','MIN_30','MIN_60','MIN_120'])
const metrics=['total_return','annual_return','max_drawdown','max_dd_duration','sharpe','sortino','calmar','total_trades','win_trades','lose_trades','rejected_trades','win_rate','profit_factor','avg_win','avg_loss','max_win','max_loss','avg_holding_days','volatility']
/** Validate structure without recalculating, rounding or upgrading original results. */
export function validateBacktestArchive(value:unknown):BacktestArchive {
  if(!object(value)||value.format!=='backtest-research-v1'||typeof value.title!=='string'||!value.title.trim()||value.title.length>500||archiveTime(value.savedAt,true)===null
    ||!object(value.request)||!object(value.result)||!object(value.metadata))throw Error('回测原档格式或来源不完整')
  const r=value.request,result=value.result,m=value.metadata
  if(typeof r.symbol!=='string'||!/^(SH|SZ|BJ):\d{6}$/.test(r.symbol)||typeof r.category!=='string'||!periods.has(r.category)
    ||typeof r.adjust!=='string'||!['NONE','QFQ','HFQ'].includes(r.adjust)||typeof r.strategy!=='string'||!r.strategy.trim()||!object(r.params)
    ||Object.values(r.params).some(v=>!['string','boolean'].includes(typeof v)&&!number(v))
    ||!number(r.cash)||r.cash<=0||['commission','min_commission','stamp_tax','slippage'].some(k=>!number(r[k])||Number(r[k])<0)
    ||!['next_open','next_close'].includes(String(r.execution))||typeof r.execution!=='string')throw Error('回测原档缺少完整标的、策略或交易参数')
  const start=archiveTime(r.start_date),end=archiveTime(r.end_date)
  if(start===null||end===null||start>end)throw Error('回测原档区间无效')
  validateArchiveBars(r.ohlcv)
  if(m.category!==r.category||m.actual_adjust!==r.adjust||m.requested_adjust!==r.adjust)throw Error('回测原档与行情口径不一致')
  if(!object(result.performance)||!object(result.config)||!Array.isArray(result.equity_curve)||!result.equity_curve.length
    ||!Array.isArray(result.trades)||!Array.isArray(result.positions)||result.positions.some(p=>!object(p)))throw Error('回测原档缺少完整净值、成交或持仓结果')
  for(const key of metrics)if(!Object.hasOwn(result.performance,key)||(result.performance[key]!==null&&!number(result.performance[key])))throw Error('回测原档绩效字段不完整')
  const times=new Set((r.ohlcv as Record<string,unknown>[]).map(b=>archiveTime(b.datetime,true)))
  let prior=-Infinity
  for(const row of result.equity_curve){
    if(!object(row))throw Error('回测净值记录无效')
    const t=archiveTime(row.datetime,true)
    if(t===null||t<=prior||!times.has(t)||['cash','position_value','total','drawdown','drawdown_pct'].some(k=>!number(row[k])))throw Error('回测净值记录与原行情不匹配')
    prior=t
  }
  for(const row of result.trades){
    if(!object(row)||!times.has(archiveTime(row.datetime,true))||!['BUY','SELL'].includes(String(row.direction))||typeof row.direction!=='string'||typeof row.rejected!=='boolean'
      ||['size','price','commission','slippage','pnl'].some(k=>!number(row[k])))throw Error('回测成交记录无效或不在原行情内')
  }
  if(value.radarSource!==undefined){
    if(!object(value.radarSource))throw Error('原扫描来源格式不完整')
    copyRadarSourceForTarget({kind:'stock',market:r.symbol.split(':')[0]!,code:r.symbol.split(':')[1]!},validateRadarArchiveSource(value.radarSource))
  }
  // Check unknown nested fields too, while preserving every original field.
  detachBacktest(value)
  return value as unknown as BacktestArchive
}
