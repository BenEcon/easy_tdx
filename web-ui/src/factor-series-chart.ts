import {factorValue} from './factor-research.ts'
import {factorAxisValue} from './factor-axis.ts'

export interface FactorTrack {id:string;name:string;values:Array<number|null>}
export const MAX_FACTOR_TRACKS=4
const colors=['#66afff','#baa4ed','#6ecbb4','#d6b473']
const dateLabel=(value:string)=>value.replace('T',' ').replace(/ 00:00:00$/,'')
const richText=(value:string)=>value.replace(/[{}\r\n]/g,' ')
export const factorTrackAxisValue=factorAxisValue
export function reconcileTracks(chosen:string[],available:string[]){return [...new Set(chosen)].filter(id=>available.includes(id)).slice(0,MAX_FACTOR_TRACKS)}
/** Display only: aligned dates, independent raw scales, no interpolation or normalization. */
export function factorSeriesOptions(labels:string[],tracks:FactorTrack[],precision:'auto'|'raw'='auto'){
  if(tracks.length<1||tracks.length>MAX_FACTOR_TRACKS||new Set(tracks.map(t=>t.id)).size!==tracks.length||tracks.some(t=>t.values.length!==labels.length))throw Error('对比曲线与日期不一致，或超过四个分轨')
  const count=tracks.length,step=82/count,gap=count>1?7:0,height=step-gap
  const indexes=tracks.map((_,i)=>i)
  return {
    animation:false,
    tooltip:{trigger:'axis',renderMode:'richText',confine:true,valueFormatter:(v:unknown)=>factorValue(v,false,precision),
      textStyle:{rich:Object.fromEntries(colors.map((color,i)=>[`s${i}`,{color}]))},
      formatter:(params:unknown)=>{
        const first=(Array.isArray(params)?params[0]:params) as {dataIndex?:number}|undefined,index=first?.dataIndex
        if(index===undefined||!Number.isInteger(index)||index<0||index>=labels.length)return ''
        return [richText(dateLabel(labels[index]!)),...tracks.map((t,i)=>`{s${i}|●} ${richText(t.name)}  ${factorValue(t.values[index],false,precision)}`)].join('\n')
      }},
    axisPointer:{link:[{xAxisIndex:'all'}]},
    grid:tracks.map((_,i)=>({left:66,right:22,top:`${7+i*step}%`,height:`${height}%`})),
    title:tracks.map((t,i)=>({text:t.name,left:66,top:`${1+i*step}%`,textStyle:{fontSize:11,fontWeight:500},padding:0})),
    xAxis:tracks.map((_,i)=>({type:'category',gridIndex:i,data:labels,boundaryGap:false,axisLabel:{show:i===count-1,hideOverlap:true,formatter:dateLabel},axisTick:{show:false},axisPointer:{show:true,label:{show:i===count-1}}})),
    yAxis:tracks.map((_,i)=>({type:'value',gridIndex:i,scale:true,splitNumber:3,axisLabel:{formatter:factorTrackAxisValue}})),
    dataZoom:[{type:'inside',xAxisIndex:indexes,filterMode:'none'},{type:'slider',xAxisIndex:indexes,filterMode:'none',height:16,bottom:6}],
    series:tracks.map((t,i)=>({id:t.id,name:t.name,type:'line',xAxisIndex:i,yAxisIndex:i,data:t.values.map(v=>typeof v==='number'&&Number.isFinite(v)?v:null),connectNulls:false,showSymbol:false,lineStyle:{width:1.5},itemStyle:{color:colors[i]}})),
  }
}
