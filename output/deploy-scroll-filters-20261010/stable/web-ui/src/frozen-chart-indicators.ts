import type { Bar } from './types'
import { buildIndicatorSeries, getIndicatorDefinition, type IndicatorParams } from './technical-indicators.ts'
import { INDICATOR_LINE_COLORS, movingAverageColor } from './moving-averages.ts'
import { provisionalColumn } from './provisional-bars.ts'

type FrozenSeries = { name: string; type: 'line' | 'bar'; values: Array<number | null>; color: string; symbol: 'none' | 'circle' }
export interface FrozenIndicator {
  type: string; params: IndicatorParams; label: string; placement: 'none' | 'overlay' | 'panel'
  bounds?: [number, number]; guideLines: number[]; series: FrozenSeries[]
}
export interface FrozenChartIndicators {
  schema: 1; source: 'captured-chart-series'; dates: string[]
  averages: Array<{ period: number; enabled: boolean; values: Array<number | null> }>
  indicators: FrozenIndicator[]
}

export function chartMovingAverage(bars: Bar[], period: number): Array<number | null> {
  return bars.map((_, i) => i + 1 < period ? null : bars.slice(i + 1 - period, i + 1).reduce((sum, bar) => sum + bar.close, 0) / period)
}

/** Capture the same unrounded plotted values, including volume averages and the analysis MACD. */
export function freezeChartIndicators(bars: Bar[], periods: number[], enabled: number[], indicators: Array<{type:string; params:IndicatorParams; rows:Array<Record<string, unknown>>}>): FrozenChartIndicators {
  const result: FrozenChartIndicators = {
    schema:1,source:'captured-chart-series',dates:bars.map(bar=>bar.datetime),
    averages:periods.map(period=>({period,enabled:enabled.includes(period),values:chartMovingAverage(bars,period)})),
    indicators:indicators.map(item=>{
      const definition=getIndicatorDefinition(item.type)
      return {type:item.type,params:{...item.params},label:definition.label,placement:definition.placement,
        ...(definition.bounds?{bounds:[...definition.bounds] as [number,number]}:{}),guideLines:[...(definition.guideLines??[])],
        series:buildIndicatorSeries(item.type,bars,item.rows).map((series,index)=>{
          const style=series.lineStyle as {color?:string}|undefined
          return {name:String(series.name),type:series.type as 'line'|'bar',symbol:series.symbol==='circle'?'circle':'none',
            color:style?.color??INDICATOR_LINE_COLORS[index%INDICATOR_LINE_COLORS.length]!,
            values:(series.data as Array<number|null|{value:number}>).map(value=>value===null?null:typeof value==='number'?value:value.value)}
        })}
    }),
  }
  validateFrozenChartIndicators(result,bars)
  return result
}

/** Only admit bounded, declarative values; never pass arbitrary saved ECharts options/callbacks. */
export function validateFrozenChartIndicators(value: unknown, bars: Bar[]): FrozenChartIndicators {
  const fail=():never=>{throw Error('冻结指标不完整或与行情不匹配；未重算或截断原记录')}
  const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
  const numeric=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
  const values=(v:unknown)=>Array.isArray(v)&&v.length===bars.length&&v.every(n=>n===null||numeric(n))
  if(!object(value)||value.schema!==1||value.source!=='captured-chart-series'||!Array.isArray(value.dates)
    ||value.dates.length!==bars.length||!value.dates.every((date,i)=>date===bars[i]?.datetime)
    ||!Array.isArray(value.averages)||value.averages.length>30||!Array.isArray(value.indicators)||value.indicators.length>8)return fail()
  const periods=new Set<number>()
  for(const ma of value.averages){
    if(!object(ma)||!numeric(ma.period)||!Number.isInteger(ma.period)||ma.period<1||ma.period>8000||periods.has(ma.period)
      ||typeof ma.enabled!=='boolean'||!values(ma.values))return fail()
    periods.add(ma.period)
  }
  for(const item of value.indicators){
    if(!object(item)||typeof item.type!=='string'||typeof item.label!=='string'||item.label.length>120
      ||!['none','panel','overlay'].includes(String(item.placement))||!object(item.params)||!Object.values(item.params).every(numeric)
      ||!Array.isArray(item.guideLines)||item.guideLines.length>20||!item.guideLines.every(numeric)
      ||(item.bounds!==undefined&&(!Array.isArray(item.bounds)||item.bounds.length!==2||!item.bounds.every(numeric)||item.bounds[0]>=item.bounds[1]))
      ||!Array.isArray(item.series)||item.series.length>20)return fail()
    const names=new Set<string>()
    for(const series of item.series){
      if(!object(series)||typeof series.name!=='string'||!series.name||series.name.length>120||names.has(series.name)
        ||!['line','bar'].includes(String(series.type))||!['none','circle'].includes(String(series.symbol))
        ||typeof series.color!=='string'||!/^#[\da-f]{3,8}$/i.test(series.color)||!values(series.values))return fail()
      names.add(series.name)
    }
  }
  return value as unknown as FrozenChartIndicators
}

export function frozenIndicatorSeries(item:FrozenIndicator,bars:Bar[]):Array<Record<string,unknown>> {
  return item.series.map((series,index)=>({
    name:series.name,type:series.type,symbol:series.symbol,symbolSize:series.symbol==='circle'?4:undefined,
    data:series.type==='line'?[...series.values]:series.values.map((value,i)=>value===null?null:provisionalColumn(value,bars[i]?.is_closed,item.type==='volume'?bars[i]!.close>=bars[i]!.open:value>=0)),
    connectNulls:false,barMaxWidth:item.type==='volume'?8:7,
    lineStyle:{color:series.color,width:item.placement==='overlay'?1.2:1.35,opacity:item.placement==='overlay'?.88:1},
    itemStyle:series.type==='line'?{color:series.color}:{color:(p:{dataIndex:number;value:number})=>(item.type==='volume'?bars[p.dataIndex]!.close>=bars[p.dataIndex]!.open:p.value>=0)?'rgba(255,94,104,.62)':'rgba(48,209,123,.62)',borderRadius:1},
    ...(index===0&&item.guideLines.length?{markLine:{silent:true,symbol:'none',label:{show:false},lineStyle:{color:'rgba(255,255,255,.11)',type:'dashed'},data:item.guideLines.map(yAxis=>({yAxis}))}}:{}),
  }))
}

export function frozenAverageSeries(snapshot:FrozenChartIndicators):Array<Record<string,unknown>> {
  return snapshot.averages.map(ma=>({name:`MA${ma.period}`,type:'line',showSymbol:false,connectNulls:false,data:[...ma.values],lineStyle:{width:1.2,color:movingAverageColor(ma.period)},itemStyle:{color:movingAverageColor(ma.period)}}))
}
