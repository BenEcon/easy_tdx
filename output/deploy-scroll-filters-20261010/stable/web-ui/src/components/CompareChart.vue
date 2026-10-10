<script setup lang="ts">
// 多 task 净值叠加对比图（归一化为初始=1）。

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts from '../echarts-setup'
import { useChartResize } from '../chart-resize'
import { fmt2 } from '../format'
import type { BacktestResult } from '../types'

const props = defineProps<{
  items: Array<{ label: string; result: BacktestResult }>
}>()

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function render() {
  if (!container.value || props.items.length === 0) return
  chart ??= echarts.init(container.value, 'dark')
  chart.setOption(buildOption(), true)
}

function buildOption(): echarts.EChartsCoreOption {
  const seriesData = props.items.map((item) => {
    const ec = item.result.equity_curve
    const initial = ec[0]?.total || 1
    return {
      name: item.label,
      dates: ec.map((e) => e.datetime.slice(0, 10)),
      values: ec.map((e) => e.total / initial),
    }
  })

  const allDates = Array.from(new Set(seriesData.flatMap((s) => s.dates))).sort()

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number | string) => fmt2(Number(v)),
    },
    legend: { type: 'scroll', top: 0, left: 8, right: 8, data: seriesData.map((s) => s.name), formatter: (name: string) => name.length > 18 ? `${name.slice(0, 18)}…` : name },
    grid: { left: 8, right: 12, top: 55, bottom: 35, outerBoundsMode: 'same', outerBoundsContain: 'axisLabel' },
    xAxis: {
      type: 'category',
      data: allDates,
      boundaryGap: false,
      axisLabel: { formatter: (v: string) => v },
    },
    yAxis: {
      type: 'value',
      scale: true,
      name: '归一化净值',
      axisLabel: { formatter: (v: number) => fmt2(v) },
    },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    series: seriesData.map((s) => {
      const valMap = new Map(s.dates.map((d, i) => [d, s.values[i]]))
      let last = 1
      const aligned = allDates.map((d) => {
        const v = valMap.get(d)
        if (v !== undefined) last = v
        return last
      })
      return {
        name: s.name,
        type: 'line',
        data: aligned,
        symbol: 'none',
        lineStyle: { width: 1.5 },
      }
    }),
  }
}

function resize() {
  chart?.resize()
}
onMounted(() => {
  render()
})
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
useChartResize(container, resize)
watch(() => props.items, render)
</script>

<template>
  <div ref="container" class="compare-chart"></div>
</template>

<style scoped>
.compare-chart {
  width: 100%;
  height: 380px;
}
</style>
