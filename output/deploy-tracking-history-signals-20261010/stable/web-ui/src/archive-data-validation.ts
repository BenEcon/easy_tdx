/** Archive validation only: no rounding, timezone guesses from the browser, or repair. */
export const archiveObject = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value)
export const archiveNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

/** Naive market times are China wall-clock; explicit ISO offsets retain their instant. */
export function archiveTime(value: unknown, requireClock = false): number | null {
  if (typeof value !== 'string') return null
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?(Z|[+-]\d{2}:\d{2})?)?$/.exec(value)
  if (!match || (requireClock && match[4] === undefined)) return null
  const year=Number(match[1]),month=Number(match[2]),day=Number(match[3]),hour=Number(match[4]??0),minute=Number(match[5]??0),second=Number(match[6]??0)
  if(year<1||month<1||month>12||day<1||day>31||hour>23||minute>59||second>59)return null
  const date=new Date(0)
  date.setUTCFullYear(year,month-1,day);date.setUTCHours(hour,minute,second,0)
  if(date.getUTCFullYear()!==year||date.getUTCMonth()!==month-1||date.getUTCDate()!==day)return null
  let offset=480
  if(match[8]==='Z')offset=0
  else if(match[8]){
    const h=Number(match[8].slice(1,3)),m=Number(match[8].slice(4,6))
    if(h>23||m>59)return null
    offset=(h*60+m)*(match[8][0]==='-'?-1:1)
  }
  return date.getTime()+Number(`0.${match[7]??0}`)*1000-offset*60_000
}

export function validateArchiveBars(value: unknown): void {
  if(!Array.isArray(value)||!value.length||value.length>8000)throw Error('存档行情根数不正确')
  let prior=-Infinity
  for(const bar of value){
    if(!archiveObject(bar))throw Error('存档行情不是有效记录')
    const instant=archiveTime(bar.datetime,true)
    if(instant===null||instant<=prior||![bar.open,bar.close,bar.high,bar.low].every(archiveNumber)
      ||Number(bar.low)>Math.min(Number(bar.open),Number(bar.close))||Number(bar.high)<Math.max(Number(bar.open),Number(bar.close))
      ||['vol','amount'].some(key=>bar[key]!==undefined&&!archiveNumber(bar[key]))
      ||(bar.is_closed!==undefined&&typeof bar.is_closed!=='boolean'))throw Error('存档行情的日期、顺序、OHLC 或成交量格式不正确')
    prior=instant
  }
}
