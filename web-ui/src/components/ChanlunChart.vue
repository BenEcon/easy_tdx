<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts, { DOWN_COLOR, UP_COLOR } from '../echarts-setup'
import {
  buildIndicatorSeries,
  calculateIndicatorRows,
  compactNumber,
  getIndicatorDefinition,
  indicatorUsesPanel,
  percentageChange,
  type IndicatorParams,
  type TechnicalIndicator,
} from '../technical-indicators'
import type { Bar, ChanlunResult } from '../types'
import TechnicalIndicatorPicker from './TechnicalIndicatorPicker.vue'

const props = defineProps<{
  bars: Bar[]
  result: ChanlunResult
  layers: {
    bis: boolean
    zss: boolean
    xds: boolean
    mmds: boolean
    bcs: boolean
  }
}>()

const container = ref<HTMLDivElement>()
const selectedIndicator = ref<TechnicalIndicator>('macd')
const indicatorParams = ref<IndicatorParams>(getIndicatorDefinition('macd').defaultParams)
const indicatorRows = ref<Array<Record<string, unknown>>>([])
const indicatorLoading = ref(false)
const indicatorError = ref('')
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

function normalizedDate(value: string): string {
  return value.replace('T', ' ').slice(0, 16).replace(/ 00:00$/, '')
}

function price2(value: unknown): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '—'
}

function signalName(type: string): string {
  const names: Record<string, string> = {
    '1buy': '一类买点',
    '2buy': '二类买点',
    '3buy': '三类买点',
    '1sell': '一类卖点',
    '2sell': '二类卖点',
    '3sell': '三类卖点',
  }
  return names[type] ?? type
}

function buildOption(): echarts.EChartsCoreOption {
  const intraday = props.bars.some((bar) => bar.datetime.slice(11, 19) !== '00:00:00')
  const dates = props.bars.map((bar) => {
    const normalized = normalizedDate(bar.datetime)
    return intraday ? normalized : normalized.slice(0, 10)
  })
  const ohlc = props.bars.map((bar) => [bar.open, bar.close, bar.low, bar.high])
  const hasIndicator = indicatorUsesPanel(selectedIndicator.value)
  const indicatorDefinition = getIndicatorDefinition(selectedIndicator.value)

  const resolveDate = (raw: string | null): string | null => {
    if (!raw) return null
    const normalized = normalizedDate(raw)
    const exact = dates.find((date) => date === normalized)
    if (exact) return exact
    return dates.find((date) => date.startsWith(normalized.slice(0, 10))) ?? null
  }

  const barAt = (raw: string | null): Bar | null => {
    const label = resolveDate(raw)
    if (!label) return null
    const index = dates.indexOf(label)
    return index >= 0 ? props.bars[index] : null
  }

  const biPoints: Array<[string, number]> = []
  if (props.layers.bis) {
    for (const bi of props.result.bis) {
      const start = resolveDate(bi.start_date)
      const end = resolveDate(bi.end_date)
      if (!start || !end) continue
      const startValue = bi.start_value ?? (bi.direction === 'up' ? bi.low : bi.high)
      const endValue = bi.end_value ?? (bi.direction === 'up' ? bi.high : bi.low)
      if (biPoints[biPoints.length - 1]?.[0] !== start) biPoints.push([start, startValue])
      biPoints.push([end, endValue])
    }
  }

  const xdSegments: Array<{
    index: number
    direction: 'up' | 'down'
    points: Array<[string, number]>
  }> = []
  if (props.layers.xds) {
    for (const xd of props.result.xds) {
      const start = resolveDate(xd.start_date)
      const end = resolveDate(xd.end_date)
      if (!start || !end) continue
      const startValue = xd.start_value ?? (xd.direction === 'up' ? xd.low : xd.high)
      const endValue = xd.end_value ?? (xd.direction === 'up' ? xd.high : xd.low)
      xdSegments.push({
        index: xd.index,
        direction: xd.direction,
        points: [[start, startValue], [end, endValue]],
      })
    }
  }

  const centerAreas = props.layers.zss
    ? props.result.zss.flatMap((zs) => {
        const start = resolveDate(zs.start_date)
        const end = resolveDate(zs.end_date)
        if (!start || !end) return []
        return [[
          { name: `中枢 ${zs.index + 1}`, xAxis: start, yAxis: zs.zd },
          { xAxis: end, yAxis: zs.zg },
        ]]
      })
    : []

  const signalPoints = props.layers.mmds
    ? props.result.mmds.flatMap((signal) => {
        const date = resolveDate(signal.date)
        const bar = barAt(signal.date)
        if (!date || !bar) return []
        const isBuy = signal.type.includes('buy')
        return [{
          name: signalName(signal.type),
          value: `${isBuy ? 'B' : 'S'}${signal.type.slice(0, 1)}`,
          signalType: signal.type,
          message: signal.msg,
          date,
          price: isBuy ? bar.low : bar.high,
          coord: [date, isBuy ? bar.low : bar.high],
          symbol: 'roundRect',
          symbolSize: [18, 13],
          symbolOffset: [0, isBuy ? 12 : -12],
          itemStyle: {
            color: isBuy ? 'rgba(255, 73, 86, 0.94)' : 'rgba(28, 187, 107, 0.94)',
            borderColor: isBuy ? '#ff9ca3' : '#87e8b7',
            borderWidth: 1,
            shadowBlur: 3,
            shadowColor: isBuy ? 'rgba(255,73,86,.18)' : 'rgba(28,187,107,.16)',
          },
          label: {
            show: true,
            formatter: `${isBuy ? 'B' : 'S'}${signal.type.slice(0, 1)}`,
            position: 'inside',
            color: '#fff',
            fontSize: 7,
            fontWeight: 700,
          },
        }]
      })
    : []

  const divergencePoints = props.layers.bcs
    ? props.result.bcs.filter((item) => item.bc).flatMap((item) => {
        const date = resolveDate(item.curr_date)
        const bar = barAt(item.curr_date)
        if (!date || !bar) return []
        return [{
          name: '背驰',
          value: item.type.toUpperCase(),
          date,
          price: bar.close,
          message: item.msg,
          coord: [date, bar.close],
          symbol: 'diamond',
          symbolSize: 9,
          itemStyle: {
            color: 'rgba(191,90,242,.26)',
            borderColor: '#d9a3ff',
            borderWidth: 1.5,
            shadowBlur: 3,
            shadowColor: 'rgba(191,90,242,.2)',
          },
          label: { show: false },
        }]
      })
    : []

  const series: Array<Record<string, unknown>> = [
    {
      name: 'K 线',
      type: 'candlestick',
      data: ohlc,
      itemStyle: {
        color: UP_COLOR,
        color0: DOWN_COLOR,
        borderColor: '#ff8a92',
        borderColor0: '#6ee0a5',
        borderWidth: 1,
      },
      emphasis: {
        itemStyle: {
          borderWidth: 2,
          shadowBlur: 8,
          shadowColor: 'rgba(0,0,0,.38)',
        },
      },
      barMaxWidth: 12,
      barMinWidth: 2,
      markArea: {
        silent: true,
        data: centerAreas,
        itemStyle: { color: 'rgba(10, 132, 255, 0.075)', borderColor: 'rgba(74, 158, 255, 0.42)', borderWidth: 1 },
        label: {
          color: '#78b8ff',
          fontSize: 9,
          position: 'insideTopLeft',
          padding: [2, 4],
          backgroundColor: 'rgba(10,132,255,.12)',
          borderRadius: 3,
        },
      },
      markPoint: {
        data: [...signalPoints, ...divergencePoints],
        tooltip: {
          formatter: (params: { data?: { name?: string; date?: string; price?: number; message?: string } }) => {
            const data = params.data
            if (!data) return ''
            return [
              `<strong style="color:#f5f5f7">${data.name ?? ''}</strong>`,
              `<div style="margin-top:5px;color:#a6a6ad">${data.date ?? ''} · ${price2(data.price)}</div>`,
              data.message ? `<div style="margin-top:5px;color:#7f818a">${data.message}</div>` : '',
            ].join('')
          },
        },
      },
    },
  ]

  if (biPoints.length) {
    series.push({
      name: '笔',
      type: 'line',
      data: biPoints,
      showSymbol: true,
      symbol: 'circle',
      symbolSize: 3,
      connectNulls: false,
      lineStyle: { color: '#79b9ef', width: 1.35, opacity: 0.78 },
      itemStyle: { color: '#a6d4f8', borderColor: '#1a2630', borderWidth: 0.8 },
      emphasis: {
        focus: 'series',
        scale: 1.45,
        lineStyle: { color: '#9bcefa', width: 2, opacity: 1 },
      },
      z: 5,
    })
  }

  for (const segment of xdSegments) {
    series.push({
      name: '线段',
      type: 'line',
      data: segment.points,
      showSymbol: true,
      symbol: 'circle',
      symbolSize: 4,
      lineStyle: { color: '#a88cdb', width: 1.8, opacity: 0.84 },
      itemStyle: { color: '#c8b3ec', borderColor: '#251f31', borderWidth: 0.8 },
      emphasis: {
        focus: 'series',
        scale: 1.35,
        lineStyle: { color: '#c0a7eb', width: 2.6, opacity: 1 },
      },
      tooltip: {
        valueFormatter: (value: number | string) => price2(value),
      },
      z: 6,
    })
  }

  const secondarySeries = buildIndicatorSeries(selectedIndicator.value, props.bars, indicatorRows.value)
  series.push(...secondarySeries)

  return {
    backgroundColor: 'transparent',
    animationDuration: 420,
    animationEasing: 'cubicOut',
    tooltip: {
      trigger: 'axis',
      confine: true,
      padding: [10, 12],
      axisPointer: {
        type: 'cross',
        link: [{ xAxisIndex: 'all' }],
        lineStyle: { color: 'rgba(255,255,255,.22)', type: 'dashed', width: 1 },
        crossStyle: { color: 'rgba(255,255,255,.22)', type: 'dashed' },
        label: { backgroundColor: '#34363e', borderRadius: 4, color: '#d7d7dc' },
      },
      formatter: (rawParams: unknown) => {
        const params = (Array.isArray(rawParams) ? rawParams : [rawParams]) as Array<{
          seriesType?: string
          seriesName?: string
          axisValueLabel?: string
          dataIndex?: number
          data?: unknown
          value?: unknown
        }>
        const candle = params.find((item) => item.seriesType === 'candlestick')
        const index = candle?.dataIndex ?? -1
        const bar = props.bars[index]
        if (!bar) return candle?.axisValueLabel ?? ''
        const change = percentageChange(props.bars, index)
        const changeColor = (change ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR
        const details = params
          .filter((item) => item.seriesType !== 'candlestick' && secondarySeries.some((seriesItem) => seriesItem.name === item.seriesName))
          .map((item) => {
            const raw = Array.isArray(item.value) ? item.value[item.value.length - 1] : item.value
            const value = Number(raw)
            if (!Number.isFinite(value)) return ''
            return `<span>${item.seriesName}<b style="float:right;color:#c8c8cd">${selectedIndicator.value === 'volume' ? compactNumber(value) : price2(value)}</b></span>`
          }).join('')
        return `
          <div style="min-width:190px">
            <div style="color:#f5f5f7;font-weight:650;margin-bottom:8px">${candle?.axisValueLabel ?? ''}</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;color:#8e9099">
              <span>开 <b style="float:right;color:#d8d8de">${price2(bar.open)}</b></span>
              <span>高 <b style="float:right;color:#d8d8de">${price2(bar.high)}</b></span>
              <span>收 <b style="float:right;color:#d8d8de">${price2(bar.close)}</b></span>
              <span>低 <b style="float:right;color:#d8d8de">${price2(bar.low)}</b></span>
            </div>
            <div style="margin-top:8px;padding-top:7px;border-top:1px solid rgba(255,255,255,.08);color:#8e9099">
              涨跌幅 <b style="float:right;color:${changeColor}">${change === null ? '—' : `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}</b>
            </div>
            ${details ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:5px 14px;margin-top:7px;color:#777982">${details}</div>` : ''}
          </div>`
      },
    },
    legend: {
      top: 0,
      right: 6,
      show: secondarySeries.length > 0,
      data: secondarySeries.map((item) => String(item.name)),
      itemWidth: 14,
      itemHeight: 7,
      icon: 'roundRect',
      textStyle: { color: '#777982', fontSize: 10 },
    },
    grid: hasIndicator
      ? [{ left: 58, right: 28, top: 42, height: '54%' }, { left: 58, right: 28, top: '68%', height: '19%' }]
      : [{ left: 58, right: 28, top: 42, bottom: 62 }],
    xAxis: [
      {
        type: 'category', data: dates, boundaryGap: true, axisLine: { onZero: false },
        axisLabel: {
          show: !hasIndicator,
          formatter: (value: string) => intraday ? value.slice(5) : value.slice(2),
          hideOverlap: true,
        },
      },
      ...(hasIndicator ? [{
        type: 'category', gridIndex: 1, data: dates, boundaryGap: true,
        axisLine: { onZero: false }, axisTick: { show: false },
        axisLabel: {
          formatter: (value: string) => intraday ? value.slice(5) : value.slice(2),
          hideOverlap: true,
        },
      }] : []),
    ],
    yAxis: [
      {
        scale: true, splitNumber: 5, axisLabel: { formatter: (value: number) => value.toFixed(2) },
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,.052)', type: 'dashed' } },
      },
      ...(hasIndicator ? [{
        type: 'value', gridIndex: 1,
        scale: !indicatorDefinition.bounds,
        min: indicatorDefinition.bounds?.[0],
        max: indicatorDefinition.bounds?.[1],
        splitNumber: 3, axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,.045)', type: 'dashed' } },
        axisLabel: { formatter: (value: number) => selectedIndicator.value === 'volume' ? compactNumber(value) : price2(value) },
      }] : []),
    ],
    dataZoom: [
      {
        type: 'inside', xAxisIndex: hasIndicator ? [0, 1] : [0],
        start: Math.max(0, 100 - Math.min(100, 12000 / Math.max(dates.length, 1))), end: 100,
      },
      {
        type: 'slider',
        xAxisIndex: hasIndicator ? [0, 1] : [0],
        height: 20,
        bottom: 15,
        borderColor: 'transparent',
        backgroundColor: 'rgba(255,255,255,.025)',
        fillerColor: 'rgba(74,158,255,.12)',
        dataBackground: {
          lineStyle: { color: 'rgba(150,154,165,.38)' },
          areaStyle: { color: 'rgba(120,124,136,.12)' },
        },
        selectedDataBackground: {
          lineStyle: { color: '#5ba7ff' },
          areaStyle: { color: 'rgba(74,158,255,.18)' },
        },
        handleStyle: { color: '#218bfa', borderColor: '#82bfff' },
        textStyle: { color: '#686a73' },
      },
    ],
    series: series as never,
  }
}

function render() {
  if (!container.value || !props.bars.length) return
  chart ??= echarts.init(container.value, 'dark')
  chart.setOption(buildOption(), true)
  requestAnimationFrame(() => chart?.resize())
}

let indicatorRequest = 0
async function refreshIndicator() {
  const requestId = ++indicatorRequest
  indicatorError.value = ''
  const definition = getIndicatorDefinition(selectedIndicator.value)
  if (!props.bars.length || definition.code === 'NONE' || definition.code === 'VOLUME') {
    indicatorRows.value = []
    render()
    return
  }
  indicatorLoading.value = true
  try {
    const rows = await calculateIndicatorRows(props.bars, selectedIndicator.value, indicatorParams.value)
    if (requestId === indicatorRequest) indicatorRows.value = rows
  } catch (error) {
    if (requestId === indicatorRequest) {
      indicatorRows.value = []
      indicatorError.value = error instanceof Error ? error.message : '指标计算失败'
    }
  } finally {
    if (requestId === indicatorRequest) {
      indicatorLoading.value = false
      render()
    }
  }
}

onMounted(() => {
  render()
  void refreshIndicator()
  if (container.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(container.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})

watch(() => [props.result, props.layers], render, { deep: true })
watch(() => [props.bars, selectedIndicator.value, indicatorParams.value], () => void refreshIndicator(), { deep: true })
</script>

<template>
  <div class="market-chart-shell">
    <div
      ref="container"
      class="chanlun-chart"
      :class="{ 'has-indicator': indicatorUsesPanel(selectedIndicator) }"
    ></div>
    <TechnicalIndicatorPicker
      v-model="selectedIndicator"
      v-model:params="indicatorParams"
      :loading="indicatorLoading"
      :error="indicatorError"
    />
  </div>
</template>

<style scoped>
.market-chart-shell {
  width: 100%;
}
.chanlun-chart {
  width: 100%;
  height: 470px;
  transition: height 220ms ease;
}
.chanlun-chart.has-indicator { height: 585px; }
:global(.chart-frame:fullscreen) .chanlun-chart,
:global(.chart-frame.fallback-expanded) .chanlun-chart {
  height: calc(100vh - 122px);
  min-height: 600px;
}
</style>
