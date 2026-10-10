<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,watch} from 'vue'
import echarts from '../echarts-setup'
import {useChartResize} from '../chart-resize'
import {factorChartOptions,type FactorChartSeries} from '../factor-chart'
const props=defineProps<{labels:string[];series:FactorChartSeries[];bar?:boolean;percent?:boolean;correlation?:boolean;precision?:'auto'|'raw'}>()
const el=ref<HTMLElement>()
let chart:echarts.ECharts|null=null
function render(){
  if(!el.value)return
  chart??=echarts.init(el.value,'dark')
  chart.setOption(factorChartOptions(props.labels,props.series,props),true)
}
onMounted(render);watch(()=>[props.labels,props.series,props.bar,props.percent,props.correlation,props.precision],render,{deep:true});useChartResize(el,()=>chart?.resize());onBeforeUnmount(()=>chart?.dispose())
</script>
<template><div ref="el" class="factor-chart" role="img" aria-label="因子检验图；对应数值见下方明细表" /></template>
<style scoped>.factor-chart{width:100%;height:310px;min-width:0;flex:1}:fullscreen .factor-chart{height:70vh}.fallback-expanded .factor-chart{height:70vh}</style>
