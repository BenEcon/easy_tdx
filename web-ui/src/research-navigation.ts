import { comparisonPeriods } from './period-comparison.ts'
import { validateTrackingTarget, type TrackingTarget } from './tracking.ts'
import type { AdjustMode, Category } from './types'
import type { BoardKind } from './chanlun-target'

export interface ResearchNavigation { target: TrackingTarget; category: Category; adjust: AdjustMode; count: number; source: 'market' | 'boards' }
export interface NavigationTarget { target: TrackingTarget | null; error: string }
// These are the periods offered by both destination forms, not every API period.
export const navigationPeriods = comparisonPeriods.filter(period=>period.value!=='MIN_1')
const markets: Record<string,string> = {'0':'SZ','1':'SH','2':'BJ',SH:'SH',SZ:'SZ',BJ:'BJ'}
const boardKinds: Record<string,BoardKind> = {'0':'HY','1':'HY2','3':'GN','4':'FG','5':'DQ',HY:'HY',HY2:'HY2',GN:'GN',FG:'FG',DQ:'DQ'}
const text = (value: unknown) => typeof value === 'string' ? value : ''
// A versioned entry is one complete context, never a partial override of a
// saved strategy, radar receipt or a future route's execution parameters.
const entryKeys = new Set(['researchContext','from','targetKind','market','symbol','name','boardType','category','adjust','count','range'])
export function navigationTarget(row: Record<string,unknown>, options: {boardType?:string; market?:string; board?:boolean} = {}): NavigationTarget {
  try {
    const raw = text(options.board ? row.board_code ?? row.code ?? row.board_symbol : row.code ?? row.symbol)
    const match = /^(?:(SH|SZ|BJ):?)?(\d{6})$/i.exec(raw)
    if (!match) throw Error('缺少完整六位代码；未猜测标的')
    const code = match[2]!, prefix = match[1]?.toUpperCase()
    const provided = options.board ? row.board_market ?? row.market : row.market
    const market = options.board ? String(provided ?? '') : markets[String(provided ?? prefix ?? options.market ?? '').toUpperCase()]
    if (!market || (prefix && prefix !== market)) throw Error('缺少明确市场或市场字段冲突')
    const name = text(options.board ? row.board_name ?? row.name : row.name ?? row.short_name).slice(0,80)
    let kind: TrackingTarget['kind']
    let boardType: BoardKind | undefined
    if (options.board) {
      kind = 'board'; boardType = boardKinds[String(row.board_type ?? options.boardType ?? '')]
      if (!boardType) throw Error('板块分类不明确，请选择具体行业／概念分类后重查')
    } else if ((market==='SH' && /^000\d{3}$/.test(code)) || (market==='SZ' && /^399\d{3}$/.test(code))) kind='index'
    else if ((market==='SH' && /^5\d{5}$/.test(code)) || (market==='SZ' && /^1[568]\d{4}$/.test(code))) kind='fund'
    else if ((market==='SH' && /^(6\d{5}|900\d{3})$/.test(code)) || (market==='SZ' && /^(00\d{4}|30[01]\d{3}|200\d{3})$/.test(code)) || (market==='BJ' && /^(43|83|87|92|93)\d{4}$/.test(code))) kind='stock'
    else throw Error('当前入口不能可靠识别此证券类型；未当作普通股票打开')
    const target: TrackingTarget = {kind,market,code,name,...(boardType?{boardType}:{})}
    validateTrackingTarget(target)
    return {target,error:''}
  } catch(error) { return {target:null,error:error instanceof Error?error.message:String(error)} }
}
export function researchNavigationQuery(value: ResearchNavigation): Record<string,string> {
  validateTrackingTarget(value.target)
  const identified = navigationTarget({code:value.target.code,market:value.target.market,name:value.target.name,board_type:value.target.boardType}, {board:value.target.kind==='board'})
  if (!identified.target || identified.target.kind!==value.target.kind || (value.target.kind!=='board' && value.target.boardType!==undefined)) throw Error('标的类型与市场、代码不匹配')
  if (!navigationPeriods.some(p=>p.value===value.category) || !['NONE','QFQ','HFQ'].includes(value.adjust) || ![200,400,600,800].includes(value.count) || !['market','boards'].includes(value.source)) throw Error('研究入口参数不受支持')
  if (value.target.kind!=='stock' && value.adjust!=='NONE') throw Error('指数、板块和场内基金入口必须明确不复权')
  return {researchContext:'v1',from:value.source,targetKind:value.target.kind,market:value.target.market,symbol:value.target.code,name:value.target.name,boardType:value.target.boardType??'',category:value.category,adjust:value.adjust,count:String(value.count),range:'latest'}
}
export function readResearchNavigation(query: Record<string,unknown>): {value:ResearchNavigation|null;error:string} {
  if (query.researchContext === undefined) return {value:null,error:''}
  try {
    if (query.researchContext!=='v1' || query.range!=='latest' || !['market','boards'].includes(text(query.from))) throw Error('研究入口版本或范围不支持')
    for (const key of ['targetKind','market','symbol','name','boardType','category','adjust','count']) if (typeof query[key]!=='string') throw Error('研究入口参数缺失或重复')
    if (Object.keys(query).some(key=>!entryKeys.has(key))) throw Error('实时研究入口含未支持或混用参数，请从市场／板块重新打开')
    const target = {kind:query.targetKind,market:query.market,code:query.symbol,name:query.name,...(query.boardType?{boardType:query.boardType}:{})} as TrackingTarget
    const value:ResearchNavigation = {target,category:query.category as Category,adjust:query.adjust as AdjustMode,count:Number(query.count),source:query.from as ResearchNavigation['source']}
    if (String(value.count)!==query.count) throw Error('历史根数格式不正确')
    researchNavigationQuery(value)
    return {value,error:''}
  } catch(error) { return {value:null,error:error instanceof Error?error.message:String(error)} }
}
export function canOpenBacktest(target: TrackingTarget) { return target.kind==='stock' || target.kind==='fund' }
