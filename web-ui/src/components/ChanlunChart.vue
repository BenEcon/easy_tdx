<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

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
import { movingAverageColor } from '../moving-averages'
import { divergenceEvidence, divergenceName } from '../divergence-evidence'
import type { DivergenceFocus } from '../divergence-focus'
import { chartBarIndex, priceAxisPadding } from '../chart-position'
import { ChartViewportMemory } from '../chart-viewport'

const props = defineProps<{
  bars: Bar[]
  focus?: DivergenceFocus | null
  maPeriods?: number[]
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
const indicators = ref<Array<{ id: number; type: TechnicalIndicator; params: IndicatorParams; rows: Array<Record<string, unknown>> }>>([
  { id: 0, type: 'volume', params: { ...getIndicatorDefinition('volume').defaultParams }, rows: [] },
  { id: 1, type: 'macd', params: { ...getIndicatorDefinition('macd').defaultParams }, rows: [] },
])
let nextIndicatorId = indicators.value.length
const panels = computed(() => indicators.value.filter(item => indicatorUsesPanel(item.type)))
const chartHeight = computed(() => 470 + panels.value.length * 155)
function addIndicator() {
  const type = (['kdj', 'rsi', 'volume', 'boll'] as TechnicalIndicator[]).find(type => !indicators.value.some(item => item.type === type)) ?? 'macd'
  indicators.value.push({ id: nextIndicatorId++, type, params: { ...getIndicatorDefinition(type).defaultParams }, rows: [] })
}
const indicatorLoading = ref(false)
const indicatorError = ref('')
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null
const viewportMemory = new ChartViewportMemory()
let renderedBars: Bar[] | null = null
let renderedIdentity = ''
let viewportScope = {}

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
  const hasIndicator = panels.value.length > 0
  const axisIndices = Array.from({ length: panels.value.length + 1 }, (_, i) => i)

  const resolveDate = (raw: string | null): string | null => {
    const index = chartBarIndex(props.bars, raw)
    return index === null ? null : dates[index]!
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
    pending: boolean
    direction: 'up' | 'down'
    points: Array<[string, number]>
  }> = []
  if (props.layers.xds) {
    const lines = [...props.result.xds, ...(props.result.unfinished_xd ? [props.result.unfinished_xd] : [])]
    for (const xd of lines) {
      const start = resolveDate(xd.start_date)
      const end = resolveDate(xd.end_date)
      if (!start || !end) continue
      const startValue = xd.start_value ?? (xd.direction === 'up' ? xd.low : xd.high)
      const endValue = xd.end_value ?? (xd.direction === 'up' ? xd.high : xd.low)
      xdSegments.push({
        index: xd.index,
        pending: xd === props.result.unfinished_xd,
        direction: xd.direction,
        points: [[start, startValue], [end, endValue]],
      })
    }
  }

  const centerAreas = props.layers.zss
    ? (props.result.structural_centres ?? props.result.zss).flatMap((zs) => {
        const start = resolveDate(zs.start_date)
        const end = resolveDate(zs.end_date)
        if (!start || !end) return []
        return [[
          { name: `中枢 ${zs.index + 1}`, xAxis: start, yAxis: zs.zd },
          { xAxis: end, yAxis: zs.zg },
        ]]
      })
    : []

  const signalGroups = new Map<string, typeof props.result.mmds>()
  for (const signal of props.result.mmds) {
    const key = `${resolveDate(signal.date)}:${signal.type.includes('buy')}`
    signalGroups.set(key, [...(signalGroups.get(key) ?? []), signal])
  }
  const signalPoints = props.layers.mmds
    ? [...signalGroups.values()].flatMap((signals) => {
        const signal = signals[0]!
        const date = resolveDate(signal.date)
        const bar = barAt(signal.date)
        if (!date || !bar) return []
        const isBuy = signal.type.includes('buy')
        const label = `${isBuy ? 'B' : 'S'}${[...new Set(signals.map(item => item.type.slice(0, 1)))].sort().join('·')}`
        return [{
          name: signals.map(item => signalName(item.type)).join(' / '),
          value: label,
          signalType: signal.type,
          message: signals.map(item => `${item.msg}；确认：${item.confirmed_date ?? '尚未确认'}`).join('<br/>'),
          date,
          price: isBuy ? bar.low : bar.high,
          coord: [date, isBuy ? bar.low : bar.high],
          symbol: 'roundRect',
          symbolSize: [label.length > 2 ? 28 : 18, 13],
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
            formatter: label,
            position: 'inside',
            color: '#fff',
            fontSize: 7,
            fontWeight: 700,
          },
        }]
      })
    : []

  const divergencePoints = props.layers.bcs
    ? props.result.bcs.filter((item) => item.bc && item.status !== 'superseded').flatMap((item) => {
        const index = chartBarIndex(props.bars, item.curr_date, item.signal_index)
        if (index === null) return []
        const date = dates[index]!
        const bar = props.bars[index]!
        return [{
          name: divergenceName(item),
          value: item.type.toUpperCase(),
          date,
          price: item.direction === 'down' ? bar.low : bar.high,
          message: `${item.status === 'candidate' ? '候选 · 尚未确认' : '已确认（不保证反转）'}；对照：${item.prev_date ?? '—'}<br/>${divergenceEvidence(item).join('<br/>')}`,
          coord: [index, item.direction === 'down' ? bar.low : bar.high],
          symbolOffset: [0, item.direction === 'down' ? 23 : -23],
          symbol: 'diamond',
          symbolSize: 9,
          itemStyle: {
            color: item.status === 'candidate' ? 'transparent' : 'rgba(191,90,242,.7)',
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
          triggerOn: 'mousemove|click',
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

  if (props.focus) {
    // Independent overlays keep centre areas and indicator colors unchanged.
    for (const axis of axisIndices) {
      series.push({
        name: `核验区间 ${axis}`, type: 'line', xAxisIndex: axis, yAxisIndex: axis,
        data: [], silent: true, tooltip: { show: false },
        markLine: { silent: true, symbol: 'none',
          lineStyle: { color: 'rgba(116,184,255,.75)', width: 1, type: 'dashed' },
          label: { show: true, formatter: '{b}', color: '#b4d9ff', fontSize: 10, rotate: 0,
            position: axis ? 'insideEndTop' : 'end', distance: 6 },
          data: props.focus.points.map(point => ({name: point.label, xAxis: point.index})),
        },
        markArea: { silent: true, label: { show: true, color: '#b4d9ff', fontSize: axis ? 9 : 11,
          position: axis ? 'insideTop' : 'top', padding: axis ? [4, 0] : 0 },
          itemStyle: { color: 'rgba(74,158,255,.06)', borderColor: 'rgba(116,184,255,.65)', borderWidth: 1, borderType: 'dashed' },
          data: props.focus.ranges.map(range => [
            { name: props.focus?.scope === 'expansion' ? `重组 ${range.label}` : range.label, xAxis: range.start }, { xAxis: range.end },
          ]),
        },
      })
    }
  }

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
      name: segment.pending ? '候选线段（未确认）' : '线段',
      type: 'line',
      data: segment.points,
      showSymbol: true,
      symbol: 'circle',
      symbolSize: segment.pending ? 3 : 4,
      lineStyle: { color: '#a88cdb', width: 1.8, opacity: segment.pending ? 0.58 : 0.84, type: segment.pending ? 'dashed' : 'solid' },
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

  const legendLabels = new Map<string, string>()
  const tooltipLabels = new Map<string, string>()
  const secondarySeries = indicators.value.flatMap(item => {
    const axis = indicatorUsesPanel(item.type) ? panels.value.findIndex(panel => panel.id === item.id) + 1 : 0
    return buildIndicatorSeries(item.type, props.bars, item.rows).map(series => {
      const name = `indicator-${item.id}-${series.name}`
      legendLabels.set(name, String(series.name))
      tooltipLabels.set(name, `${getIndicatorDefinition(item.type).label} · ${series.name}`)
      return { ...series, name, xAxisIndex: axis, yAxisIndex: axis }
    })
  })
  const averages = [...new Set(props.maPeriods ?? [])].sort((a, b) => a - b).map(period => ({
    name: `MA${period}`, type: 'line', showSymbol: false, connectNulls: false,
    data: props.bars.map((_, i) => i + 1 < period ? null : props.bars.slice(i + 1 - period, i + 1).reduce((sum, bar) => sum + bar.close, 0) / period),
    lineStyle: { width: 1.2, color: movingAverageColor(period) },
    itemStyle: { color: movingAverageColor(period) },
  }))
  series.push(...averages, ...secondarySeries)
  if (props.focus) {
    for (const item of series) Object.assign(item, { animation: false, animationDuration: 0, animationDurationUpdate: 0 })
  }

  return {
    backgroundColor: 'transparent',
    animation: !props.focus,
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
        const index = candle?.dataIndex ?? params[0]?.dataIndex ?? -1
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
            return `<span>${tooltipLabels.get(item.seriesName ?? '') ?? item.seriesName}<b style="float:right;color:#c8c8cd">${price2(value)}</b></span>`
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
    legend: [
      {
        type: 'scroll', top: 0, right: 28,
        show: averages.length > 0,
        data: averages.map(item => item.name),
        itemWidth: 12, itemHeight: 3, itemGap: 12, icon: 'roundRect',
        textStyle: { color: '#9298a4', fontSize: 10 },
      },
      ...[0, ...panels.value.map((_, i) => i + 1)].map(axis => ({
        type: 'scroll',
        top: axis === 0 ? 22 : 396 + (axis - 1) * 155,
        right: 28,
        show: secondarySeries.some(item => item.xAxisIndex === axis),
        data: secondarySeries.filter(item => item.xAxisIndex === axis).map(item => item.name),
        formatter: (name: string) => legendLabels.get(name) ?? name,
        itemWidth: 12, itemHeight: 3, itemGap: 12, icon: 'roundRect',
        textStyle: { color: '#858b98', fontSize: 10 },
        pageIconColor: '#9298a4', pageIconInactiveColor: '#363943',
        pageTextStyle: { color: '#858b98' },
      })),
    ],
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 58, right: 28, top: 50, height: 342 },
      ...panels.value.map((_, i) => ({ left: 58, right: 28, top: 420 + i * 155, height: 115 })),
    ],
    xAxis: [
      {
        type: 'category', data: dates, boundaryGap: true, axisLine: { onZero: false },
        axisLabel: {
          show: !hasIndicator,
          formatter: (value: string) => intraday ? value.slice(5) : value.slice(2),
          hideOverlap: true,
        },
      },
      ...panels.value.map((_, i) => ({
        type: 'category', gridIndex: i + 1, data: dates, boundaryGap: true,
        axisLine: { onZero: false }, axisTick: { show: false },
        axisLabel: {
          show: i === panels.value.length - 1,
          formatter: (value: string) => intraday ? value.slice(5) : value.slice(2),
          hideOverlap: true,
        },
      })),
    ],
    yAxis: [
      {
        scale: true, splitNumber: 5, axisLabel: { formatter: (value: number) => value.toFixed(2) },
        min: (extent: {min: number; max: number}) => extent.min - priceAxisPadding(extent),
        max: (extent: {min: number; max: number}) => extent.max + priceAxisPadding(extent),
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,.052)', type: 'dashed' } },
      },
      ...panels.value.map((item, i) => ({
        type: 'value', gridIndex: i + 1,
        name: getIndicatorDefinition(item.type).label,
        nameTextStyle: { color: '#9298a4', fontSize: 10 },
        scale: !getIndicatorDefinition(item.type).bounds,
        min: getIndicatorDefinition(item.type).bounds?.[0],
        max: getIndicatorDefinition(item.type).bounds?.[1],
        splitNumber: 3, axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,.045)', type: 'dashed' } },
        axisLabel: { formatter: (value: number) => item.type === 'volume' ? compactNumber(value) : price2(value) },
      })),
    ],
    dataZoom: [
      {
        type: 'inside', xAxisIndex: axisIndices,
        ...(props.focus ? { startValue: props.focus.start, endValue: props.focus.end }
          : { start: Math.max(0, 100 - Math.min(100, 12000 / Math.max(dates.length, 1))), end: 100 }),
      },
      {
        type: 'slider',
        xAxisIndex: axisIndices,
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
  const current = (chart.getOption() ?? {}) as { dataZoom?: unknown[]; legend?: Array<{selected?: Record<string, boolean>}> }
  const identity = `${props.result.code}:${props.result.frequency}`
  const sameSnapshot = renderedBars === props.bars && renderedIdentity === identity
  if (!sameSnapshot) viewportScope = {}
  const zoom = viewportMemory.update(viewportScope, props.focus ?? null, current.dataZoom?.[0])
  const option = buildOption()
  if (zoom) {
    for (const axis of option.dataZoom as Array<Record<string, unknown>>) {
      delete axis.startValue
      delete axis.endValue
      Object.assign(axis, zoom)
    }
  }
  if (sameSnapshot) {
    const selected = Object.assign({}, ...((current.legend ?? []).map(legend => legend.selected ?? {})))
    for (const legend of option.legend as Array<Record<string, unknown>>) {
      legend.selected = selected
    }
  }
  renderedBars = props.bars
  renderedIdentity = identity
  if (props.focus) chart.clear()
  chart.setOption(option, true)
  requestAnimationFrame(() => chart?.resize())
}

let indicatorRequest = 0
async function refreshIndicator() {
  const requestId = ++indicatorRequest
  indicatorError.value = ''
  indicatorLoading.value = true
  try {
    await Promise.all(indicators.value.map(async item => {
      try {
        const rows = await calculateIndicatorRows(props.bars, item.type, item.params)
        if (requestId === indicatorRequest) item.rows = rows
      } catch (error) {
        if (requestId === indicatorRequest) {
          item.rows = []
          indicatorError.value += `${getIndicatorDefinition(item.type).label}：${error instanceof Error ? error.message : '计算失败'}；`
        }
      }
    }))
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

watch(() => [props.result, props.layers, props.maPeriods, props.focus], render, { deep: true })
watch(() => [props.bars, indicators.value.map(item => [item.id, item.type, item.params])], () => void refreshIndicator(), { deep: true })
</script>

<template>
  <div class="market-chart-shell">
    <div
      ref="container"
      class="chanlun-chart"
      :style="{ height: `${chartHeight}px`, minHeight: `${chartHeight}px` }"
    ></div>
    <div class="indicator-heading"><span>技术指标 · 可同时显示多个</span><button @click="addIndicator">＋ 添加指标</button></div>
    <div v-for="(item, index) in indicators" :key="item.id" class="indicator-entry">
    <button class="remove-indicator" :aria-label="`移除第 ${index + 1} 个指标`" @click="indicators.splice(index, 1)">移除</button>
    <TechnicalIndicatorPicker
      v-model="item.type"
      v-model:params="item.params"
      :loading="indicatorLoading"
    />
    </div>
    <p v-if="indicatorError" role="alert">{{ indicatorError }}</p>
  </div>
</template>

<style scoped>
.indicator-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 12px 0 4px; font-size: 11px; color: var(--text-muted); }
.indicator-heading button, .remove-indicator { padding: 5px 9px; font-size: 11px; border: 1px solid var(--border); border-radius: 7px; background: rgba(255,255,255,.03); color: var(--text-muted); cursor: pointer; }
.indicator-entry { position: relative; border-bottom: 1px solid var(--border); padding-right: 52px; }
.remove-indicator { position: absolute; right: 0; top: 13px; }
:global(.chart-frame:fullscreen) .market-chart-shell, :global(.chart-frame.fallback-expanded) .market-chart-shell { overflow-y: auto; }
:global(.chart-frame:fullscreen) .chanlun-chart, :global(.chart-frame.fallback-expanded) .chanlun-chart { flex: none !important; }
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
