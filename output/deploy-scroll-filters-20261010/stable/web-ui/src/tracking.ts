import type { ResearchTarget, BoardKind } from './chanlun-target.ts'
import type { Study, StudyPeriod } from './research-study.ts'
import { detectMarket } from './market.ts'
import type {BarSnapshot} from './api'

export type TrackingKind = 'stock' | 'board' | 'index' | 'fund'
export interface TrackingTarget { kind: TrackingKind; market: string; code: string; name: string; boardType?: BoardKind }
export interface TrackingGroup { id: string; name: string; targets: TrackingTarget[] }
export interface TrackingBook { version: 1; revision: string; groups: TrackingGroup[] }
export interface TrackingEntry { target: TrackingTarget; sources: string[] }
export interface ExpansionIssue { target: TrackingTarget; reason: string }
export const trackingLabels = { stock: '个股', board: '板块', index: '指数', fund: '场内基金' }
export const trackingKey = (t: TrackingTarget) => `${t.kind}:${t.market}:${t.code}${t.kind === 'board' ? `:${t.boardType}` : ''}`
export const trackingTitle = (t: TrackingTarget) => `${t.code}-${t.name || '名称待补充'}`
export const emptyTrackingBook = (): TrackingBook => ({ version: 1, revision: '', groups: [] })
export function validateTrackingTarget(t: TrackingTarget): void {
  if (!t || !Object.hasOwn(trackingLabels, t.kind) || typeof t.code !== 'string' || typeof t.market !== 'string' || !/^\d{6}$/.test(t.code) || typeof t.name !== 'string' || t.name.length > 80) throw new Error('标的类型、六位代码或名称不正确')
  if (t.kind === 'board') {
    if (!['HY','HY2','GN','FG','DQ'].includes(t.boardType ?? '') || !/^[\w.-]{1,16}$/.test(t.market)) throw new Error('请从板块目录选择有效板块')
  } else if (!['SH','SZ','BJ'].includes(t.market)) throw new Error('请选择正确的交易市场')
  if (t.kind === 'stock' && detectMarket(t.code) !== t.market) throw new Error('个股代码与交易市场不匹配；追踪指数请使用指数类型')
  if (t.kind === 'index' && t.market === 'BJ') throw new Error('当前指数分析支持沪深市场')
  if (t.kind === 'fund' && !((t.market === 'SH' && /^5\d{5}$/.test(t.code)) || (t.market === 'SZ' && /^1[568]\d{4}$/.test(t.code)))) throw new Error('仅支持沪深场内基金代码；场外基金暂不支持')
}
export function readTrackingBook(value: unknown): TrackingBook {
  if (value == null) return emptyTrackingBook()
  const book = value as TrackingBook
  if (book.version !== 1 || typeof book.revision !== 'string' || !Array.isArray(book.groups) || book.groups.length > 50) throw new Error('追踪分组数据版本或格式不正确；未覆盖原数据')
  const ids = new Set<string>()
  for (const group of book.groups) {
    if (!group || typeof group.id !== 'string' || !group.id || ids.has(group.id) || typeof group.name !== 'string' || !group.name.trim() || group.name.length > 40 || !Array.isArray(group.targets)) throw new Error('追踪分组数据损坏；未覆盖原数据')
    ids.add(group.id)
    const targets = new Set<string>()
    for (const target of group.targets) {
      validateTrackingTarget(target)
      if (targets.has(trackingKey(target))) throw new Error('追踪分组包含重复标的')
      targets.add(trackingKey(target))
    }
  }
  if (new TextEncoder().encode(JSON.stringify(book)).length > 40000) throw new Error('分组存储已超过 40KB，请减少直接添加的标的；板块成员不占用分组存储')
  return JSON.parse(JSON.stringify(book)) as TrackingBook
}
export function researchTarget(t: TrackingTarget): ResearchTarget {
  return { ...t, kind: t.kind === 'fund' ? 'stock' : t.kind }
}
export function trackingAdjustment(t: TrackingTarget): 'QFQ' | 'NONE' { return t.kind === 'stock' ? 'QFQ' : 'NONE' }
function memberTarget(row: Record<string, unknown>): TrackingTarget {
  const markets: Record<string, string> = { '0':'SZ', '1':'SH', '2':'BJ', SH:'SH', SZ:'SZ', BJ:'BJ' }
  const target: TrackingTarget = { kind:'stock', code:String(row.code ?? ''), market:markets[String(row.market)] ?? '', name:String(row.name ?? '') }
  validateTrackingTarget(target)
  return target
}
/** The adapter requests the provider's entire membership; never apply a display-page limit. */
export async function expandTrackingGroup(group: TrackingGroup, load: (code: string) => Promise<{data: Record<string,unknown>[]; count: number}>, signal: AbortSignal) {
  const entries = new Map<string, TrackingEntry>()
  const issues: ExpansionIssue[] = []
  function add(target: TrackingTarget, source: string) {
    const key = trackingKey(target), prior = entries.get(key)
    if (prior) { if (!prior.sources.includes(source)) prior.sources.push(source) }
    else entries.set(key, { target:{...target}, sources:[source] })
  }
  for (const target of group.targets) {
    signal.throwIfAborted(); validateTrackingTarget(target)
    add(target, '直接追踪')
    if (target.kind !== 'board') continue
    try {
      const response = await load(target.code)
      signal.throwIfAborted()
      if (!response.data.length) throw new Error('未返回成员，不能视为完整空板块')
      if (response.count !== response.data.length || response.data.length >= 100000) throw new Error('成员数量不完整或达到接口上限；请重试核实')
      // Validate the entire response before accepting any partial membership.
      const members = response.data.map(memberTarget)
      for (const member of members) add(member, trackingTitle(target))
    } catch (e) {
      signal.throwIfAborted()
      issues.push({ target, reason:e instanceof Error ? e.message : String(e) })
    }
  }
  return { entries:[...entries.values()], issues }
}
export interface TrackingEvidence {adjust:string;requested_count:number;series:Array<{category:StudyPeriod;snapshot:BarSnapshot}>}
export interface TrackingAnalysis extends TrackingEntry { state: 'pending' | 'running' | 'done' | 'error' | 'cancelled'; study?: Study; error?: string; evidence?:TrackingEvidence }
/** Descriptive breadth only: each deduplicated instrument has one vote, not a portfolio return. */
export const breadthMetrics = {covered:'已覆盖',total:'全部标的',penUp:'最近严格笔向上',penDown:'最近严格笔向下',aboveZero:'双线轴上',belowZero:'双线轴下',divergence:'存在已确认背离',buy:'存在结构买点',sell:'存在结构卖点',macdBuy:'存在 M1 买入提示',macdSell:'存在 M1 卖出提示'} as const
export type BreadthMetric = keyof typeof breadthMetrics
export interface BreadthFilter {category: StudyPeriod; metric: BreadthMetric}
export function matchesBreadth(row: TrackingAnalysis, selection: BreadthFilter): boolean {
  if(selection.metric === 'total')return true
  const item=row.study?.rows.find(r=>r.category===selection.category&&!r.error)
  if(!item)return false
  const points=item.buy_sell_points??[]
  switch(selection.metric){
    case 'covered':return true
    case 'penUp':return item.direction_observation?.strict?.direction==='up'
    case 'penDown':return item.direction_observation?.strict?.direction==='down'
    case 'aboveZero':return (item.pairs?.macd?.fast??0)>0&&(item.pairs?.macd?.slow??0)>0
    case 'belowZero':return (item.pairs?.macd?.fast??0)<0&&(item.pairs?.macd?.slow??0)<0
    case 'divergence':return item.divergences?.some(d=>d.status==='confirmed')??false
    case 'buy':case 'sell':return points.some(p=>p.family==='structure'&&p.status==='confirmed'&&p.side===selection.metric)
    case 'macdBuy':case 'macdSell':return points.some(p=>p.family==='macd'&&p.status==='confirmed'&&p.side===(selection.metric==='macdBuy'?'buy':'sell'))
  }
}
export function trackingBreadth(rows: TrackingAnalysis[], periods: StudyPeriod[]) {
  return periods.map(category => {
    const counts=Object.fromEntries((Object.keys(breadthMetrics) as BreadthMetric[]).map(metric=>[metric,rows.filter(row=>matchesBreadth(row,{category,metric})).length])) as Record<BreadthMetric,number>
    return {category,...counts}
  })
}
/** Sequential, cancellable queue. Unstarted rows remain explicit on cancellation. */
export async function analyzeTrackingEntries(entries: TrackingEntry[], analyze: (target: TrackingTarget, signal: AbortSignal) => Promise<Study>, signal: AbortSignal, publish: (rows: TrackingAnalysis[]) => void) {
  const rows: TrackingAnalysis[] = entries.map(entry => ({...entry, state:'pending'}))
  const emit = () => publish(rows.map(row => ({...row})))
  emit()
  for (const row of rows) {
    if (signal.aborted) break
    row.state = 'running'; emit()
    try {
      const study = await analyze(row.target, signal)
      signal.throwIfAborted()
      if (!study?.rows?.length) throw new Error('分析接口没有返回周期结果')
      const {tracking_evidence,...result}=study as Study&{tracking_evidence?:TrackingEvidence}
      row.study = result
      if(tracking_evidence)row.evidence=tracking_evidence
      if (study.rows.some(item => item.error)) throw new Error(study.rows.filter(item => item.error).map(item => `${item.category}: ${item.error}`).join('；'))
      row.state = 'done'
    } catch (e) {
      if(e&&typeof e==='object'&&'tracking_evidence' in e)row.evidence=e.tracking_evidence as TrackingEvidence
      row.state = signal.aborted ? 'cancelled' : 'error'; row.error = signal.aborted ? '已停止' : e instanceof Error ? e.message : String(e)
    }
    emit()
  }
  for (const row of rows) if (row.state === 'pending' || row.state === 'running') row.state = 'cancelled'
  emit()
  return rows
}
export function trackingChartQuery(t: TrackingTarget, category: StudyPeriod) {
  validateTrackingTarget(t)
  return { from:'tracking', targetKind:t.kind, symbol:t.code, market:t.market, name:t.name, boardType:t.boardType ?? '', category, adjust:trackingAdjustment(t) }
}
