import type { SignalScanRow } from './types'
import type { MarketDataMetadata } from './market-data-contract'
import type { ResearchSnapshot } from './research-snapshots'
import { frozenRadarSnapshot } from './radar-evidence.ts'
import { readRadarReview, reviewTime, type RadarReview } from './radar-review.ts'

/** Standalone lineage: the original scan input is NOT the displayed/recomputed chart. */
export interface RadarArchiveSource {
  contract: 'radar-archive-v1'
  review: RadarReview
  receipt: {
    contract: string; task_id: string; row_index: number; window_bars: number
    row: SignalScanRow; bars: Record<string,unknown>[]; metadata: MarketDataMetadata
    execution_version: string; current_execution_version: string; storage: string
  }
}
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
export function validateRadarArchiveSource(raw:unknown): RadarArchiveSource {
  if(!object(raw)||raw.contract!=='radar-archive-v1'||!object(raw.review)||!object(raw.receipt))throw Error('原扫描来源存档格式不完整')
  const source=raw as unknown as RadarArchiveSource,r=source.review
  if(!['买入','卖出','无指定信号'].includes(r.signal)||!object(r.evidence)||!object(r.params)||typeof r.name!=='string')throw Error('原扫描信号或任务引用不完整')
  const parsed=readRadarReview({review:'signal',symbol:r.symbol,category:r.category,adjust:r.adjust,scanAsOf:r.asOf,
    signalDate:r.signalDate,signal:r.signal==='买入'?'BUY':r.signal==='卖出'?'SELL':'',strategy:r.strategy,strategyName:r.name,
    params:JSON.stringify(r.params),scanFingerprint:r.fingerprint,scanTaskId:r.evidence.taskId,scanRowIndex:String(r.evidence.rowIndex)})
  if(!parsed.value||!Number.isSafeInteger(r.evidence.rowIndex)||r.evidence.rowIndex<0
    ||r.asOf!==parsed.value.asOf||r.signalDate!==parsed.value.signalDate)throw Error(parsed.error||'原扫描来源引用无效')
  frozenRadarSnapshot(source.receipt,parsed.value)
  const row=source.receipt.row
  const windowDates=new Set(source.receipt.bars.slice(-source.receipt.window_bars).map(b=>reviewTime(b.datetime).slice(0,16)))
  if(!Array.isArray(row.recent_signals)||row.recent_signals.some(s=>!s||!['BUY','SELL'].includes(s.direction)||!reviewTime(s.date)||!windowDates.has(reviewTime(s.date).slice(0,16))))throw Error('原扫描窗口内信号不完整或超出窗口')
  const last=row.recent_signals.at(-1)
  if(row.latest_signal!==(last?.direction??null)||reviewTime(row.signal_date)!==reviewTime(last?.date)
    ||!['holding','flat'].includes(row.position??'')||row.last_close!==source.receipt.bars.at(-1)?.close
    ||reviewTime(row.last_bar_date).slice(0,16)!==reviewTime(source.receipt.bars.at(-1)?.datetime).slice(0,16))throw Error('原扫描摘要与原始条目不一致')
  if(!row.metadata||row.metadata.data_fingerprint!==r.fingerprint||row.metadata.actual_adjust!==r.adjust||row.metadata.requested_adjust!==r.adjust||row.metadata.quality?.status==='error'
    ||row.metadata.category!==r.category||reviewTime(row.metadata.last_closed_at)!==parsed.value.asOf)throw Error('原扫描条目与行情来源不一致')
  return source
}

type Capture = Omit<ResearchSnapshot,'schema'|'id'|'owner'|'name'|'note'|'savedAt'>
export function copyRadarSourceForTarget(target:Capture['target'],source:RadarArchiveSource|null|undefined):RadarArchiveSource|undefined {
  if(!source)return undefined
  validateRadarArchiveSource(source)
  if(target.kind!=='stock'||target.code!==source.review.symbol
    ||target.market!==source.receipt.row.symbol.split(':')[0])throw Error('当前研究与原扫描标的不一致，未保存混合来源')
  return JSON.parse(JSON.stringify(source)) as RadarArchiveSource
}
export function withRadarArchiveSource(capture:Capture,source:RadarArchiveSource|null):Capture {
  const radarSource=copyRadarSourceForTarget(capture.target,source)
  return radarSource?{...capture,radarSource}:capture
}
