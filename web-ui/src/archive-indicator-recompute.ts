import { archiveObject, archiveNumber } from './archive-data-validation.ts'
import { validateFrozenChartIndicators, type FrozenChartIndicators } from './frozen-chart-indicators.ts'
import { getIndicatorDefinition } from './technical-indicators.ts'
import type { Bar } from './types'

const sameParams=(a:Record<string,unknown>,b:Record<string,unknown>)=>Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(key=>Object.hasOwn(b,key)&&a[key]===b[key])

export function archivedIndicatorSettings(frozen:FrozenChartIndicators) {
  for(const item of frozen.indicators){
    const definition=getIndicatorDefinition(item.type)
    if(definition.value!==item.type)throw Error(`原档指标 ${item.type} 不受当前版本支持，未替换`)
    if(Object.keys(item.params).length!==Object.keys(definition.defaultParams).length||Object.keys(definition.defaultParams).some(key=>!Object.hasOwn(item.params,key)))throw Error(`${item.label} 原参数不完整，不能用默认值补算`)
    const names=item.type==='volume'?['成交量','MAVOL5','MAVOL10']:definition.outputs.map(key=>key.replace(`${definition.code}_`,''))
    if(item.series.length!==names.length||item.series.some((row,i)=>row.name!==names[i]))throw Error(`${item.label} 原输出列与当前指标不兼容，未更换其含义`)
  }
  return {averages:frozen.averages.map(({period,enabled})=>({period,enabled})),indicators:frozen.indicators.map(({type,params})=>({type,params:{...params}}))}
}

/** Replace values only, retaining the saved declarative chart style; no network or defaults. */
export function projectRecomputedIndicators(value:unknown,before:FrozenChartIndicators,bars:Bar[]):FrozenChartIndicators {
  const fail=():never=>{throw Error('重算指标缺少匹配的参数、输出列或完整序列，未保存部分指标')}
  const settings=archivedIndicatorSettings(before),next=structuredClone(before)
  const values=(list:unknown):list is Array<number|null>=>Array.isArray(list)&&list.length===bars.length&&list.every(n=>n===null||archiveNumber(n))
  if(!archiveObject(value)||!Array.isArray(value.averages)||!Array.isArray(value.indicators)||value.averages.length!==settings.averages.length||value.indicators.length!==settings.indicators.length)return fail()
  value.averages.forEach((row,i)=>{
    const expected=settings.averages[i]!
    if(!archiveObject(row)||row.period!==expected.period||row.enabled!==expected.enabled||!values(row.values))return fail()
    next.averages[i]!.values=[...row.values]
  })
  value.indicators.forEach((row,i)=>{
    const expected=settings.indicators[i]!,definition=getIndicatorDefinition(expected.type)
    if(!archiveObject(row)||row.type!==expected.type||!archiveObject(row.params)||!sameParams(row.params,expected.params)||!Array.isArray(row.rows)||row.rows.length!==bars.length)return fail()
    for(const point of row.rows)if(!archiveObject(point)||Object.keys(point).length!==definition.outputs.length||definition.outputs.some(key=>!Object.hasOwn(point,key)||(point[key]!==null&&!archiveNumber(point[key]))))return fail()
    next.indicators[i]!.series.forEach((series,j)=>series.values=(row.rows as Record<string,number|null>[]).map(point=>point[definition.outputs[j]!]!))
  })
  return validateFrozenChartIndicators(next,bars)
}
