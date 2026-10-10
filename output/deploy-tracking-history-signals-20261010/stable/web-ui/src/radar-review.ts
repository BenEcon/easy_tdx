import type { AdjustMode, Category, SignalScanResult, SignalScanRow, SignalScanRecentSignal } from './types'
import type { BarSnapshot } from './api'
import { detectMarket } from './market.ts'
import { alignPeriodSnapshots, comparisonPeriods } from './period-comparison.ts'
import { assertMarketData } from './market-data-contract.ts'

export interface RadarReview {
  symbol: string; category: Category; adjust: AdjustMode; asOf: string
  signalDate: string; signal: string; strategy: string; name: string
  params: Record<string, number | string | boolean>; fingerprint: string
}
export const radarCacheKey = (owner: string) => `easy-tdx.signal-radar.v2.${encodeURIComponent(owner)}`
const text = (value: unknown) => typeof value === 'string' ? value : ''
const scalarParams = (value: unknown): value is RadarReview['params'] => !!value && typeof value === 'object' && !Array.isArray(value) && Object.values(value).every(item => typeof item === 'string' || typeof item === 'boolean' || typeof item === 'number' && Number.isFinite(item))
export interface CachedScan {
  schema: 'radar-cache-v2'; owner: string; result: SignalScanResult
  scannedAt: string; windowBars: number; adjust: string
}
export function readRadarCache(raw: string, owner: string): CachedScan | null {
  try {
    const cached = JSON.parse(raw)
    if (!owner || cached?.schema !== 'radar-cache-v2' || cached.owner !== owner || ![1,3,5,10].includes(cached.windowBars) || !['QFQ','HFQ','NONE'].includes(cached.adjust) || typeof cached.scannedAt !== 'string') return null
    const result = cached.result
    if (!result || !Array.isArray(result.rows) || !['total','buy_count','sell_count','error_count','elapsed'].every(key => typeof result[key] === 'number' && Number.isFinite(result[key]) && result[key] >= 0)) return null
    if (!result.rows.every((row: SignalScanRow) => row && (row.last_close === null || typeof row.last_close === 'number' && Number.isFinite(row.last_close)) && [null,'BUY','SELL'].includes(row.latest_signal) && [null,'holding','flat'].includes(row.position) && (row.signal_date === null || typeof row.signal_date === 'string') && (row.last_bar_date === null || typeof row.last_bar_date === 'string'))) return null
    if (!result.rows.every((row: SignalScanRow) => row && ['strategy_id','strategy_name','strategy','strategy_label','symbol','category'].every(key => typeof (row as unknown as Record<string, unknown>)[key] === 'string') && ['single','portfolio','multi'].includes(row.kind) && scalarParams(row.params) && Array.isArray(row.recent_signals) && row.recent_signals.every(signal => signal && typeof signal.date === 'string' && ['BUY','SELL'].includes(signal.direction)) && (row.error === null || typeof row.error === 'string') && (row.metadata == null || typeof row.metadata === 'object' && !Array.isArray(row.metadata) && typeof row.metadata.actual_adjust === 'string' && typeof row.metadata.source === 'string'))) return null
    return cached
  } catch { return null }
}
export function sameReviewStrategy(review: RadarReview | null, strategy: string, params: RadarReview['params']) {
  return !!review && review.strategy === strategy && Object.keys(review.params).length === Object.keys(params).length && Object.entries(review.params).every(([key, value]) => Object.hasOwn(params, key) && params[key] === value)
}
export function reviewTime(value: unknown): string {
  const raw = text(value).replace('T', ' ')
  const match = /^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$/.exec(raw)
  if (!match) return ''
  const [, y, m, d, h = '00', minute = '00', second = '00'] = match
  const date = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)))
  if (date.toISOString().slice(0, 10) !== `${y}-${m}-${d}` || Number(h) > 23 || Number(minute) > 59 || Number(second) > 59) return ''
  return `${y}-${m}-${d} ${h}:${minute}:${second}`
}
export function readRadarReview(query: Record<string, unknown>): { value: RadarReview | null; error: string } {
  if (query.review !== 'signal') return { value: null, error: '' }
  try {
    const symbol = text(query.symbol), category = text(query.category), adjust = text(query.adjust)
    if (!/^\d{6}$/.test(symbol) || !comparisonPeriods.some(item => item.value === category)) throw Error('标的或周期无效')
    if (!['QFQ', 'HFQ', 'NONE'].includes(adjust)) throw Error('缺少原扫描复权信息，请返回雷达重新扫描')
    if (query.market && query.market !== detectMarket(symbol)) throw Error('市场与证券代码不一致')
    const asOf = reviewTime(query.scanAsOf), signalDate = reviewTime(query.signalDate)
    if (!asOf) throw Error('缺少明确的原扫描截止时间，请重新扫描')
    if (query.signalDate && (!signalDate || signalDate > asOf)) throw Error('信号日期不在原扫描截止范围内')
    if (query.params != null && typeof query.params !== 'string') throw Error('策略参数无效')
    if (query.signal != null && !['', 'BUY', 'SELL'].includes(query.signal as string)) throw Error('信号方向无效')
    if (query.scanFingerprint != null && typeof query.scanFingerprint !== 'string') throw Error('原行情指纹无效')
    const paramsText = text(query.params) || '{}'
    if (paramsText.length > 8192) throw Error('策略参数过长')
    const params = JSON.parse(paramsText)
    if (!scalarParams(params)) throw Error('策略参数无效')
    const strategy = text(query.strategy)
    if (!/^[\w.-]{1,100}$/.test(strategy)) throw Error('缺少有效策略名称')
    const fingerprint = text(query.scanFingerprint)
    if (fingerprint && !/^[a-f0-9]{64}$/.test(fingerprint)) throw Error('原行情指纹无效')
    return { value: { symbol, category: category as Category, adjust: adjust as AdjustMode, asOf, signalDate,
      signal: query.signal === 'BUY' ? '买入' : query.signal === 'SELL' ? '卖出' : '无指定信号', strategy,
      name: (text(query.strategyName) || text(query.strategyLabel) || strategy).slice(0, 200), params, fingerprint }, error: '' }
  } catch (error) { return { value: null, error: error instanceof Error ? error.message : '复核参数无效' } }
}
export function radarReviewQuery(row: SignalScanRow, capturedAdjust: string, signal?: SignalScanRecentSignal) {
  const match = /^(?:(SH|SZ|BJ):?)?(\d{6})$/.exec(row.symbol)
  const metadata = row.metadata
  const query: Record<string, string> = {
    review: 'signal', autoRun: '1', symbol: match?.[2] ?? '', market: match?.[1] ?? detectMarket(match?.[2] ?? ''),
    category: row.category, adjust: metadata?.actual_adjust || capturedAdjust,
    scanAsOf: metadata?.last_closed_at || '',
    scanFingerprint: metadata?.data_fingerprint || '', signal: signal?.direction || row.latest_signal || '',
    signalDate: signal?.date || row.signal_date || '', strategy: row.strategy,
    strategyName: row.strategy_name, strategyLabel: row.strategy_label, params: JSON.stringify(row.params), count: '800',
  }
  const parsed = readRadarReview(query)
  if (!parsed.value) throw Error(parsed.error)
  return query
}
export function sameReviewInput(review: RadarReview | null, code: string, category: string, adjust: string) {
  return !!review && review.symbol === code && review.category === category && review.adjust === adjust
}
export function snapshotForReview(snapshot: BarSnapshot, review: RadarReview): BarSnapshot {
  assertMarketData(snapshot.metadata, review.adjust)
  if (snapshot.metadata.category !== review.category) throw Error('复核行情周期与原扫描不一致')
  const aligned = alignPeriodSnapshots(snapshot, snapshot, review.asOf, review.adjust).primary
  if (!aligned.bars.length) throw Error('当前返回行情未覆盖原扫描截止时间；不能用最新行情冒充原扫描')
  return { bars: aligned.bars, metadata: { ...snapshot.metadata,
    data_fingerprint: aligned.excluded ? undefined : snapshot.metadata.data_fingerprint,
    source_fingerprint: snapshot.metadata.data_fingerprint,
    last_bar_at: aligned.bars.at(-1)!.datetime, last_closed_at: aligned.bars.at(-1)!.period_end,
    range_start: aligned.bars[0]!.datetime, range_end: aligned.bars.at(-1)!.period_end,
    consistency_note: `按原扫描截止过滤当前重取行情（本次排除 ${aligned.excluded} 根未收盘或截止后 K 线）；未保存原始扫描行情，预热区间和复权历史可能不同，不代表重现原扫描。`,
  } }
}
