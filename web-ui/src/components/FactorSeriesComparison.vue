<script setup lang="ts">
import {computed,nextTick,onMounted,onBeforeUnmount,ref,watch} from 'vue'
import echarts from '../echarts-setup'
import {useChartResize} from '../chart-resize'
import {factorSeriesOptions,reconcileTracks,MAX_FACTOR_TRACKS} from '../factor-series-chart'
import ChartFrame from './ChartFrame.vue'
const props=defineProps<{rows:Record<string,unknown>[];names:string[];labels:Record<string,string>;precision?:'auto'|'raw'}>()
const chosen=ref<string[]>([]),initialized=ref(false),el=ref<HTMLElement>(),chartError=ref('')
let chart:echarts.ECharts|null=null
watch(()=>props.names,(names)=>{
  if(!initialized.value&&names.length){chosen.value=names.slice(0,MAX_FACTOR_TRACKS);initialized.value=true}
  else chosen.value=reconcileTracks(chosen.value,names)
},{immediate:true})
const tracks=computed(()=>chosen.value.map(id=>({id,name:props.labels[id]??id,values:props.rows.map(row=>typeof row[id]==='number'?row[id] as number:null)})))
function toggle(id:string){chosen.value=chosen.value.includes(id)?chosen.value.filter(n=>n!==id):chosen.value.length<MAX_FACTOR_TRACKS?[...chosen.value,id]:chosen.value}
async function render(){
  await nextTick();chartError.value=''
  if(!el.value)return
  chart??=echarts.init(el.value,'dark')
  if(!tracks.value.length){chart.clear();return}
  try{chart.setOption(factorSeriesOptions(props.rows.map(r=>String(r.datetime)),tracks.value,props.precision),true);chart.resize()}
  catch(e){chart.clear();chartError.value=e instanceof Error?e.message:String(e)}
}
onMounted(render);watch(()=>[props.rows,tracks.value,props.precision],render,{deep:true})
useChartResize(el,()=>chart?.resize());onBeforeUnmount(()=>{chart?.dispose();chart=null})
</script>
<template><ChartFrame title="因子分轨对比" description="同一日期与缩放范围，各轨使用独立原值尺度；不标准化、不补缺口。">
  <div class="series-workspace">
  <fieldset class="track-options"><legend>显示曲线 · {{ chosen.length }}/{{ MAX_FACTOR_TRACKS }}</legend><label v-for="name in names" :key="name"><input type="checkbox" :checked="chosen.includes(name)" :disabled="!chosen.includes(name)&&chosen.length>=MAX_FACTOR_TRACKS" @change="toggle(name)">{{ labels[name]??name }}</label></fieldset>
  <p v-if="chartError" role="alert">{{ chartError }}</p><p v-else-if="!chosen.length" role="status">请选择至少一个因子；可同时对比四个，其余数值仍保留在完整明细与导出中。</p>
  <div ref="el" class="factor-tracks" :style="{height:`${Math.max(1,chosen.length)*155+95}px`}" role="img" aria-label="原始因子分轨图，共用日期与缩放；对应数值见完整序列表" />
  </div>
</ChartFrame></template>
<style scoped>.series-workspace{width:100%;min-width:0;min-height:0;flex:1;overflow:auto}</style>
<style scoped>.track-options{border:0;border-bottom:1px solid var(--border);margin:0 0 10px;padding:0 0 12px;display:flex;gap:8px 16px;flex-wrap:wrap;min-width:0}.track-options legend{font-size:11px;color:var(--text-muted);margin-bottom:10px}.track-options label{display:flex;align-items:center;gap:6px;font-size:11px;min-height:28px;overflow-wrap:anywhere}.track-options input{width:14px;height:14px;min-height:0;margin:0;accent-color:var(--accent)}.factor-tracks{width:100%;min-width:0}p{font-size:12px;color:var(--text-muted);line-height:1.8}:deep(.chart-frame-content){display:block}@media(max-width:600px){.track-options{gap:6px 12px}.track-options label{max-width:100%}}</style>
