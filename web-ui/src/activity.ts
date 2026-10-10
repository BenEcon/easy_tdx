export const ACTIVE_IDLE_MS = 60_000
export function activityEligible(visible: boolean, focused: boolean, lastAction: number, now: number) {
  return visible && focused && now >= lastAction && now-lastAction < ACTIVE_IDLE_MS
}

export function activityDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '未取得'
  const minutes=Math.floor(seconds/60),hours=Math.floor(minutes/60)
  return hours ? `${hours} 小时 ${minutes%60} 分` : minutes ? `${minutes} 分 ${Math.floor(seconds%60)} 秒` : `${Math.floor(seconds)} 秒`
}

export interface ActivityLocation {state:string; label:string; isp?:string; checked_at?:number; source?:string}
export interface ActivityTarget {key:string; code:string; market:string}
export interface ActivityCodeGroup extends ActivityTarget {queries:number; users:number; last_seen:number}
export interface ActivityEvent {id:number; owner:string; username:string; occurred:number; kind:'login'|'query'; query_origin?:'user'|'server'|'legacy'; ip:string; feature:string; outcome:string; details:Record<string,unknown>; location:ActivityLocation|null; targets?:ActivityTarget[]}
export interface ActivityUser {id:string; username:string; active_seconds:number; queries:number; logins:number; last_seen:number|null; recently_active:boolean}

export function activityTime(value: number|null) {
  return value == null ? '暂无记录' : new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(value*1000)
}
const fieldLabels:Record<string,string>={code:'标的',symbol:'标的',market:'市场',category:'周期',adjust:'复权',kind:'类型',board_type:'板块类型',board_code:'板块',stock_code:'股票',stock_market:'股票市场',strategy:'策略',strategy_name:'策略',start_date:'开始',end_date:'结束',as_of:'截止',count:'根数',visible_count:'可见根数',series:'周期序列',symbols:'标的',codes:'标的',stocks:'标的'}
export function activityTargetLabel(target:ActivityTarget,names:Record<string,string>):string {
  return `${target.code}-${names[target.key] || '名称待补全'}`
}
export function activityMarketLabel(market:string):string {
  return ({SH:'沪市',SZ:'深市',BJ:'北交所',BOARD:'板块','?':'市场未记录'} as Record<string,string>)[market] || market
}
export function activityDetails(details:Record<string,unknown>): string {
  const labels: Record<string, string> = {...fieldLabels, board_symbol:'板块'}
  return Object.entries(details).filter(([key])=>labels[key]).map(([key,value])=>{
    const formatted = Array.isArray(value) ? value.map(v=>typeof v==='object'&&v!==null?Object.values(v).join(' / '):String(v)).join('、') : String(value)
    const total=details[`${key}_total`]
    return `${labels[key]}：${formatted}${typeof total==='number'&&Array.isArray(value)&&total>value.length?`（共 ${total} 项，仅记前 ${value.length} 项）`:''}`
  }).join(' · ') || '无标的参数（列表或概览查询）'
}
