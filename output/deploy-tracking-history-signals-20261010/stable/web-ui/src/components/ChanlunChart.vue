<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts, { DOWN_COLOR, UP_COLOR } from '../echarts-setup'
import { clickTooltipOptions, installClickChartTooltip } from '../click-chart-tooltip'
import {
  buildIndicatorSeries,
  compactNumber,
  getIndicatorDefinition,
  percentageChange,
  type IndicatorParams,
  type TechnicalIndicator,
} from '../technical-indicators'
import type { Bar, ChanlunResult, ChanlunDivergence } from '../types'
import TechnicalIndicatorPicker from './TechnicalIndicatorPicker.vue'
import { movingAverageColor, movingAverageSelection } from '../moving-averages'
import { divergenceEvidence, divergenceName } from '../divergence-evidence'
import { divergenceMarker, macdPrompts, visibleDivergences } from '../divergence-marker'
import type { DivergenceFocus } from '../divergence-focus'
import { chartBarIndex, priceAxisPadding } from '../chart-position'
import { ChartViewportMemory } from '../chart-viewport'
import { useMobileViewport } from '../mobile-viewport'
import { provisionalCandle } from '../provisional-bars'
import { structureLineWidth, emphasizedLineWidth, type ChanlunLineWidths } from '../chanlun-line-width'
import { consolidationAppearance, nextPenPreview } from '../structure-preview'
import { candleFill } from '../candle-fill'
import { consolidationHits } from '../consolidation-hit'
import StructureInfoPopover from './StructureInfoPopover.vue'
import { signalName, structuralSignalDetail, macdSignalDetail, type ChartSignalDetail } from '../chart-signal-detail'
import { barWindow, overlappingBars, nearestMarkers, timeLinkGraphic, type PlotRect, type TimeWindow, type MarkerCandidate } from '../chart-research-link'
import { useResearchPreferences } from '../research-preferences'
import { researchIndicatorRows } from '../research-indicators'
import { chartMovingAverage, freezeChartIndicators, frozenAverageSeries, frozenIndicatorSeries, type FrozenChartIndicators } from '../frozen-chart-indicators'
import { synchronousChartMotion, synchronizeChartSeries } from '../chart-synchronous-motion'
import { escapeChartText } from '../chart-text'

const props = defineProps<{
  bars: Bar[]
  periodCategory?: string
  evidenceEnabled?: boolean
  focus?: DivergenceFocus | null
  showDivergenceHistory?: boolean
  maPeriods?: number[]
  maAvailablePeriods?: number[]
  lineWidths?: ChanlunLineWidths
  candleTransparency?: number
  linkedCursor?: TimeWindow | null
  linkedZoom?: TimeWindow | null
  indicatorConfig?: Array<{ type: string; params: IndicatorParams }>
  frozenIndicators?: FrozenChartIndicators
  readonlyArchive?: boolean
  result: ChanlunResult
  layers: {
    bis: boolean
    zss: boolean
    xds: boolean
    mmds: boolean
    bcs: boolean
    consolidations?: boolean
    nextPen?: boolean
  }
}>()
const emit = defineEmits<{ 'update:maPeriods': [periods: number[]]; cursor: [range: TimeWindow | null]; zoom: [range: TimeWindow]; viewport: [range: TimeWindow]; inspect: [date: string]; review: [date: string] }>()
const reviewDate = ref('')
const preferences = useResearchPreferences()
const objectHover = computed(() => preferences.settings.value.objectHover)
const linkedLabel = ref('')
const availableMA = computed(() => props.frozenIndicators?.averages.map(item=>item.period) ?? (props.readonlyArchive ? [] : [...new Set(props.maAvailablePeriods ?? props.maPeriods ?? [])].sort((a, b) => a - b)))
const frozenMASelection = ref<number[] | null>(null)
const enabledMA = computed(() => props.frozenIndicators ? frozenMASelection.value ?? props.frozenIndicators.averages.filter(item=>item.enabled).map(item=>item.period) : props.maPeriods ?? [])
const mobile = useMobileViewport()
function toggleMobileMA(period: number) {
  const selected = new Set(enabledMA.value)
  if (selected.has(period)) selected.delete(period)
  else selected.add(period)
  const periods=availableMA.value.filter(value => selected.has(value))
  if (props.frozenIndicators) { frozenMASelection.value=periods; scheduleRender() }
  else emit('update:maPeriods', periods)
}

const container = ref<HTMLDivElement>()
const consolidationPopover = ref<InstanceType<typeof StructureInfoPopover>>()
type RenderedDivergence = { divergence: ChanlunDivergence; coord: number[]; symbolOffset: number[]; symbolSize: number }
let renderedDivergences: RenderedDivergence[] = []
type RenderedSignal = { details: ChartSignalDetail[]; coord: Array<string | number>; symbolOffset: number[]; symbolSize: number[] }
let renderedSignals: RenderedSignal[] = []
const availableSignals = computed(() => !props.layers.mmds ? [] : [
  ...props.result.mmds.flatMap(signal => {
    const index = chartBarIndex(props.bars, signal.date)
    return index === null ? [] : [structuralSignalDetail(signal, signal.type.includes('buy') ? props.bars[index]!.low : props.bars[index]!.high)]
  }),
  ...macdPrompts(props.result.bcs).flatMap(item => {
    const index = chartBarIndex(props.bars, item.curr_date, item.signal_index)
    return index === null ? [] : [macdSignalDetail(item, item.direction === 'down' ? props.bars[index]!.low : props.bars[index]!.high)]
  }),
])
type ObjectChoice = { title: string; signal?: ChartSignalDetail; divergence?: ChanlunDivergence }
let markerCandidates: MarkerCandidate<{ key: string; objects: ObjectChoice[] }>[] | null = null
type StructureHit = { key: string; objects?: ObjectChoice[]; signals?: ChartSignalDetail[]; divergences?: ChanlunDivergence[]; areas?: number[] }
let hoverKey = ''
let dismissedHoverKey = ''
let hoverCloseTimer: ReturnType<typeof setTimeout> | undefined
function cancelHoverClose() { clearTimeout(hoverCloseTimer); hoverCloseTimer = undefined }
function onPopoverClosed() { cancelHoverClose(); dismissedHoverKey = hoverKey; hoverKey = '' }
function clearObjectPreview() {
  if (consolidationPopover.value?.isPinned()) return
  cancelHoverClose()
  consolidationPopover.value?.hide(false)
  hoverKey = ''; dismissedHoverKey = ''
}
function releaseObjectModifier(event: KeyboardEvent) {
  if (!objectHover.value && (event.key === 'Meta' || !event.metaKey)) clearObjectPreview()
}
function blurObjectPreview() { clearObjectPreview() }
function leaveWorkspace() {
  // Native popovers live in the top layer, outside a v-show-hidden chart.
  cancelHoverClose()
  consolidationPopover.value?.hide(false)
  clickTooltip?.hide()
  hoverKey = ''; dismissedHoverKey = ''; cursorKey = ''
  emit('cursor', null)
}
watch(objectHover, () => { cancelHoverClose(); consolidationPopover.value?.hide(false); hoverKey = ''; dismissedHoverKey = '' })
function leaveStructure() {
  if (consolidationPopover.value?.isPinned() || hoverCloseTimer !== undefined) return
  hoverCloseTimer = setTimeout(() => {
    hoverCloseTimer = undefined
    if (!consolidationPopover.value?.isPinned()) consolidationPopover.value?.hide(false)
    hoverKey = ''; dismissedHoverKey = ''
  }, 180)
}
function leaveChart() { cursorKey = ''; emit('cursor', null); leaveStructure() }
function showConsolidations(indices: number[], x: number, y: number, preview = false) {
  clickTooltip?.hide()
  const areas = props.result.pen_consolidations ?? []
  void consolidationPopover.value?.show(indices.flatMap(index => areas[index] ? [{ index, area: areas[index]! }] : []), x, y, preview)
}
function structureHit(event: MouseEvent): StructureHit | null {
  if (!chart || !container.value) return null
  const rect = container.value.getBoundingClientRect()
  const x = (event.clientX - rect.left) * chart.getWidth() / rect.width
  const y = (event.clientY - rect.top) * chart.getHeight() / rect.height
  const markers = markerCandidates ??= [
    ...renderedSignals.map((point, index) => {
      const pixel = chart!.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, point.coord) as number[]
      return { center: pixel.map((value, i) => value + point.symbolOffset[i]!), size: point.symbolSize,
        value: { key: `signal:${index}`, objects: point.details.map(signal => ({ title: `${signal.title} · ${signal.date}`, signal })) } }
    }),
    ...renderedDivergences.map((point, index) => {
      const pixel = chart!.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, point.coord) as number[]
      return { center: pixel.map((value, i) => value + point.symbolOffset[i]!), size: [point.symbolSize, point.symbolSize],
        value: { key: `divergence:${index}`, objects: [{ title: `${divergenceName(point.divergence)} · ${point.divergence.curr_date}`, divergence: point.divergence }] } }
    }),
  ]
  const hitsByPoint = nearestMarkers(markers, x, y)
  if (hitsByPoint.length) return { key: hitsByPoint.map(item => item.key).join(','), objects: hitsByPoint.flatMap(item => item.objects) }
  if (!props.layers.consolidations || !chart.containPixel({ gridIndex: 0 }, [x, y])) return null
  const bounds = (props.result.pen_consolidations ?? []).flatMap((area, index) => {
    const start = chartBarIndex(props.bars, area.start_date), end = chartBarIndex(props.bars, area.end_date)
    return start === null || end === null ? [] : [{ index,
      start: chart!.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [start, area.lower]) as number[],
      end: chart!.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [end, area.upper]) as number[],
    }]
  })
  const hits = consolidationHits(bounds, x, y)
  return hits.length ? { key: `areas:${hits.join(',')}`, areas: hits } : null
}
function showStructure(hit: StructureHit, event: MouseEvent, preview: boolean) {
  cancelHoverClose()
  clickTooltip?.hide()
  if (hit.objects) void consolidationPopover.value?.showObjects(hit.objects, event.clientX, event.clientY, preview)
  else if (hit.signals) void consolidationPopover.value?.showSignals(hit.signals, event.clientX, event.clientY, preview)
  else if (hit.divergences) void consolidationPopover.value?.showDivergences(hit.divergences, event.clientX, event.clientY, preview)
  else showConsolidations(hit.areas!, event.clientX, event.clientY, preview)
}
function onConsolidationContext(event: MouseEvent) {
  const hit = structureHit(event)
  if (!hit) return
  event.preventDefault()
  hoverKey = ''; dismissedHoverKey = ''
  showStructure(hit, event, false)
}
function onStructureHover(event: PointerEvent) {
  emitCursor(event)
  if (!objectHover.value && !event.metaKey) { clearObjectPreview(); return }
  if (event.pointerType !== 'mouse' || event.buttons || (clickTooltip?.isActive() && !event.metaKey) || consolidationPopover.value?.isPinned()) return
  const hit = structureHit(event)
  if (!hit) { leaveStructure(); return }
  cancelHoverClose()
  if (hit.key === hoverKey || hit.key === dismissedHoverKey) return
  dismissedHoverKey = ''
  hoverKey = hit.key
  showStructure(hit, event, true)
}
function onChartClick(event: MouseEvent) {
  if (props.evidenceEnabled && chart && container.value) {
    const rect = container.value.getBoundingClientRect()
    const point = [(event.clientX - rect.left) * chart.getWidth() / rect.width, (event.clientY - rect.top) * chart.getHeight() / rect.height]
    if (chart.containPixel({ gridIndex: 0 }, point)) {
      const index = Math.round((chart.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, point) as number[])[0]!)
      reviewDate.value = props.bars[index]?.datetime ?? ''
    }
  }
  const hit = objectHover.value ? structureHit(event) : null
  if (hit) { hoverKey = ''; dismissedHoverKey = ''; showStructure(hit, event, false); return }
  cancelHoverClose()
  consolidationPopover.value?.hide(false)
}
function browseSignals(event: MouseEvent) {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  clickTooltip?.hide()
  void consolidationPopover.value?.showSignals(availableSignals.value.slice().reverse(), rect.left, rect.bottom)
}
function browseConsolidations(event: MouseEvent) {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  showConsolidations((props.result.pen_consolidations ?? []).map((_, index) => index).reverse(), rect.left, rect.bottom)
}
function browseDivergences(event: MouseEvent) {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  clickTooltip?.hide()
  void consolidationPopover.value?.showDivergences(visibleDivergences(props.result.bcs, props.showDivergenceHistory)
    .filter(item => chartBarIndex(props.bars, item.curr_date, item.signal_index) !== null).slice().reverse(), rect.left, rect.bottom)
}
const indicators = ref<Array<{ id: number; type: TechnicalIndicator; params: IndicatorParams; rows: Array<Record<string, unknown>> }>>(
  (props.frozenIndicators?.indicators ?? (props.readonlyArchive ? [] : props.indicatorConfig ?? preferences.settings.value.indicators)).map((item, id) => ({ ...item, params: { ...item.params }, id, rows: [] })))
let nextIndicatorId = indicators.value.length
const indicatorDefinition = (item: {id:number;type:string}) => props.frozenIndicators?.indicators[item.id] ?? getIndicatorDefinition(item.type)
const panels = computed(() => indicators.value.filter(item => indicatorDefinition(item).placement === 'panel'))
const chartHeight = computed(() => 470 + panels.value.length * 155)
function addIndicator() {
  if (indicators.value.length >= 8) return
  const type = (['kdj', 'rsi', 'volume', 'boll'] as TechnicalIndicator[]).find(type => !indicators.value.some(item => item.type === type)) ?? 'macd'
  indicators.value.push({ id: nextIndicatorId++, type, params: { ...getIndicatorDefinition(type).defaultParams }, rows: [] })
}
const indicatorLoading = ref(false)
const indicatorError = ref('')
let chart: echarts.ECharts | null = null
let clickTooltip: ReturnType<typeof installClickChartTooltip> | null = null
let resizeObserver: ResizeObserver | null = null
const viewportMemory = new ChartViewportMemory()
let renderedBars: Bar[] | null = null
let renderedIdentity = ''
let viewportScope = {}
let cursorKey = ''
let linkedGraphicIds: string[] = []
function emitCursor(event: PointerEvent) {
  if (!chart || !container.value) return
  const rect = container.value.getBoundingClientRect()
  const point = [(event.clientX - rect.left) * chart.getWidth() / rect.width, (event.clientY - rect.top) * chart.getHeight() / rect.height]
  if (!chart.containPixel({ gridIndex: 0 }, point)) { if (cursorKey) { cursorKey = ''; emit('cursor', null) }; return }
  const index = Math.round((chart.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, point) as number[])[0]!)
  const bar = props.bars[index]
  if (bar && cursorKey !== bar.datetime) { cursorKey = bar.datetime; emit('cursor', barWindow(bar, props.periodCategory ?? props.result.frequency)) }
}
function zoomWindow(): TimeWindow | null {
  const zoom = (chart?.getOption().dataZoom as Array<{ start?: number; end?: number; startValue?: number; endValue?: number }> | undefined)?.[0]
  if (!zoom || !props.bars.length) return null
  const last = props.bars.length - 1
  const start = Math.max(0, Math.round(zoom.startValue ?? (zoom.start ?? 0) * last / 100))
  const end = Math.min(last, Math.round(zoom.endValue ?? (zoom.end ?? 100) * last / 100))
  return { start: barWindow(props.bars[start]!, props.periodCategory ?? props.result.frequency).start, end: barWindow(props.bars[end]!).end }
}
function applyLinkedZoom(range: TimeWindow | null | undefined) {
  if (!chart || !range) return
  const indices = overlappingBars(props.bars, range, props.periodCategory ?? props.result.frequency)
  if (!indices.length) { linkedLabel.value = '联动范围内无对应行情'; return }
  chart.dispatchAction({ type: 'dataZoom', startValue: indices[0], endValue: indices.at(-1) }, { silent: true })
  markerCandidates = null
  const visible = zoomWindow(); if (visible) emit('viewport', visible)
  consolidationPopover.value?.hide()
  drawLinkedCursor()
}
function drawLinkedCursor(range = props.linkedCursor) {
  if (!chart) return
  const indices = range ? overlappingBars(props.bars, range, props.periodCategory ?? props.result.frequency) : []
  linkedLabel.value = range ? indices.length ? `联动：${range.start} — ${range.end} · 对应 ${indices.length} 根` : '此时间区间无对应行情' : ''
  const children: Record<string, unknown>[] = []
  if (indices.length) {
    for (let panel = 0; panel <= panels.value.length; panel++) {
      // Read the resolved grid rectangle (including ECharts label/layout adjustments).
      // Guard this internal adapter so a future engine change simply omits the decoration.
      const model = (chart as unknown as { getModel?: () => { getComponent: (kind: string, index: number) => { coordinateSystem?: { getRect: () => PlotRect } } | undefined } }).getModel?.()
      const grid = model?.getComponent('grid', panel)
      const rect = grid?.coordinateSystem?.getRect()
      if (!rect) continue
      const first = indices[0]!, last = indices.at(-1)!
      const left = chart.convertToPixel({ xAxisIndex: panel }, first) as number
      const right = chart.convertToPixel({ xAxisIndex: panel }, last) as number
      const adjacent = chart.convertToPixel({ xAxisIndex: panel }, first < props.bars.length - 1 ? first + 1 : first - 1) as number
      const halfBand = Number.isFinite(adjacent) ? Math.abs(adjacent - left) / 2 : 0
      const graphic = timeLinkGraphic(rect, left, right, indices.length, halfBand)
      if (graphic) children.push({ ...graphic, id: `research-time-link-${panel}`, $action: 'replace' })
    }
  }
  const nextIds = children.map(item => item.id as string)
  const removed = linkedGraphicIds.filter(id => !nextIds.includes(id)).map(id => ({ id, $action: 'remove' }))
  // Explicit IDs/removal avoid anonymous group children surviving an empty update.
  chart.setOption({ graphic: [...removed, ...children] } as never)
  linkedGraphicIds = nextIds
}
function locate(date: string) {
  const index = chartBarIndex(props.bars, date)
  if (index === null || !chart) return
  const visible = zoomWindow()
  const indices = visible ? overlappingBars(props.bars, visible, props.periodCategory ?? props.result.frequency) : []
  if (indices.length && (index < indices[0]! || index > indices.at(-1)!)) {
    const span = indices.at(-1)! - indices[0]!
    const start = Math.max(0, Math.min(props.bars.length - span - 1, index - Math.floor(span / 2)))
    chart.dispatchAction({ type: 'dataZoom', startValue: start, endValue: start + span }, { silent: true })
    markerCandidates = null
    const range = zoomWindow(); if (range) emit('viewport', range)
  }
  drawLinkedCursor(barWindow(props.bars[index]!, props.periodCategory ?? props.result.frequency))
  container.value?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  container.value?.focus({ preventScroll: true })
}
defineExpose({ locate, zoomWindow, captureIndicators })
watch(() => props.linkedCursor, () => drawLinkedCursor())
watch(() => props.linkedZoom, applyLinkedZoom)
watch(() => props.indicatorConfig ?? preferences.settings.value.indicators, items => {
  if (props.frozenIndicators || props.readonlyArchive) return
  if (JSON.stringify(items) === JSON.stringify(indicators.value.map(({ type, params }) => ({ type, params })))) return
  indicators.value = items.map(item => ({ ...item, params: { ...item.params }, id: nextIndicatorId++, rows: [] }))
}, { deep: true })
watch(() => indicators.value.map(({ type, params }) => ({ type, params })), items => { if (!props.indicatorConfig && !props.frozenIndicators && !props.readonlyArchive) preferences.patch({ indicators: items }) }, { deep: true })

function normalizedDate(value: string): string {
  return value.replace('T', ' ').slice(0, 16).replace(/ 00:00$/, '')
}

function price2(value: unknown): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '—'
}

function buildOption(): echarts.EChartsCoreOption {
  const intraday = props.bars.some((bar) => bar.datetime.slice(11, 19) !== '00:00:00')
  const dates = props.bars.map((bar) => {
    const normalized = normalizedDate(bar.datetime)
    return intraday ? normalized : normalized.slice(0, 10)
  })
  const ohlc = props.bars.map((bar) => provisionalCandle([bar.open, bar.close, bar.low, bar.high], bar.is_closed))
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
          details: signals.map(item => structuralSignalDetail(item, isBuy ? bar.low : bar.high)),
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

  const macdPromptSlots = new Set<string>()
  const promptItems = macdPrompts(props.result.bcs)
  const macdPoints = props.layers.mmds ? promptItems.flatMap(item => {
    const index = chartBarIndex(props.bars, item.curr_date, item.signal_index)
    if (index === null) return []
    const slot = `${index}:${item.direction}`
    if (macdPromptSlots.has(slot)) return []
    macdPromptSlots.add(slot)
    const buy = item.direction === 'down'
    const price = buy ? props.bars[index]!.low : props.bars[index]!.high
    return [{
      name: `M1 · MACD ${buy ? '买入' : '卖出'}提示`, value: 'M1',
      date: dates[index], price, coord: [index, price],
      details: promptItems.filter(other => other.direction === item.direction
        && chartBarIndex(props.bars, other.curr_date, other.signal_index) === index).map(other => macdSignalDetail(other, price)),
      message: `仅为 MACD 波段提示，不等同于缠论结构一${buy ? '买' : '卖'}。<br/>极值：${item.curr_date}；实际确认：${item.confirmed_date}`,
      symbol: 'roundRect', symbolSize: [20, 13], symbolOffset: [0, buy ? 25 : -25],
      itemStyle: { color: buy ? '#e65b6b' : '#39ad79', borderWidth: 0 },
      label: { show: true, formatter: 'M1', color: '#fff', fontSize: 7, fontWeight: 700 },
    }]
  }) : []
  const divergenceSlots = new Map<string, number>()
  const divergencePoints = props.layers.bcs
    ? visibleDivergences(props.result.bcs, props.showDivergenceHistory).flatMap((item) => {
        const index = chartBarIndex(props.bars, item.curr_date, item.signal_index)
        if (index === null) return []
        const date = dates[index]!
        const bar = props.bars[index]!
        const slotKey = `${index}:${item.direction}`
        const slot = divergenceSlots.get(slotKey) ?? 0
        divergenceSlots.set(slotKey, slot + 1)
        return [{
          ...divergenceMarker(item, props.showDivergenceHistory),
          divergence: item,
          name: divergenceName(item),
          value: item.type.toUpperCase(),
          date,
          price: item.direction === 'down' ? bar.low : bar.high,
          message: `${item.status === 'superseded' ? '历史候选 · 已失效／被替代' : item.status === 'candidate' ? '候选 · 尚未确认' : '已确认（不保证反转）'}；对照：${item.prev_date ?? '—'}<br/>${divergenceEvidence(item).join('<br/>')}`,
          coord: [index, item.direction === 'down' ? bar.low : bar.high],
          symbolOffset: [0, (item.direction === 'down' ? 1 : -1) * ((macdPromptSlots.has(slotKey) ? 40 : 23) + slot * 13)],
        }]
      })
    : []

  renderedDivergences = divergencePoints as RenderedDivergence[]
  renderedSignals = [...signalPoints, ...macdPoints]
  const series: Array<Record<string, unknown>> = [
    {
      name: 'K 线',
      type: 'candlestick',
      data: ohlc,
      itemStyle: {
        color: candleFill(UP_COLOR, props.candleTransparency),
        color0: candleFill(DOWN_COLOR, props.candleTransparency),
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
        data: [...signalPoints, ...macdPoints, ...divergencePoints],
        tooltip: {
          ...clickTooltipOptions,
          formatter: (params: { data?: { name?: string; date?: string; price?: number; message?: string } }) => {
            const data = params.data
            if (!data) return ''
            return [
              `<strong style="color:#f5f5f7">${escapeChartText(data.name)}</strong>`,
              `<div style="margin-top:5px;color:#a6a6ad">${escapeChartText(data.date)} · ${price2(data.price)}</div>`,
              data.message ? `<div style="margin-top:5px;color:#7f818a">${escapeChartText(data.message)}</div>` : '',
            ].join('')
          },
        },
      },
    },
  ]

  if (props.layers.consolidations) {
    series.push({
      name: '三笔盘整', type: 'line', data: [], silent: true,
      markArea: {
        silent: true,
        itemStyle: { color: 'rgba(137,173,198,.035)', borderColor: 'rgba(155,189,211,.65)', borderWidth: 1, borderType: 'dashed' },
        label: { color: '#9dbbce', fontSize: 10, position: 'insideBottomLeft' },
        data: (props.result.pen_consolidations ?? []).flatMap((area, i) => {
          const start = resolveDate(area.start_date), end = resolveDate(area.end_date)
          return start && end ? [[
            { name: `盘整 ${i + 1}${area.confirmed ? '' : ' · 进行中'}`, xAxis: start, yAxis: area.lower, ...consolidationAppearance(area.confirmed) },
            { xAxis: end, yAxis: area.upper },
          ]] : []
        }),
      },
    })
  }

  if (props.focus) {
    if (props.focus.pen) {
      const pen = props.focus.pen
      series.push({name:'局部确认用笔（非全局结构笔）',type:'line',xAxisIndex:0,yAxisIndex:0,
        data:[[pen.start,pen.startPrice],[pen.end,pen.endPrice]],symbol:'circle',symbolSize:5,
        lineStyle:{color:'#b4d9ff',width:2,type:'dashed'},itemStyle:{color:'#b4d9ff'},z:12,
        tooltip:{show:false},silent:true})
    }
    // Independent overlays keep centre areas and indicator colors unchanged.
    for (const axis of axisIndices) {
      series.push({
        name: `核验区间 ${axis}`, type: 'line', xAxisIndex: axis, yAxisIndex: axis,
        data: [], silent: true, tooltip: { show: false },
        markLine: { silent: true, symbol: 'none',
          lineStyle: { color: 'rgba(116,184,255,.75)', width: 1, type: 'dashed' },
          label: { show: !mobile.value || axis === 0,
            formatter: mobile.value && props.focus.scope === 'reverse-pen'
              ? (point: {name: string}) => (({'信号极值':'起点','反向端点':'端点','实际确认':'确认'} as Record<string,string>)[point.name] ?? point.name)
              : '{b}', color: '#b4d9ff', fontSize: 10, rotate: 0,
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
      lineStyle: { color: '#79b9ef', width: structureLineWidth('bi', props.lineWidths?.bi), opacity: 0.78 },
      itemStyle: { color: '#a6d4f8', borderColor: '#1a2630', borderWidth: 0.8 },
      emphasis: {
        focus: 'series',
        scale: 1.45,
        lineStyle: { color: '#9bcefa', width: emphasizedLineWidth('bi', props.lineWidths?.bi), opacity: 1 },
      },
      z: 5,
    })
  }

  const preview = props.layers.nextPen ? nextPenPreview(props.bars, props.result.bis) : null
  if (preview) {
    series.push({
      name: '待成笔方向（观察）', type: 'line', silent: true, tooltip: { show: false },
      data: [[dates[preview.start], preview.startPrice], [dates[preview.end], preview.endPrice]],
      symbol: 'emptyCircle', symbolSize: 5,
      lineStyle: { color: '#d2a96c', width: structureLineWidth('bi', props.lineWidths?.bi), type: 'dashed', opacity: .9 },
      itemStyle: { color: '#d2a96c' },
      z: 7,
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
      lineStyle: { color: '#a88cdb', width: structureLineWidth('xd', props.lineWidths?.xd), opacity: segment.pending ? 0.58 : 0.84, type: segment.pending ? 'dashed' : 'solid' },
      itemStyle: { color: '#c8b3ec', borderColor: '#251f31', borderWidth: 0.8 },
      emphasis: {
        focus: 'series',
        scale: 1.35,
        lineStyle: { color: '#c0a7eb', width: emphasizedLineWidth('xd', props.lineWidths?.xd), opacity: 1 },
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
    const axis = indicatorDefinition(item).placement === 'panel' ? panels.value.findIndex(panel => panel.id === item.id) + 1 : 0
    const saved = props.frozenIndicators?.indicators[item.id]
    return (saved ? frozenIndicatorSeries(saved,props.bars) : buildIndicatorSeries(item.type, props.bars, item.rows)).map(series => {
      const name = `indicator-${item.id}-${series.name}`
      legendLabels.set(name, String(series.name))
      tooltipLabels.set(name, `${indicatorDefinition(item).label} · ${series.name}`)
      return { ...series, name, xAxisIndex: axis, yAxisIndex: axis }
    })
  })
  const averages = props.frozenIndicators ? frozenAverageSeries(props.frozenIndicators) : availableMA.value.map(period => ({
    name: `MA${period}`, type: 'line', showSymbol: false, connectNulls: false,
    data: chartMovingAverage(props.bars,period),
    lineStyle: { width: 1.2, color: movingAverageColor(period) },
    itemStyle: { color: movingAverageColor(period) },
  }))
  series.push(...averages, ...secondarySeries)
  synchronizeChartSeries(series)

  return {
    backgroundColor: 'transparent',
    ...synchronousChartMotion,
    tooltip: {
      ...clickTooltipOptions,
      trigger: 'axis',
      confine: true,
      padding: [10, 12],
      axisPointer: {
        animation: false,
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
        if (!bar) return escapeChartText(candle?.axisValueLabel)
        const change = percentageChange(props.bars, index)
        const changeColor = (change ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR
        const details = params
          .filter((item) => item.seriesType !== 'candlestick' && secondarySeries.some((seriesItem) => seriesItem.name === item.seriesName))
          .map((item) => {
            const raw = Array.isArray(item.value) ? item.value[item.value.length - 1] : item.value
            const value = Number(raw)
            if (!Number.isFinite(value)) return ''
            return `<span>${escapeChartText(tooltipLabels.get(item.seriesName ?? '') ?? item.seriesName)}<b style="float:right;color:#c8c8cd">${price2(value)}</b></span>`
          }).join('')
        return `
          <div style="min-width:190px">
            <div style="color:#f5f5f7;font-weight:650;margin-bottom:8px">${escapeChartText(candle?.axisValueLabel)}</div>
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
        show: averages.length > 0 && !mobile.value,
        data: averages.map(item => item.name),
        selected: movingAverageSelection(availableMA.value, enabledMA.value),
        inactiveColor: '#626977',
        pageIconColor: '#9298a4', pageIconInactiveColor: '#363943',
        pageTextStyle: { color: '#858b98' },
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
    axisPointer: { animation: false, link: [{ xAxisIndex: 'all' }] },
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
        name: indicatorDefinition(item).label,
        nameTextStyle: { color: '#9298a4', fontSize: 10 },
        scale: !indicatorDefinition(item).bounds,
        min: indicatorDefinition(item).bounds?.[0],
        max: indicatorDefinition(item).bounds?.[1],
        splitNumber: 3, axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,.045)', type: 'dashed' } },
        axisLabel: { formatter: (value: number) => item.type === 'volume' ? compactNumber(value) : price2(value) },
      })),
    ],
    dataZoom: [
      {
        type: 'inside', xAxisIndex: axisIndices, throttle: 16,
        ...(props.focus ? { startValue: props.focus.start, endValue: props.focus.end }
          : { start: Math.max(0, 100 - Math.min(100, 12000 / Math.max(dates.length, 1))), end: 100 }),
      },
      {
        type: 'slider',
        throttle: 16, realtime: true,
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
  markerCandidates = null
  consolidationPopover.value?.hide()
  if (!container.value || !props.bars.length) return
  if (!chart) {
    chart = echarts.init(container.value, 'dark')
    clickTooltip = installClickChartTooltip(chart, container.value)
    chart.on('datazoom', () => { markerCandidates = null; consolidationPopover.value?.hide(); const range = zoomWindow(); if (range) { emit('zoom', range); emit('viewport', range) }; drawLinkedCursor() })
    chart.on('legendselectchanged', (event: unknown) => {
      const { name, selected } = event as { name: string; selected: Record<string, boolean> }
      if (availableMA.value.some(period => name === `MA${period}`)) {
        const periods=availableMA.value.filter(period => selected[`MA${period}`] !== false)
        if (props.frozenIndicators) frozenMASelection.value=periods
        else emit('update:maPeriods', periods)
      }
    })
  }
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
      legend.selected = { ...selected, ...movingAverageSelection(availableMA.value, enabledMA.value) }
    }
  }
  renderedBars = props.bars
  renderedIdentity = identity
  clickTooltip?.hide()
  // A reset drops ECharts' graphic registry too. Do not later remove stale IDs
  // from the previous registry when an evidence focus rebuilds the chart.
  if (props.focus || !sameSnapshot) linkedGraphicIds = []
  if (props.focus) chart.clear()
  // Cursor graphics need the new axes/grid immediately, not a deferred layout.
  chart.setOption(option, { notMerge: !sameSnapshot, replaceMerge: sameSnapshot ? ['series', 'xAxis', 'yAxis', 'grid', 'legend'] : undefined, lazyUpdate: false })
  drawLinkedCursor()
  const visible = zoomWindow(); if (visible) emit('viewport', visible)
  requestAnimationFrame(() => { markerCandidates = null; chart?.resize(); drawLinkedCursor() })
}

let indicatorRequest = 0
let readyBars: Bar[] | null = null
let readyMacd: ChanlunResult['macd'] | undefined
let readyConfig = ''
const indicatorSignature = () => JSON.stringify(indicators.value.map(item=>[item.type,item.params]))
function captureIndicators(): FrozenChartIndicators {
  if (props.frozenIndicators) return JSON.parse(JSON.stringify(props.frozenIndicators)) as FrozenChartIndicators
  if (props.readonlyArchive) throw new Error('旧档未保存冻结指标，不能补造原版指标')
  if (indicatorLoading.value || indicatorError.value || readyBars !== props.bars || readyMacd !== props.result.macd || readyConfig !== indicatorSignature()) {
    throw new Error('技术指标尚未完整计算，暂不能保存；请等待完成或修正报错的指标')
  }
  return freezeChartIndicators(props.bars,availableMA.value,enabledMA.value,indicators.value)
}
async function refreshIndicator() {
  const requestId = ++indicatorRequest
  indicatorError.value = ''
  if (props.frozenIndicators || props.readonlyArchive) { indicatorLoading.value=false; render(); return }
  const inputBars=props.bars, inputMacd=props.result.macd, inputConfig=indicatorSignature()
  indicatorLoading.value = true
  try {
    await Promise.all(indicators.value.map(async item => {
      try {
        // The primary MACD is the exact series used to compute these signals.
        const macd = props.result.macd
        const rows = item.type === 'macd' && macd?.dif.length === props.bars.length
          ? props.bars.map((_, i) => ({ MACD_DIF: macd.dif[i], MACD_DEA: macd.dea[i], MACD_HIST: macd.hist[i] }))
          : await researchIndicatorRows(props.bars, item.type, item.params)
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
      if (!indicatorError.value) { readyBars=inputBars; readyMacd=inputMacd; readyConfig=inputConfig }
      render()
    }
  }
}

onMounted(() => {
  window.addEventListener('keyup', releaseObjectModifier)
  window.addEventListener('blur', blurObjectPreview)
  window.addEventListener('research-workspace-change', leaveWorkspace)
  render()
  void refreshIndicator()
  if (container.value) {
    resizeObserver = new ResizeObserver(() => { markerCandidates = null; consolidationPopover.value?.hide(); chart?.resize(); drawLinkedCursor() })
    resizeObserver.observe(container.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keyup', releaseObjectModifier)
  window.removeEventListener('blur', blurObjectPreview)
  window.removeEventListener('research-workspace-change', leaveWorkspace)
  indicatorRequest++
  cancelHoverClose()
  resizeObserver?.disconnect()
  clickTooltip?.dispose()
  chart?.dispose()
  chart = null
})

let renderFrame = 0
function scheduleRender() { cancelAnimationFrame(renderFrame); renderFrame = requestAnimationFrame(render) }
onBeforeUnmount(() => cancelAnimationFrame(renderFrame))
watch(() => [props.result, props.bars], () => { reviewDate.value = ''; scheduleRender() })
watch(() => [props.layers, props.maPeriods, props.maAvailablePeriods, props.focus, props.lineWidths, props.candleTransparency, props.showDivergenceHistory, mobile.value], scheduleRender, { deep: true })
watch(() => [props.bars, props.result.macd, indicators.value.map(item => [item.id, item.type, item.params])], () => void refreshIndicator(), { deep: true })
</script>

<template>
  <div class="market-chart-shell">
    <div v-if="mobile && availableMA.length" class="mobile-ma-controls" role="group" aria-label="均线显示开关">
      <button v-for="period in availableMA" :key="period" type="button" :aria-pressed="enabledMA.includes(period)" @click="toggleMobileMA(period)">
        <i :style="{ background: movingAverageColor(period) }" aria-hidden="true"></i>MA{{ period }}
      </button>
    </div>
    <div
      ref="container"
      class="chanlun-chart"
      tabindex="-1"
      role="region"
      aria-label="蜡烛图绘图区"
      @contextmenu="onConsolidationContext"
      @pointermove="onStructureHover"
      @pointerleave="leaveChart"
      @click="onChartClick"
      :style="{ height: `${chartHeight}px`, minHeight: `${chartHeight}px`, '--chanlun-chart-height': `${chartHeight}px` }"
    ></div>
    <div v-if="evidenceEnabled" class="consolidation-access"><span>{{ reviewDate ? `所选 K 线 · ${reviewDate.replace('T', ' ')}` : '点击主图 K 线，可查找该日期关联证据' }}</span><button type="button" :disabled="!reviewDate" @click="emit('review', reviewDate)">查看所选日期证据</button></div>
    <p v-if="linkedLabel" class="macd-prompt-note" role="status">{{ linkedLabel }}</p>
    <div v-if="layers.consolidations && result.pen_consolidations?.length" class="consolidation-access"><span>右键盘整矩形，查看区间详情</span><button type="button" @click="browseConsolidations">查看盘整详情</button></div>
    <div v-if="layers.bcs && visibleDivergences(result.bcs, showDivergenceHistory).length" class="consolidation-access"><span>右键背离／背驰标记，查看状态与依据</span><button type="button" @click="browseDivergences">查看背离详情</button></div>
    <div v-if="availableSignals.length" class="consolidation-access"><span>{{ objectHover ? '悬停预览买卖点，点击或右键固定查看' : '右键查看买卖点，或按住 ⌘ 悬停预览' }}</span><button type="button" @click="browseSignals">查看买卖点详情</button></div>
    <StructureInfoPopover ref="consolidationPopover" :mobile-sheet="preferences.settings.value.mobileSheet" :evidence-enabled="evidenceEnabled" @review="emit('review', $event)" @locate="locate" @inspect="emit('inspect', $event)" @enter="cancelHoverClose" @leave="leaveStructure" @closed="onPopoverClosed" />
    <p v-if="layers.nextPen" class="macd-prompt-note">琥珀虚线＝待成笔方向 · 仅连接可见已收盘行情的反向运动，端点可变；突破观察极值即撤销，不改变严格笔。</p>
    <p v-if="layers.bcs" class="macd-prompt-note">圆形＝双线 · 菱形＝标准 · 三角形＝非标准 · 大菱形＝特殊 · 底紫顶绿 · 彩色空心＝候选 · 实心＝确认<span v-if="showDivergenceHistory"> · 灰色空心＝已失效／被替代</span></p>
    <p v-if="layers.mmds && macdPrompts(result.bcs).length" class="macd-prompt-note">M1 为 MACD 波段提示，非缠论结构一类点；标记位于极值日，实际确认日见提示详情。</p>
    <p v-if="frozenIndicators" class="macd-prompt-note">原档指标 · 数值及参数已冻结，不重算；图例可临时隐藏曲线。</p>
    <p v-else-if="readonlyArchive" class="macd-prompt-note">旧档未保存指标 · 仅展示原行情与原结构，未补算。</p>
    <div v-if="!frozenIndicators && !readonlyArchive" class="indicator-heading"><span>技术指标 · 可同时显示多个</span><button :disabled="indicators.length >= 8" @click="addIndicator">＋ 添加指标</button></div>
    <div v-for="(item, index) in frozenIndicators || readonlyArchive ? [] : indicators" :key="item.id" class="indicator-entry">
    <button class="remove-indicator" :aria-label="`移除第 ${index + 1} 个指标`" @click="indicators.splice(index, 1)">移除</button>
    <TechnicalIndicatorPicker
      v-model="item.type"
      v-model:params="item.params"
      :loading="indicatorLoading"
      :locked-params="item.type === 'macd'"
    />
    </div>
    <p v-if="indicatorError" role="alert">{{ indicatorError }}</p>
  </div>
</template>

<style scoped>
.consolidation-access { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px 12px; padding: 6px 0; color: var(--text-dim); font-size: 10px; }
.consolidation-access button { min-height: 30px; padding: 4px 9px; border: 1px solid rgba(162,184,213,.13); border-radius: 6px; background: rgba(255,255,255,.025); color: #aebed3; box-shadow: none; font-size: 10px; }
.consolidation-access button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.macd-prompt-note { margin: 4px 0 8px; color: var(--text-muted); font-size: 11px; line-height: 1.6; }
.indicator-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 12px 0 4px; font-size: 11px; color: var(--text-muted); }
.indicator-heading button, .remove-indicator { padding: 5px 9px; font-size: 11px; border: 1px solid var(--border); border-radius: 7px; background: rgba(255,255,255,.03); color: var(--text-muted); cursor: pointer; }
.indicator-entry { position: relative; border-bottom: 1px solid var(--border); padding-right: 52px; }
.remove-indicator { position: absolute; right: 0; top: 13px; }
:global(.chart-frame:fullscreen .market-chart-shell), :global(.chart-frame.fallback-expanded .market-chart-shell) { overflow-y: auto; }
:global(.chart-frame:fullscreen .chanlun-chart), :global(.chart-frame.fallback-expanded .chanlun-chart) { flex: none !important; }
.market-chart-shell {
  width: 100%;
}
.chanlun-chart {
  width: 100%;
  height: 470px;
}
.chanlun-chart.has-indicator { height: 585px; }
:global(.chart-frame:fullscreen .chanlun-chart),
:global(.chart-frame.fallback-expanded .chanlun-chart) {
  height: calc(100vh - 122px);
  min-height: 600px;
}
</style>
