<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts, { UP_COLOR } from '../echarts-setup'

type Row = Record<string, unknown>

const props = defineProps<{ rows: Row[] }>()
const el = ref<HTMLDivElement | null>(null)
let chart: ReturnType<typeof echarts.init> | null = null
let observer: ResizeObserver | null = null

function minuteLabel(index: number): string {
  const minutes = index < 120 ? 9 * 60 + 30 + index : 13 * 60 + index - 120
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}

const labels = computed(() => props.rows.map((_, index) => minuteLabel(index)))

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value, 'dark')
  const prices = props.rows.map((row) => Number(row.price) || null)
  const volumes = props.rows.map((row) => Number(row.vol) || 0)
  const validPrices = prices.filter((value): value is number => value !== null)
  const baseline = validPrices.length ? validPrices[0] : 0
  chart.setOption({
    animationDuration: 420,
    grid: [
      { left: 58, right: 20, top: 22, height: '62%' },
      { left: 58, right: 20, top: '76%', height: '15%' },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255,255,255,.24)' } },
      formatter: (items: Array<{ axisValue: string; seriesName: string; value: number }>) => {
        const price = items.find((item) => item.seriesName === '价格')?.value
        const vol = items.find((item) => item.seriesName === '成交量')?.value
        const change = baseline && price ? ((price / baseline) - 1) * 100 : 0
        return `<strong>${items[0]?.axisValue ?? ''}</strong><br/>价格 ${Number(price).toFixed(2)} <span style="color:${change >= 0 ? '#ff5e68' : '#30d17b'}">${change >= 0 ? '+' : ''}${change.toFixed(2)}%</span><br/>成交量 ${Number(vol).toLocaleString('zh-CN')}`
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: [
      { type: 'category', data: labels.value, boundaryGap: false, axisLabel: { interval: 29 }, axisTick: { show: false } },
      { type: 'category', gridIndex: 1, data: labels.value, boundaryGap: true, axisLabel: { show: false }, axisTick: { show: false } },
    ],
    yAxis: [
      { type: 'value', scale: true, axisLabel: { formatter: (value: number) => value.toFixed(2) } },
      { type: 'value', gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    series: [
      {
        name: '价格', type: 'line', data: prices, showSymbol: false, smooth: 0.12,
        lineStyle: { width: 1.65, color: '#54a8ff' },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
          { offset: 0, color: 'rgba(10,132,255,.24)' }, { offset: 1, color: 'rgba(10,132,255,0)' },
        ] } },
        markLine: baseline ? { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: 'rgba(255,255,255,.16)', type: 'dashed' }, data: [{ yAxis: baseline }] } : undefined,
      },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes, itemStyle: { color: UP_COLOR, opacity: 0.42 }, barMaxWidth: 4 },
    ],
  }, true)
}

watch(() => props.rows, render, { deep: true })
onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart?.resize())
  if (el.value) observer.observe(el.value)
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose(); chart = null })
</script>

<template><div ref="el" class="intraday-chart"></div></template>

<style scoped>
.intraday-chart{width:100%;height:100%;min-height:330px}
</style>
