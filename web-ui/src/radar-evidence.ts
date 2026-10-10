import type { BarSnapshot } from './api'
import type { Bar } from './types'
import { assertMarketData } from './market-data-contract.ts'
import { reviewTime, sameReviewStrategy, type RadarReview } from './radar-review.ts'
import { detectMarket } from './market.ts'
import type { RadarArchiveSource } from './radar-archive.ts'

/** Bind the authenticated server receipt to the selected row, never a live fallback. */
export function frozenRadarSnapshot(raw: unknown, review: RadarReview): BarSnapshot {
  const r=raw as RadarArchiveSource['receipt']
  const reference=review.evidence
  if(!reference||!r||r.contract!=='radar-evidence-v1'||r.task_id!==reference.taskId||r.row_index!==reference.rowIndex)throw Error('原任务行情引用不一致')
  const row=r.row
  if(!row||row.error||row.symbol!==`${detectMarket(review.symbol)}:${review.symbol}`||row.category!==review.category||!row.params||typeof row.params!=='object'||Array.isArray(row.params)||!sameReviewStrategy(review,row.strategy,row.params))throw Error('原扫描标的或策略参数与链接不一致')
  assertMarketData(r.metadata,review.adjust)
  if(r.metadata.category!==review.category||r.metadata.data_fingerprint!==review.fingerprint||reviewTime(r.metadata.last_closed_at)!==review.asOf)throw Error('原扫描行情指纹或截止不一致')
  if(review.signalDate&&(!Array.isArray(row.recent_signals)||!row.recent_signals.some(s=>s&&reviewTime(s.date)===review.signalDate&&(review.signal==='买入'?s.direction==='BUY':review.signal==='卖出'?s.direction==='SELL':true))))throw Error('所选信号不在原扫描记录中')
  if(!['memory','persistent'].includes(r.storage)||![r.execution_version,r.current_execution_version].every(v=>typeof v==='string'&&v.length>0&&v.length<=256))throw Error('原扫描版本或保存方式无效')
  if(!Number.isInteger(r.window_bars)||r.window_bars<1||r.window_bars>30)throw Error('原扫描信号窗口无效')
  if(!Array.isArray(r.bars)||r.bars.length<2||r.bars.length>800)throw Error('原扫描行情不完整')
  let previous=''
  const bars:Bar[]=r.bars.map(b=>{
    const date=reviewTime(b?.datetime),end=reviewTime(b?.period_end)
    if(!date||date<=previous||!end||end<date||end>review.asOf||b.is_closed!==true)throw Error('原扫描行情顺序或收盘状态无效')
    const values=[b.open,b.high,b.low,b.close,b.vol??b.volume,b.amount]
    if(!values.every(v=>typeof v==='number'&&Number.isFinite(v)&&v>=0))throw Error('原扫描价格或成交数据无效')
    const [open,high,low,close,vol,amount]=values as [number,number,number,number,number,number]
    if(low<=0||low>Math.min(open,close)||high<Math.max(open,close))throw Error('原扫描高低价关系无效')
    previous=date
    return {datetime:String(b.datetime),period_end:String(b.period_end),is_closed:true,open,high,low,close,vol,amount}
  })
  if(reviewTime(bars.at(-1)!.period_end)!==review.asOf)throw Error('原扫描末根行情与截止不一致')
  const compatible=r.execution_version===r.current_execution_version
  // Vue may proxy a receipt read from a local/cloud archive. Detach the JSON
  // wire data without structuredClone's DataCloneError on reactive proxies.
  return {bars,radarSource:JSON.parse(JSON.stringify({contract:'radar-archive-v1',review,receipt:r})),metadata:{...r.metadata,original_task:{task_id:r.task_id,row_index:r.row_index,execution_version:r.execution_version,current_execution_version:r.current_execution_version,storage:r.storage,compatible},
    consistency_note:`使用原任务保存的 ${bars.length} 根完整行情（含原预热区间），没有重新取行情。${compatible?'当前执行版本与原扫描一致。':'执行版本已变化，后续按当前版本重算，不声称原算法重放。'}原行情是扫描时取得的版本，并不保证属于历史交易当日的数据版本。`}}
}
