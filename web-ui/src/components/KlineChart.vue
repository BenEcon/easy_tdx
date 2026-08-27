<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts, { DOWN_COLOR, UP_COLOR } from '../echarts-setup'
import { fmt2 } from '../format'
import {
  calculateKdj,
  calculateMacd,
  calculateRsi,
  compactNumber,
  percentageChange,
  type TechnicalIndicator,
} from '../technical-indicators'
import type { Bar, Trade } from '../types'
import TechnicalIndicatorPicker from './TechnicalIndicatorPicker.vue'

const props = defineProps<{ bars: Bar[]; trades: Trade[] }>()

const container = ref<HTMLDivElement>()
const selectedIndicator = ref<TechnicalIndicator>('macd')
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

function indicatorSeries(indicator: TechnicalIndicator): Array<Record<string, unknown>> {
  const shared = { xAxisIndex: 1, yAxisIndex: 1, symbol: 'none', animationDuration: 260 }
  if (indicator === 'volume') {
    return [{
      name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
      data: props.bars.map((bar) => bar.vol), barMaxWidth: 8,
      itemStyle: {
        color: (params: { dataIndex: number }) => props.bars[params.dataIndex].close >= props.bars[params.dataIndex].open
          ? 'rgba(255,94,104,.62)' : 'rgba(48,209,123,.62)',
        borderRadius: [2, 2, 0, 0],
      },
    }]
  }
  if (indicator === 'macd') {
    const macd = calculateMacd(props.bars)
    return [
      {
        name: 'MACD', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: macd.histogram, barMaxWidth: 7,
        itemStyle: {
          color: (params: { value: number }) => params.value >= 0 ? 'rgba(255,94,104,.62)' : 'rgba(48,209,123,.62)',
          borderRadius: 1,
        },
      },
      { ...shared, name: 'DIF', type: 'line', data: macd.dif, lineStyle: { color: '#56a8ff', width: 1.35 } },
      { ...shared, name: 'DEA', type: 'line', data: macd.dea, lineStyle: { color: '#f2c94c', width: 1.35 } },
    ]
  }
  if (indicator === 'kdj') {
    const kdj = calculateKdj(props.bars)
    return [
      { ...shared, name: 'K', type: 'line', data: kdj.k, lineStyle: { color: '#56a8ff', width: 1.3 } },
      { ...shared, name: 'D', type: 'line', data: kdj.d, lineStyle: { color: '#f2c94c', width: 1.3 } },
      { ...shared, name: 'J', type: 'line', data: kdj.j, lineStyle: { color: '#c488ff', width: 1.3 } },
    ]
  }
  if (indicator === 'rsi') {
    return [{
      ...shared, name: 'RSI(14)', type: 'line', data: calculateRsi(props.bars),
      lineStyle: { color: '#c488ff', width: 1.45 },
      markLine: {
        silent: true, symbol: 'none', label: { show: false },
        lineStyle: { color: 'rgba(255,255,255,.11)', type: 'dashed' },
        data: [{ yAxis: 30 }, { yAxis: 70 }],
      },
    }]
  }
  return []
}

function buildOption(): echarts.EChartsCoreOption {
  const keys = props.bars.map((bar) => bar.datetime)
  const keyIndex = new Map<string, number>()
  keys.forEach((key, index) => keyIndex.set(key, index))
  const isIntraday = keys.some((key) => key.slice(11, 19) && key.slice(11, 19) !== '00:00:00')
  const dates = keys.map((key) => (isIntraday ? key.replace('T', ' ').slice(5, 16) : key.slice(0, 10)))
  const ohlc = props.bars.map((bar) => [bar.open, bar.close, bar.low, bar.high])
  const hasIndicator = selectedIndicator.value !== 'none'
  const zoomStart = Math.max(0, 100 - Math.min(100, 18000 / Math.max(dates.length, 1)))

  const markPoints: Array<Record<string, unknown>> = []
  for (const trade of props.trades) {
    if (trade.rejected) continue
    const tradeKey = trade.datetime.slice(0, 19).replace(' ', 'T')
    let index = keyIndex.get(tradeKey)
    if (index === undefined) {
      index = keys.findIndex((key) => key.startsWith(tradeKey.slice(0, 10)))
      if (index === -1) continue
    }
    const isBuy = trade.direction === 'BUY'
    markPoints.push({
      name: isBuy ? '买入' : '卖出', value: isBuy ? 'B' : 'S', date: dates[index], price: trade.price,
      coord: [index, trade.price], symbol: 'roundRect', symbolSize: [20, 15],
      symbolOffset: [0, isBuy ? 13 : -13],
      itemStyle: {
        color: isBuy ? 'rgba(255,73,86,.94)' : 'rgba(28,187,107,.94)',
        borderColor: isBuy ? '#ff9ca3' : '#87e8b7', borderWidth: 1, shadowBlur: 5,
        shadowColor: isBuy ? 'rgba(255,73,86,.22)' : 'rgba(28,187,107,.20)',
      },
      label: { show: true, formatter: isBuy ? 'B' : 'S', color: '#fff', fontSize: 8, fontWeight: 700 },
    })
  }

  const secondarySeries = indicatorSeries(selectedIndicator.value)
  const xAxis = [
    {
      type: 'category', data: dates, boundaryGap: true, axisLine: { onZero: false }, splitLine: { show: false },
      axisLabel: { show: !hasIndicator, formatter: (value: string) => value, hideOverlap: true },
    },
    ...(hasIndicator ? [{
      type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLine: { onZero: false },
      axisTick: { show: false }, splitLine: { show: false },
      axisLabel: { formatter: (value: string) => value, hideOverlap: true },
    }] : []),
  ]
  const yAxis = [
    {
      scale: true, axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,.052)', type: 'dashed' } },
      axisLabel: { formatter: (value: number) => fmt2(value) },
    },
    ...(hasIndicator ? [{
      type: 'value', gridIndex: 1,
      scale: selectedIndicator.value !== 'kdj' && selectedIndicator.value !== 'rsi',
      min: selectedIndicator.value === 'rsi' ? 0 : undefined,
      max: selectedIndicator.value === 'rsi' ? 100 : undefined,
      splitNumber: 3, axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,.045)', type: 'dashed' } },
      axisLabel: { formatter: (value: number) => selectedIndicator.value === 'volume' ? compactNumber(value) : fmt2(value) },
    }] : []),
  ]

  return {
    backgroundColor: 'transparent', animationDuration: 360, animationEasing: 'cubicOut',
    tooltip: {
      trigger: 'axis', confine: true, padding: [10, 12],
      axisPointer: {
        type: 'cross', link: [{ xAxisIndex: 'all' }],
        lineStyle: { color: 'rgba(255,255,255,.22)', type: 'dashed' },
        crossStyle: { color: 'rgba(255,255,255,.22)', type: 'dashed' },
        label: { backgroundColor: '#34363e', borderRadius: 4 },
      },
      formatter: (rawParams: unknown) => {
        const params = (Array.isArray(rawParams) ? rawParams : [rawParams]) as Array<{
          seriesType?: string; seriesName?: string; axisValueLabel?: string; dataIndex?: number; value?: unknown
        }>
        const candle = params.find((item) => item.seriesType === 'candlestick')
        const index = candle?.dataIndex ?? -1
        const bar = props.bars[index]
        if (!bar) return candle?.axisValueLabel ?? ''
        const change = percentageChange(props.bars, index)
        const changeColor = (change ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR
        const details = params
          .filter((item) => item.seriesType !== 'candlestick' && item.seriesName && item.seriesName !== 'K 线')
          .map((item) => {
            const raw = Array.isArray(item.value) ? item.value[item.value.length - 1] : item.value
            const value = Number(raw)
            if (!Number.isFinite(value)) return ''
            return `<span>${item.seriesName}<b style="float:right;color:#c8c8cd">${selectedIndicator.value === 'volume' ? compactNumber(value) : fmt2(value)}</b></span>`
          }).join('')
        return `
          <div style="min-width:190px">
            <div style="color:#f5f5f7;font-weight:650;margin-bottom:8px">${candle?.axisValueLabel ?? dates[index]}</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;color:#8e9099">
              <span>开 <b style="float:right;color:#d8d8de">${fmt2(bar.open)}</b></span>
              <span>高 <b style="float:right;color:#d8d8de">${fmt2(bar.high)}</b></span>
              <span>收 <b style="float:right;color:#d8d8de">${fmt2(bar.close)}</b></span>
              <span>低 <b style="float:right;color:#d8d8de">${fmt2(bar.low)}</b></span>
            </div>
            <div style="margin-top:8px;padding-top:7px;border-top:1px solid rgba(255,255,255,.08);color:#8e9099">
              涨跌幅 <b style="float:right;color:${changeColor}">${change === null ? '—' : `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}</b>
            </div>
            ${details ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:5px 14px;margin-top:7px;color:#777982">${details}</div>` : ''}
          </div>`
      },
    },
    legend: {
      data: ['K 线', ...secondarySeries.map((item) => String(item.name))], top: 0, right: 6,
      itemWidth: 14, itemHeight: 7, icon: 'roundRect', textStyle: { color: '#777982', fontSize: 10 },
    },
    grid: hasIndicator
      ? [{ left: 58, right: 28, top: 34, height: '55%' }, { left: 58, right: 28, top: '68%', height: '19%' }]
      : [{ left: 58, right: 28, top: 34, bottom: 58 }],
    xAxis, yAxis,
    dataZoom: [
      { type: 'inside', xAxisIndex: hasIndicator ? [0, 1] : [0], start: zoomStart, end: 100 },
      {
        type: 'slider', xAxisIndex: hasIndicator ? [0, 1] : [0], height: 20, bottom: 8, start: zoomStart, end: 100,
        borderColor: 'transparent', backgroundColor: 'rgba(255,255,255,.025)', fillerColor: 'rgba(74,158,255,.12)',
        handleStyle: { color: '#218bfa', borderColor: '#82bfff' }, textStyle: { color: '#686a73' },
      },
    ],
    series: [
      {
        name: 'K 线', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0, data: ohlc,
        itemStyle: {
          color: UP_COLOR, color0: DOWN_COLOR, borderColor: '#ff8a92', borderColor0: '#6ee0a5', borderWidth: 1,
        },
        emphasis: { itemStyle: { borderWidth: 2, shadowBlur: 8, shadowColor: 'rgba(0,0,0,.38)' } },
        barMaxWidth: 12, barMinWidth: 2,
        labelLayout: { hideOverlap: true },
        markPoint: {
          data: markPoints,
          tooltip: {
            formatter: (params: { data?: { name?: string; date?: string; price?: number } }) => {
              const data = params.data
              return `<strong>${data?.name ?? ''}</strong><div style="margin-top:5px;color:#a6a6ad">${data?.date ?? ''} · ${fmt2(Number(data?.price))}</div>`
            },
          },
        },
      },
      ...secondarySeries,
    ] as never,
  }
}

function render() {
  if (!container.value || props.bars.length === 0) return
  chart ??= echarts.init(container.value, 'dark')
  chart.setOption(buildOption(), true)
  requestAnimationFrame(() => chart?.resize())
}

onMounted(() => {
  render()
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
watch(() => [props.bars, props.trades, selectedIndicator.value], render, { deep: true })
</script>

<template>
  <div class="market-chart-shell">
    <div ref="container" class="kline-chart" :class="{ 'has-indicator': selectedIndicator !== 'none' }"></div>
    <TechnicalIndicatorPicker v-model="selectedIndicator" />
  </div>
</template>

<style scoped>
.market-chart-shell { width: 100%; }
.kline-chart { width: 100%; height: 420px; transition: height 220ms ease; }
.kline-chart.has-indicator { height: 535px; }
:global(.chart-frame:fullscreen) .kline-chart,
:global(.chart-frame.fallback-expanded) .kline-chart { height: calc(100vh - 122px); min-height: 560px; }
</style>
