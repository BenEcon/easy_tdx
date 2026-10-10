import {factorValue} from './factor-research.ts'
import {factorAxisValue} from './factor-axis.ts'

export interface FactorChartSeries {name:string;values:Array<number|null>}
export interface FactorChartSettings {bar?:boolean;percent?:boolean;correlation?:boolean;precision?:'auto'|'raw'}

/** Display-only options: never normalize, round, interpolate or alter saved values. */
export function factorChartOptions(labels:string[],series:FactorChartSeries[],settings:FactorChartSettings={}) {
  const percent=settings.percent===true
  return {
    animation:false,
    tooltip:{trigger:'axis',renderMode:'richText',valueFormatter:(v:unknown)=>factorValue(v,percent,settings.precision)},
    legend:{top:4},grid:{left:60,right:20,top:45,bottom:60},
    xAxis:{type:'category',data:labels,axisLabel:{hideOverlap:true,formatter:(value:string)=>value.replace('T',' ').replace(/ 00:00:00$/,'')}},
    yAxis:{type:'value',scale:!settings.correlation,
      ...(settings.correlation?{min:-1,max:1}:{}),
      axisLabel:{formatter:(v:number)=>factorAxisValue(v,percent)}},
    dataZoom:settings.bar?[]:[{type:'inside'},{type:'slider',height:16,bottom:8}],
    series:series.map((s,i)=>({name:s.name,type:settings.bar?'bar':'line',
      data:s.values.map(v=>typeof v==='number'&&Number.isFinite(v)?v:null),
      connectNulls:false,showSymbol:false,barMaxWidth:45,lineStyle:{width:1.5},
      itemStyle:{color:['#66afff','#baa4ed','#6ecbb4','#d6b473'][i%4]}})),
  }
}
