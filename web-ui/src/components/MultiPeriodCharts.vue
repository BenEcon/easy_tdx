<script setup lang="ts">
import { queryAction } from '../query-origin'
import { computed, nextTick, onBeforeUnmount, shallowRef, ref, watch } from 'vue'
import { fetchResearchSnapshot, replayChanlun, formatError, type BarSnapshot } from '../api'
import { targetIdentity, type ResearchTarget } from '../chanlun-target'
import { alignPeriodSnapshots, comparisonPeriods, periodLabel } from '../period-comparison'
import type { AdjustMode, Bar, Category, ChanlunResult, ChanlunDivergence } from '../types'
import type { ChanlunLineWidths } from '../chanlun-line-width'
import { divergenceFocus, reversePenFocus, type DivergenceFocus } from '../divergence-focus'
import { divergenceName } from '../divergence-evidence'
import { selectEvidenceSource } from '../evidence-replay'
import { chartBarIndex } from '../chart-position'
import ChartFrame from './ChartFrame.vue'
import ChanlunChart from './ChanlunChart.vue'
import MacSelect from './MacSelect.vue'
import PeriodStructureInspector from './PeriodStructureInspector.vue'
import PeriodEvidencePanel from './PeriodEvidencePanel.vue'
import { useResearchPreferences } from '../research-preferences'
import type { TimeWindow } from '../chart-research-link'
import { ResearchRequestCache } from '../research-request-cache'
import type { ResearchSnapshot } from '../research-snapshots'
import type { FrozenChartIndicators } from '../frozen-chart-indicators'
import { visibleComparisonPeriod, type ResearchWorkspace } from '../research-workspace'
import { useMobileViewport } from '../mobile-viewport'

const props = defineProps<{
  target: ResearchTarget; title: string; adjust: AdjustMode; asOf: string; busy: boolean
  primaryCategory: Category; primaryBars: Bar[]; primaryMetadata: BarSnapshot['metadata']; primaryResult: ChanlunResult; count: number
  layers: { bis: boolean; zss: boolean; xds: boolean; mmds: boolean; bcs: boolean; consolidations?: boolean; nextPen?: boolean }
  maPeriods: number[]; maAvailablePeriods: number[]; lineWidths: ChanlunLineWidths; candleTransparency: number
  showDivergenceHistory: boolean; focus?: DivergenceFocus | null
  workspace: ResearchWorkspace
  primaryIndicators: () => FrozenChartIndicators | undefined
}>()
const emit = defineEmits<{ 'update:maPeriods': [periods: number[]]; 'locate-primary': [date: string]; workspace:[value:ResearchWorkspace] }>()
const mobile = useMobileViewport()
const mobileCategory = ref<Category>(props.primaryCategory)
const auditVisited = ref(false)
watch(() => props.workspace, value => { if (value === 'audit') auditVisited.value = true }, {immediate:true})
watch([mobileCategory,mobile], () => { cursor.value = null; void nextTick(() => window.dispatchEvent(new Event('resize'))) })
const preferences = useResearchPreferences()
const selected = ref<Category>(preferences.settings.value.secondary === props.primaryCategory ? (props.primaryCategory === 'MIN_30' ? 'DAY' : 'MIN_30') : preferences.settings.value.secondary as Category)
const layout = computed({ get: () => preferences.settings.value.layout, set: value => preferences.patch({ layout: value }) })
const linkCursor = computed({ get: () => preferences.settings.value.linkCursor, set: value => preferences.patch({ linkCursor: value }) })
const linkZoom = computed({ get: () => preferences.settings.value.linkZoom, set: value => preferences.patch({ linkZoom: value }) })
const cursor = shallowRef<{ source: Category; range: TimeWindow | null } | null>(null)
const zoom = shallowRef<{ source: Category; range: TimeWindow } | null>(null)
const visibleRanges = ref<Partial<Record<Category, TimeWindow>>>({})
const chartRefs = new Map<Category, InstanceType<typeof ChanlunChart>>()
const inspector = ref<InstanceType<typeof PeriodStructureInspector>>()
const evidencePanel = ref<InstanceType<typeof PeriodEvidencePanel>>()
const evidenceFocus = shallowRef<{ category: Category; focus: DivergenceFocus } | null>(null)
const auditCategory = ref<Category>(props.primaryCategory)
const evidenceSource = computed(() => comparison.value && mode.value !== 'primary'
  ? selectEvidenceSource([comparison.value.primary, comparison.value.other], auditCategory.value) : null)
const auditData = computed(() => {
  if (comparison.value && mode.value !== 'primary') return auditCategory.value === comparison.value.other.category ? comparison.value.other : comparison.value.primary
  return { category: props.primaryCategory, bars: props.primaryBars, result: props.primaryResult, excluded: 0 }
})
function setChart(category: Category, element: unknown) {
  if (element) chartRefs.set(category, element as InstanceType<typeof ChanlunChart>)
  else chartRefs.delete(category)
}
function onZoom(category: Category, range: TimeWindow) { visibleRanges.value[category] = range; zoom.value = { source: category, range } }
async function inspectDate(category: Category, date: string) {
  emit('workspace','audit')
  auditCategory.value = category; await nextTick(); await inspector.value?.inspect(date)
}
async function reviewDate(category: Category, date: string) {
  if (!comparison.value || props.busy || loading.value) return
  const source = selectEvidenceSource([comparison.value.primary, comparison.value.other], category)
  if (!source || chartBarIndex(source.bars, date) === null) return
  emit('workspace','audit')
  auditCategory.value = category
  await nextTick()
  // Ignore a stale event if the snapshot changed while the component was mounting.
  if (evidenceSource.value !== source) return
  await evidencePanel.value?.inspect(date)
}
async function locateEvidenceDate(date: string) {
  const source = evidenceSource.value
  if (!source || chartBarIndex(source.bars, date) === null) return
  emit('workspace','chart'); mobileCategory.value = source.category
  if (!chartRefs.has(source.category)) { mode.value = 'compare'; await nextTick() }
  await nextTick()
  if (evidenceSource.value !== source) return
  chartRefs.get(source.category)?.locate(date)
}
async function locateEvidence(item: ChanlunDivergence, reverse: boolean) {
  const source = evidenceSource.value
  if (!source) return
  const label = `${periodLabel(source.category)} · ${divergenceName(item)}`
  const focus = reverse ? reversePenFocus(item, source.bars.length, label) : divergenceFocus(item, source.bars.length, label)
  if (!focus) return
  emit('workspace','chart'); mobileCategory.value = source.category
  evidenceFocus.value = { category: source.category, focus }
  if (!chartRefs.has(source.category)) mode.value = 'compare'
  await nextTick()
  if (evidenceSource.value !== source) return
  const date = item.curr_date ?? source.bars[focus.start]?.datetime
  if (date) chartRefs.get(source.category)?.locate(date)
}
watch(auditCategory, () => { evidenceFocus.value = null })
async function locate(date: string) {
  emit('workspace','chart')
  mobileCategory.value = auditData.value.category
  await nextTick()
  if (mode.value === 'primary' || !comparison.value) emit('locate-primary', date)
  else {
    const category = auditData.value.category
    if (!chartRefs.has(category)) { mode.value = 'compare'; await nextTick() }
    chartRefs.get(category)?.locate(date)
  }
}
defineExpose({ capture, showPrimary: () => { mode.value = 'primary' }, inspectMain: (date: string) => inspectDate(props.primaryCategory, date), setPrimaryRange: (range: TimeWindow) => { visibleRanges.value[props.primaryCategory] = range } })
watch(selected, value => preferences.patch({ secondary: value }))
watch(() => preferences.settings.value.secondary, value => {
  if (value !== props.primaryCategory) selected.value = value as Category
})
watch(layout, () => void nextTick(() => window.dispatchEvent(new Event('resize'))))
const options = computed(() => comparisonPeriods.filter(item => item.value !== props.primaryCategory))
const mode = ref<'primary' | 'other' | 'compare'>('primary')
const loading = ref(false)
const error = ref('')
const notice = ref('')
type ChartData = { category: Category; bars: Bar[]; result: ChanlunResult; excluded: number; metadata: BarSnapshot['metadata'] }
const comparison = shallowRef<{ cutoff: string; primary: ChartData; other: ChartData } | null>(null)
const charts = computed(() => !comparison.value || mode.value === 'primary' ? []
  : mode.value === 'other' ? [comparison.value.other] : [comparison.value.primary, comparison.value.other])
let generation = 0
let abort: AbortController | null = null
const replayCache = new ResearchRequestCache<ChanlunResult>()
function invalidate() {
  if (comparison.value || loading.value) notice.value = '分析条件或回放时刻已变化，请重新生成周期对比。'
  generation++; comparison.value = null; loading.value = false; error.value = ''; mode.value = 'primary'
  abort?.abort(); abort = null; cursor.value = null; zoom.value = null; visibleRanges.value = {}; auditCategory.value = props.primaryCategory
  evidenceFocus.value = null
  mobileCategory.value = props.primaryCategory
}
watch([() => targetIdentity(props.target), () => props.adjust, () => props.asOf, () => props.primaryCategory,
  () => props.primaryBars, () => props.primaryMetadata, () => props.count, selected], invalidate, { flush: 'sync' })
watch(() => props.primaryCategory, value => { if (selected.value === value) selected.value = value === 'MIN_30' ? 'DAY' : 'MIN_30' })
watch(() => props.focus, value => { if (value) mode.value = 'primary' })
watch(mode, value => { if (value === 'other' && comparison.value) auditCategory.value = comparison.value.other.category; void nextTick(() => window.dispatchEvent(new Event('resize'))) })
onBeforeUnmount(() => { generation++; abort?.abort(); replayCache.clear() })

async function generate() {
  if (loading.value) return
  abort?.abort(); abort = new AbortController()
  const signal = abort.signal
  const version = ++generation
  const instrument = { ...props.target }
  const identity = targetIdentity(instrument)
  const category = selected.value, primaryCategory = props.primaryCategory
  const primary: BarSnapshot = { bars: props.primaryBars, metadata: props.primaryMetadata }
  const originalResult = props.primaryResult
  const asOf = props.asOf, adjust = props.adjust, count = props.count
  loading.value = true; error.value = ''; notice.value = ''; comparison.value = null; mode.value = 'primary'
  evidenceFocus.value = null
  try {
    const snapshot = await queryAction(true)(() => fetchResearchSnapshot(instrument, category, count, adjust, signal))
    if (version !== generation) return
    const aligned = alignPeriodSnapshots(primary, snapshot, asOf, adjust)
    if (!aligned.primary.bars.length) throw new Error('主周期在共同截止前没有已收盘 K 线，暂不能对比')
    if (!aligned.other.bars.length) throw new Error(`${periodLabel(category)}在共同截止前没有已收盘 K 线。可向后回放或扩大历史窗口后重试。`)
    // Keep the original warm-up start; only remove unavailable suffix candles.
    const replay = (period: Category, bars: Bar[]) => {
      const req = { code: identity, category: period, bars, visible_count: bars.length }
      const key = JSON.stringify({ req, adjust, cutoff: aligned.cutoff, rules: { structure: originalResult.structure_metadata,
        base: originalResult.base_decomposition?.rule, macd: [...new Set(originalResult.bcs.map(item => item.evidence?.rule_version))] }, build: 'research-workspace-v1' })
      return replayCache.get(key, () => replayChanlun(req, signal))
    }
    const primaryResult = aligned.primary.excluded === 0 ? originalResult : await replay(primaryCategory, aligned.primary.bars)
    if (version !== generation) return
    const otherResult = await replay(category, aligned.other.bars)
    if (version !== generation) return
    comparison.value = { cutoff: aligned.cutoff,
      primary: { ...aligned.primary, category: primaryCategory, result: primaryResult, metadata: primary.metadata },
      other: { ...aligned.other, category, result: otherResult, metadata: snapshot.metadata } }
    mode.value = 'compare'
    mobileCategory.value = primaryCategory
    auditCategory.value = primaryCategory
  } catch (err) { if (version === generation) error.value = formatError(err) }
  finally { if (version === generation) loading.value = false }
}
const shortTime = (value: string) => value.replace('T', ' ').replace(' 00:00:00', '')
function rangeText(chart: ChartData) {
  return `${shortTime(chart.bars[0]!.datetime)} — ${shortTime(chart.bars.at(-1)!.period_end!)} · ${chart.bars.length} 根已收盘${chart.excluded ? ` · 排除 ${chart.excluded} 根未收盘或截止后行情` : ''}`
}
function capture(): Omit<ResearchSnapshot, 'schema' | 'id' | 'owner' | 'name' | 'note' | 'savedAt'> {
  if (props.busy || loading.value) throw new Error('当前周期仍在计算，请完成后保存快照')
  const savedCharts = comparison.value && mode.value !== 'primary' ? charts.value
    : [{ category: props.primaryCategory, bars: props.primaryBars, result: props.primaryResult, metadata: props.primaryMetadata }]
  return { target: props.target, title: props.title, cutoff: comparison.value && mode.value !== 'primary' ? comparison.value.cutoff : props.asOf,
    frontendVersion: 'research-frozen-indicators-20261009', ruleVersions: [...new Set(savedCharts.flatMap(chart => chart.result.bcs.map(item => item.evidence?.rule_version).filter((value): value is number => typeof value === 'number')))],
    preferences: preferences.settings.value, layers: props.layers, history: props.showDivergenceHistory, charts: savedCharts.map(chart=>{
      const frozenIndicators = comparison.value && mode.value !== 'primary' ? chartRefs.get(chart.category)?.captureIndicators() : props.primaryIndicators()
      if (!frozenIndicators) throw Error(`${periodLabel(chart.category)}图表尚未就绪，未保存不完整快照`)
      return {...chart,frozenIndicators}
    }) }
}
</script>

<template>
  <section class="period-charts" aria-label="多周期图表对比" :aria-busy="loading">
    <div v-show="workspace === 'chart'" class="period-chart-surface">
    <div class="period-tools">
      <div class="period-heading"><strong>多周期图表</strong><span>主周期 <b>{{ periodLabel(primaryCategory) }}</b></span></div>
      <div class="period-selection">
        <span class="period-selection-label">对照周期</span>
        <MacSelect v-model="selected" :options="options" aria-label="对照周期" :disabled="busy" />
        <button class="period-generate" :disabled="busy || loading || !asOf" @click="generate">{{ loading ? '计算中…' : comparison ? '重新生成' : '生成对比' }}</button>
      </div>
    </div>
    <div v-if="comparison" class="period-viewbar">
      <div class="period-modes" role="group" aria-label="周期图表显示方式">
        <button :aria-pressed="mode === 'primary'" @click="mode = 'primary'">主周期 · {{ periodLabel(primaryCategory) }}</button>
        <button :aria-pressed="mode === 'other'" @click="mode = 'other'">仅看 {{ periodLabel(comparison.other.category) }}</button>
        <button :aria-pressed="mode === 'compare'" @click="mode = 'compare'">双图对比</button>
      </div>
      <span class="period-cutoff">共同截止 <time>{{ comparison.cutoff }}</time></span>
      <div v-if="mode === 'compare' && !mobile" class="comparison-options">
        <label><input v-model="linkCursor" type="checkbox" />时间联动</label><label><input v-model="linkZoom" type="checkbox" />范围联动</label>
        <div class="period-modes" role="group" aria-label="对比布局"><button :aria-pressed="layout === 'stacked'" @click="layout = 'stacked'">上下排列</button><button :aria-pressed="layout === 'side'" @click="layout = 'side'">左右排列</button></div>
      </div>
    </div>
    <p v-if="error" class="period-error" role="alert">{{ error }}</p>
    <p v-else-if="loading" class="period-note" role="status">正在计算所选周期的独立结构，主图仍可查看…</p>
    <p v-else-if="!comparison" class="period-note" role="status">{{ notice || '选择另一个周期，查看同一标的的独立分析，或与主周期上下对比。' }}</p>
    <p v-else-if="mode !== 'primary'" class="period-note">仅纳入共同截止前的已收盘 K 线。图上日期可直达“审核”中的本周期证据；主周期完整审核单独保留。</p>
    <div v-show="mode === 'primary' || !comparison" class="period-primary"><slot /></div>
    <ChartFrame v-if="charts.length" class="comparison-workspace" title="周期对比工作区" :description="mobile ? '手机一次显示一个周期；切换保留原始对比快照。' : '全屏同时查看两个周期；可选择上下或左右排列。'">
    <div v-if="mobile && mode === 'compare' && comparison" class="mobile-chart-switch period-modes" role="group" aria-label="手机显示周期">
      <button v-for="chart in [comparison.primary,comparison.other]" :key="chart.category" :aria-pressed="mobileCategory === chart.category" @click="mobileCategory = chart.category">显示{{ periodLabel(chart.category) }}<span>{{ chart.category === primaryCategory ? '主周期' : '对照' }}</span></button>
    </div>
    <div class="period-comparison" :class="{ 'side-by-side': layout === 'side' && mode === 'compare' }">
      <div v-for="chart in charts" v-show="visibleComparisonPeriod(mobile,mode,chart.category,mobileCategory)" :key="chart.category" class="period-chart-cell">
      <ChartFrame :title="`${title} · ${periodLabel(chart.category)}`" :description="rangeText(chart)">
        <template #actions><span class="period-chart-label">{{ chart.category === primaryCategory ? '主周期 · 收盘快照' : '对照周期' }}</span></template>
        <ChanlunChart :ref="element => setChart(chart.category, element)" :period-category="chart.category" :bars="chart.bars" :result="chart.result" :layers="layers" :show-divergence-history="showDivergenceHistory"
          evidence-enabled :focus="evidenceFocus?.category === chart.category ? evidenceFocus.focus : null" @review="reviewDate(chart.category, $event)"
          :linked-cursor="linkCursor && cursor?.source !== chart.category ? cursor?.range : null" :linked-zoom="linkZoom && zoom?.source !== chart.category ? zoom?.range : null"
          @cursor="cursor = { source: chart.category, range: $event }" @zoom="onZoom(chart.category, $event)" @inspect="inspectDate(chart.category, $event)"
          @viewport="visibleRanges[chart.category] = $event"
          :ma-periods="maPeriods" :ma-available-periods="maAvailablePeriods" :line-widths="lineWidths" :candle-transparency="candleTransparency"
          @update:ma-periods="emit('update:maPeriods', $event)" />
      </ChartFrame>
      </div>
    </div>
    </ChartFrame>
    </div>
    <div v-if="auditVisited" v-show="workspace === 'audit'" class="period-audit-surface" aria-label="周期明细审核">
    <div v-if="comparison && mode !== 'primary'" class="audit-select"><span>明细周期</span><MacSelect v-model="auditCategory" :options="[comparison.primary, comparison.other].map(chart => ({ value: chart.category, label: periodLabel(chart.category) }))" aria-label="明细周期" /></div>
    <p v-if="evidenceFocus && evidenceSource" class="period-note evidence-focus-note"><span>图表定位：{{ evidenceFocus.focus.title }}</span><button @click="evidenceFocus = null">清除定位</button></p>
    <PeriodEvidencePanel v-if="evidenceSource" ref="evidencePanel" :source="evidenceSource" :title="title" :busy="busy || loading" @locate="locateEvidenceDate" @locate-divergence="locateEvidence" />
    <PeriodStructureInspector ref="inspector" :key="auditData.category" :result="auditData.result" :bars="auditData.bars" :title="`${title} · ${periodLabel(auditData.category)}`" :visible-range="visibleRanges[auditData.category]" @locate="locate" />
    </div>
  </section>
</template>

<style scoped>
.period-chart-surface,.period-audit-surface,.period-save-surface{min-width:0}.mobile-chart-switch{margin-bottom:16px}.mobile-chart-switch span{margin-left:6px;font-size:10px;color:var(--text-muted)}
.period-charts { min-width: 0; width: 100%; }
.period-tools, .period-viewbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px 20px; }
.period-tools { border-block: 1px solid var(--border); padding: 14px 0; }
.period-heading, .period-selection { display: flex; align-items: center; gap: 12px; min-width: 0; }
.period-heading strong { font-size: 13px; font-weight: 600; color: var(--text); }
.period-heading span, .period-selection-label, .period-cutoff { font-size: 11px; color: var(--text-muted); }
.period-heading b { color: var(--text); font-weight: 500; margin-left: 6px; }
.period-selection :deep(.mac-select) { width: 128px; }
.period-selection :deep(.mac-select-trigger) { min-height: 32px; }
.period-generate { min-height: 32px; padding: 5px 12px; font-size: 12px; border: 1px solid var(--border); border-radius: 8px; color: var(--text-muted); background: var(--bg-elevated); white-space: nowrap; cursor: pointer; }
.period-generate:disabled { opacity: .45; cursor: default; }
.period-generate:hover:not(:disabled) { color: var(--text); border-color: var(--accent); }
.period-viewbar { padding-top: 14px; }
.period-modes { display: flex; flex-wrap: wrap; gap: 3px; padding: 3px; border-radius: 9px; background: var(--bg-deep); border: 1px solid var(--border); }
.period-modes button { border: 0; background: transparent; padding: 6px 10px; border-radius: 6px; color: var(--text-muted); font-size: 11px; cursor: pointer; }
.period-modes button[aria-pressed="true"] { background: var(--bg-elevated); color: var(--text); box-shadow: 0 1px 3px #0002; }
.period-modes button:focus-visible, .period-generate:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.period-cutoff { display: flex; flex-wrap: wrap; gap: 6px; font-variant-numeric: tabular-nums; }
.period-note, .period-error { font-size: 11px; line-height: 1.8; margin: 10px 0 16px; color: var(--text-muted); overflow-wrap: anywhere; }
.period-error { color: var(--up); }
.period-comparison { display: grid; grid-template-columns: minmax(0, 1fr); gap: 24px; min-width: 0; }
.period-chart-cell { min-width: 0; }
.period-comparison :deep(> :not(:first-child):not(.expanded)) { border-top: 1px solid var(--border); padding-top: 20px; }
.period-chart-label { font-size: 10px; color: var(--text-muted); white-space: nowrap; padding-top: 8px; }
.comparison-options, .audit-select { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; color: var(--text-muted); font-size: 11px; }
.comparison-options label { display: flex; align-items: center; gap: 6px; white-space: nowrap; flex-shrink: 0; }
.comparison-options input[type=checkbox] { width: 14px; height: 14px; min-height: 14px; margin: 0; padding: 0; flex: 0 0 14px; accent-color: #85b5e8; }
.audit-select { padding-top: 18px; }
.audit-select :deep(.mac-select) { width: 140px; }
.evidence-focus-note { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; }
.evidence-focus-note button { min-height: 30px; font-size: 11px; }
@media (min-width: 1100px) {
  .period-comparison.side-by-side { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .period-comparison.side-by-side > .period-chart-cell { margin: 0 !important; border-top: 0 !important; padding-top: 0 !important; }
  .period-comparison.side-by-side :deep(.chart-frame:not(.expanded) > .chart-frame-header) { min-height: 88px !important; box-sizing: border-box; }
}
@media (max-width: 760px) {
  .period-tools, .period-viewbar { align-items: stretch; gap: 12px; }
  .period-heading { justify-content: space-between; width: 100%; }
  .period-selection { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px; width: 100%; }
  .period-selection :deep(.mac-select) { width: 100%; }
  .period-modes { width: 100%; }
  .period-modes button { flex: 1; padding-inline: 6px; white-space: nowrap; }
  .period-chart-label { display: none; }
}
@media (max-width: 1400px) {
  .period-comparison :deep(.indicator-control) { flex-direction: column; align-items: flex-start; gap: 7px; }
  .period-comparison :deep(.indicator-actions) { width: 100%; min-width: 0; overflow-x: auto; }
  .period-comparison :deep(.indicator-options) { flex: 0 0 auto; }
  .period-comparison :deep(.indicator-heading) { flex-wrap: wrap; }
  .period-comparison :deep(.indicator-control > .indicator-heading) { width: 100%; flex-wrap: nowrap; }
  .period-chart-label { display: none; }
}
</style>
