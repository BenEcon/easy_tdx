<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import ChanlunChart from '../components/ChanlunChart.vue'
import ConfirmationReplay from '../components/ConfirmationReplay.vue'
import DecompositionInspector from '../components/DecompositionInspector.vue'
import ExtensionHierarchyInspector from '../components/ExtensionHierarchyInspector.vue'
import ExpansionInspector from '../components/ExpansionInspector.vue'
import ChartFrame from '../components/ChartFrame.vue'
import AdjustPicker from '../components/AdjustPicker.vue'
import MacSelect from '../components/MacSelect.vue'
import NumberStepper from '../components/NumberStepper.vue'
import { movingAverageColor } from '../moving-averages'
import { divergenceEvidence, divergenceName, signalEvidence } from '../divergence-evidence'
import { divergenceFocus, type DivergenceFocus } from '../divergence-focus'
import { expansionFocus } from '../expansion-focus'
import { centreEvidence, centreState, segmentEvidence, segmentsConnected } from '../structure-evidence'
import StockHistoryMenu from '../components/StockHistoryMenu.vue'
import { replayChanlun, replayChanlunComparison, analyzeIndustry, fetchStockIndustries, fetchRecentBars, formatError } from '../api'
import { detectMarket, marketLabel } from '../market'
import { useSelectedStock, recordStockHistory } from '../stock-history'
import type { StockHistoryItem } from '../stock-history'
import type { Bar, Category, ChanlunResult, ChanlunDivergence } from '../types'
import { useMarketPreferences } from '../market-preferences'

const route = useRoute()
const code = useSelectedStock()
const maSettings = ref([5, 10, 20, 30, 60, 120].map(period => ({ period, enabled: period === 5 || period === 10 })))
const maPeriods = computed(() => [...new Set(maSettings.value.filter(item => item.enabled).map(item => item.period))].sort((a, b) => a - b))
function setMAPeriod(index: number, value: number) {
  if (Number.isFinite(value)) maSettings.value[index]!.period = Math.max(1, Math.min(800, Math.round(value)))
}
const industries = ref<Array<{ value: string; label: string }>>([])
const industryCode = ref('')
const industryView = ref('stock')
const industryData = ref<Awaited<ReturnType<typeof analyzeIndustry>> | null>(null)
const industrySnapshot = ref<Awaited<ReturnType<typeof analyzeIndustry>> | null>(null)
const industryAlignment = ref<Awaited<ReturnType<typeof replayChanlunComparison>>['alignment'] | null>(null)
const industryError = ref('')
const industryLoading = ref(false)
let analysisVersion = 0
let industryVersion = 0
async function loadIndustry() {
  const version = ++industryVersion
  industryData.value = null
  industryAlignment.value = null
  if (!industryCode.value || industryView.value === 'stock') { industryLoading.value = false; return }
  industryLoading.value = true
  industryError.value = ''
  try {
    const data = industrySnapshot.value ?? await analyzeIndustry({ stock_market: detectMarket(code.value), stock_code: code.value, board_code: industryCode.value, category: category.value, count: count.value })
    if (version !== industryVersion) return
    industrySnapshot.value = data
    if (!snapshotResult.value || !bars.value.length) return
    const aligned = await replayChanlunComparison({
      stock: { code: snapshotResult.value.code, category: category.value, bars: snapshotBars.value, visible_count: bars.value.length },
      industry: { code: industryCode.value, bars: data.bars },
    })
    if (version === industryVersion) {
      industryData.value = aligned.industry
      industryAlignment.value = aligned.alignment
    }
  } catch (e) { if (version === industryVersion) industryError.value = formatError(e) }
  finally { if (version === industryVersion) industryLoading.value = false }
}
watch([industryCode, industryView], ([nextCode], [previousCode]) => {
  replayVersion++
  replayBusy.value = false
  replayPosition.value = bars.value.length || 1
  if (nextCode !== previousCode) industrySnapshot.value = null
  void loadIndustry()
})
watch(code, () => {
  analysisVersion++
  industryVersion++
  loading.value = false
  result.value = null
  bars.value = []
  industries.value = []
  industryCode.value = ''
  industryData.value = null
}, { flush: 'sync' })
const category = ref<Category>('DAY')
const count = ref(600)
const loading = ref(false)
const error = ref('')
const result = ref<ChanlunResult | null>(null)
const bars = ref<Bar[]>([])
const snapshotBars = ref<Bar[]>([])
const snapshotResult = ref<ChanlunResult | null>(null)
const replayPosition = ref(1)
const replayBusy = ref(false)
const replaySlider = ref<HTMLInputElement | null>(null)
const replayActive = computed(() => bars.value.length < snapshotBars.value.length)
const replayDate = computed(() => (bars.value.at(-1)?.datetime ?? '').replace('T', ' ').replace(/ 00:00:00$/, ''))
let replayVersion = 0
function clearReplay() {
  replayVersion++
  replayBusy.value = false
  snapshotBars.value = []
  snapshotResult.value = null
  industryVersion++
  industrySnapshot.value = null
  industryData.value = null
  industryAlignment.value = null
  industryLoading.value = false
}
watch([code, category, count], clearReplay, { flush: 'sync' })
onBeforeUnmount(() => { analysisVersion++; industryVersion++; replayVersion++ })
async function seekReplay(position: number) {
  if (!snapshotResult.value || replayBusy.value || loading.value || industryLoading.value) return
  const target = Math.max(1, Math.min(snapshotBars.value.length, position))
  const version = ++replayVersion
  const restoreFocus = document.activeElement === replaySlider.value
  replayBusy.value = true
  error.value = ''
  try {
    const request = {
      code: snapshotResult.value.code, category: category.value,
      bars: snapshotBars.value, visible_count: target,
    }
    const comparison = industryView.value !== 'stock' && industrySnapshot.value
      ? await replayChanlunComparison({ stock: request, industry: { code: industryCode.value, bars: industrySnapshot.value.bars } })
      : null
    const next = comparison?.stock ?? (target === snapshotBars.value.length ? snapshotResult.value : await replayChanlun(request))
    if (version !== replayVersion) return
    result.value = next
    bars.value = snapshotBars.value.slice(0, target)
    replayPosition.value = target
    if (comparison) {
      industryData.value = comparison.industry
      industryAlignment.value = comparison.alignment
    } else if (industryView.value !== 'stock') {
      industryData.value = null
      industryAlignment.value = null
    }
  } catch (e) {
    if (version === replayVersion) {
      error.value = formatError(e)
      replayPosition.value = bars.value.length
    }
  } finally {
    if (version === replayVersion) {
      replayBusy.value = false
      await nextTick()
      if (restoreFocus && version === replayVersion) replaySlider.value?.focus({ preventScroll: true })
    }
  }
}
const activeTab = ref<'structure' | 'signals' | 'divergence'>('structure')
const focusedDivergence = ref<DivergenceFocus | null>(null)
const focusToolbar = ref<HTMLElement>()
watch(result, () => { focusedDivergence.value = null }, { flush: 'sync' })
async function locateDivergence(item: ChanlunDivergence) {
  const focus = divergenceFocus(item, bars.value.length, `${divergenceName(item)} · ${item.curr_date ?? ''}${item.status === 'candidate' ? ' · 候选未确认' : ''}`)
  if (focus) await showStructureFocus(focus)
}
async function locateExpansion(candidateId: string) {
  // Resolve from the CURRENT result, never from an event payload retained before replay.
  const candidates = result.value?.expansion_regrouping?.candidates ?? []
  const index = candidates.findIndex(candidate => candidate.id === candidateId)
  if (index < 0) return
  const focus = expansionFocus(candidates[index]!, bars.value.length, `跨中枢候选 ${index + 1} · 自然完成待证`)
  if (focus) await showStructureFocus(focus)
}
async function showStructureFocus(focus: DivergenceFocus) {
  if (replayBusy.value || loading.value || industryLoading.value) return
  if (industryView.value === 'industry') industryView.value = 'stock'
  focusedDivergence.value = focus
  await nextTick()
  focusToolbar.value?.scrollIntoView({ block: 'center' })
  focusToolbar.value?.focus({ preventScroll: true })
}
async function jumpToConfirmation(position: number) {
  await seekReplay(position)
  if (bars.value.length === position && !error.value) {
    await nextTick()
    replaySlider.value?.scrollIntoView({ block: 'center' })
    replaySlider.value?.focus({ preventScroll: true })
  }
}
const { adjustMode } = useMarketPreferences()
watch([category, count, adjustMode], () => {
  clearReplay()
  analysisVersion++
  industryVersion++
  loading.value = false
  result.value = null
  industryData.value = null
}, { flush: 'sync' })
const isSignalReview = computed(() => route.query.review === 'signal')
const reviewSignalLabel = computed(() =>
  route.query.signal === 'BUY' ? '买入信号' : route.query.signal === 'SELL' ? '卖出信号' : '缠论信号',
)
const reviewSignalDate = computed(() => String(route.query.signalDate || '日期未知'))
const reviewSourceName = computed(() => String(route.query.strategyName || route.query.strategyLabel || '缠论买卖点'))

interface LayerState {
  bis: boolean
  zss: boolean
  xds: boolean
  mmds: boolean
  bcs: boolean
}

const layers = ref<LayerState>({
  bis: true,
  zss: true,
  xds: true,
  mmds: true,
  bcs: true,
})

const layerOptions: Array<{ key: keyof LayerState; label: string }> = [
  { key: 'bis', label: '笔' },
  { key: 'zss', label: '中枢' },
  { key: 'xds', label: '线段' },
  { key: 'mmds', label: '买卖点' },
  { key: 'bcs', label: '背离 / 背驰' },
]

const categories: Array<{ value: Category; label: string }> = [
  { value: 'DAY', label: '日线' },
  { value: 'WEEK', label: '周线' },
  { value: 'MONTH', label: '月线' },
  { value: 'MIN_5', label: '5 分钟' },
  { value: 'MIN_15', label: '15 分钟' },
  { value: 'MIN_30', label: '30 分钟' },
  { value: 'MIN_60', label: '60 分钟' },
]
const countOptions = [
  { value: 200, label: '200 根 · 快速', description: '适合快速查看近期结构' },
  { value: 400, label: '400 根 · 均衡', description: '速度与结构完整度平衡' },
  { value: 600, label: '600 根 · 推荐', description: '适合常规缠论分析' },
  { value: 800, label: '800 根 · 完整', description: '覆盖更长历史区间' },
]

const detectedMarket = computed(() =>
  /^\d{6}$/.test(code.value) ? marketLabel(detectMarket(code.value)) : '等待识别',
)

const displayCentres = computed(() => result.value?.structural_centres ?? result.value?.zss ?? [])
const summary = computed(() => {
  if (!result.value) return []
  return [
    { label: '原始 K 线', value: result.value.kline_count },
    { label: '合并 K 线', value: result.value.ckline_count },
    { label: '分型', value: result.value.fractal_count },
    { label: '笔', value: result.value.bi_count },
    { label: '基础中枢', value: displayCentres.value.length },
    { label: '线段', value: result.value.xd_count },
    { label: '买卖点', value: result.value.mmd_count },
    { label: '背离 / 背驰', value: result.value.bcs.filter((item) => item.bc && item.status !== 'superseded').length },
  ]
})

const latestStructure = computed(() => {
  if (!result.value || result.value.bis.length === 0) return '暂无可确认结构'
  const latestBi = result.value.bis[result.value.bis.length - 1]
  const direction = latestBi.direction === 'up' ? '向上笔' : '向下笔'
  const status = (latestBi.structurally_confirmed ?? latestBi.done) ? '已确认' : '进行中'
  const center = displayCentres.value[displayCentres.value.length - 1]
  if (!center) return `当前 ${direction} · ${status}，尚未形成中枢`
  return `当前 ${direction} · ${status}，最近中枢 ${center.zd.toFixed(2)}–${center.zg.toFixed(2)}`
})

function signalLabel(type: string): string {
  const labels: Record<string, string> = {
    '1buy': '一类买点',
    '2buy': '二类买点',
    '3buy': '三类买点',
    '1sell': '一类卖点',
    '2sell': '二类卖点',
    '3sell': '三类卖点',
  }
  return labels[type] ?? type
}

function formatMessage(text: string): string {
  return text.replace(/-?\d+\.\d+/g, (value) => Number(value).toFixed(2))
}

function segmentValue(
  segment: ChanlunResult['xds'][number],
  endpoint: 'start' | 'end',
): number {
  if (endpoint === 'start') {
    return segment.start_value ?? (segment.direction === 'up' ? segment.low : segment.high)
  }
  return segment.end_value ?? (segment.direction === 'up' ? segment.high : segment.low)
}

const segmentSequenceValid = computed(() => {
  return segmentsConnected(result.value?.xds ?? [])
})

function selectHistory(item: StockHistoryItem) {
  code.value = item.code
  category.value = item.category
}

async function runAnalysis() {
  if (!/^\d{6}$/.test(code.value)) {
    error.value = '请输入 6 位证券代码'
    return
  }

  loading.value = true
  clearReplay()
  error.value = ''
  const version = ++analysisVersion
  industryData.value = null
  industries.value = []
  industryCode.value = ''
  industryError.value = ''
  try {
    const market = detectMarket(code.value)
    const nextBars = await fetchRecentBars(market, code.value, category.value, count.value, adjustMode.value)
    if (version !== analysisVersion) return
    if (!nextBars.length) throw new Error('所选范围暂无行情')
    const nextResult = await replayChanlun({
      code: `${market}${code.value}`, category: category.value,
      bars: nextBars, visible_count: nextBars.length,
    })
    if (version !== analysisVersion) return
    bars.value = nextBars
    result.value = nextResult
    snapshotBars.value = nextBars
    snapshotResult.value = nextResult
    replayPosition.value = nextBars.length
    recordStockHistory({ code: code.value, category: category.value })
    activeTab.value = 'structure'
    try {
      const belonging = await fetchStockIndustries(market, code.value)
      if (version !== analysisVersion) return
      industries.value = belonging.data.map((row) => ({ value: String(row.board_code), label: String(row.board_name) }))
      industryCode.value = industries.value[0]?.value ?? ''
    } catch (e) { if (version === analysisVersion) industryError.value = formatError(e) }
  } catch (e) {
    if (version === analysisVersion) error.value = formatError(e)
  } finally {
    if (version === analysisVersion) loading.value = false
  }
}

onMounted(async () => {
  const qSymbol = route.query.symbol as string | undefined
  const qCategory = route.query.category as Category | undefined
  const qCount = Number(route.query.count)
  if (qSymbol) code.value = qSymbol
  if (qCategory) category.value = qCategory
  if (countOptions.some((item) => item.value === qCount)) count.value = qCount

  if (isSignalReview.value && route.query.autoRun === '1' && qSymbol) {
    await runAnalysis()
    if (result.value) activeTab.value = 'signals'
  }
})
</script>

<template>
  <div class="chanlun-view">
    <aside class="analysis-inspector">
      <div class="inspector-title">
        <span class="inspector-symbol">⌘</span>
        <div>
          <h2>结构分析</h2>
          <p>从 K 线递进识别走势结构</p>
        </div>
      </div>

      <section class="inspector-section">
        <h3>标的与周期</h3>
        <div class="field code-field">
          <div class="code-label-row">
            <label>证券代码</label>
            <StockHistoryMenu @select="selectHistory" />
          </div>
          <input v-model.trim="code" autocomplete="off" maxlength="6" inputmode="numeric" placeholder="000001" @keyup.enter="runAnalysis" />
          <span class="market-label">{{ detectedMarket }}</span>
        </div>
        <div class="field">
          <label>分析周期</label>
          <MacSelect v-model="category" :options="categories" aria-label="缠论分析周期" />
        </div>
        <div class="field">
          <label>历史窗口</label>
          <MacSelect v-model="count" :options="countOptions" aria-label="缠论历史窗口" />
        </div>
        <AdjustPicker />
      </section>

      <details class="inspector-section ma-section">
        <summary class="ma-heading"><h3>均线系统</h3><span>周期 · K 线数</span><i aria-hidden="true"></i></summary>
        <div class="ma-settings">
          <div v-for="(item, index) in maSettings" :key="index" class="ma-setting" :class="{ enabled: item.enabled }">
            <label class="ma-toggle">
              <input v-model="item.enabled" type="checkbox" :aria-label="`显示第 ${index + 1} 条均线`" />
              <i :style="{ background: movingAverageColor(item.period) }" aria-hidden="true"></i>
              <span>均线 {{ index + 1 }}</span>
            </label>
            <NumberStepper :model-value="item.period" :min="1" :max="800" :step="1" compact :aria-label="`第 ${index + 1} 条均线周期`" @update:model-value="setMAPeriod(index, $event)" />
          </div>
        </div>
        <p class="ma-help">输入周期后生效；相同周期合并显示。</p>
      </details>

      <section class="inspector-section layer-section">
        <h3>图层</h3>
        <label v-for="item in layerOptions" :key="item.key" class="layer-row">
          <span>{{ item.label }}</span>
          <input v-model="layers[item.key]" type="checkbox" />
        </label>
      </section>

      <div class="method-note">
        <strong>计算管道</strong>
        <p>K 线合并 → 分型 → 笔 → 中枢 → 线段 → 买卖点 → 背驰</p>
      </div>

      <button class="primary analyze-button action-button" :disabled="loading" @click="runAnalysis">
        <span v-if="loading" class="spinner"></span>
        {{ loading ? '正在解析结构…' : '开始分析' }}
      </button>
    </aside>

    <main class="analysis-workspace">
      <section v-if="isSignalReview" class="review-context" aria-label="信号人工复核上下文">
        <div class="review-context-icon">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <circle cx="8.5" cy="8.5" r="4.75" />
            <path d="m12.1 12.1 3.4 3.4M6.4 8.7l1.3 1.3 2.8-3" />
          </svg>
        </div>
        <div class="review-context-copy">
          <span>雷达信号 · 人工复核</span>
          <strong>{{ reviewSourceName }} · {{ code }}</strong>
          <p>{{ reviewSignalLabel }} · {{ reviewSignalDate }} · {{ category }} · 已载入完整结构并定位买卖点</p>
        </div>
        <RouterLink class="review-back" to="/signals">返回信号雷达</RouterLink>
      </section>
      <div v-if="error" class="error-banner">{{ error }}</div>

      <div v-if="!result && !loading" class="empty-state">
        <div class="empty-visual" aria-hidden="true">
          <div class="preview-meta"><span>结构演化</span><small><i></i> 已确认</small></div>
          <svg viewBox="0 0 680 230" preserveAspectRatio="xMidYMid meet">
            <defs>
              <linearGradient id="preview-center-fill" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#a88cdb" stop-opacity=".17" />
                <stop offset="1" stop-color="#6f72d9" stop-opacity=".06" />
              </linearGradient>
              <filter id="preview-line-glow" x="-20%" y="-30%" width="140%" height="160%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            </defs>

            <g class="preview-grid">
              <path d="M38 50H642M38 90H642M38 130H642M38 170H642" />
              <path d="M100 28V184M200 28V184M300 28V184M400 28V184M500 28V184M600 28V184" />
            </g>

            <g class="preview-candles">
              <g><line x1="48" y1="126" x2="48" y2="166"/><rect x="42" y="139" width="12" height="16"/></g>
              <g class="up"><line x1="78" y1="105" x2="78" y2="152"/><rect x="72" y="118" width="12" height="23"/></g>
              <g class="up"><line x1="108" y1="72" x2="108" y2="130"/><rect x="102" y="88" width="12" height="31"/></g>
              <g><line x1="138" y1="64" x2="138" y2="104"/><rect x="132" y="74" width="12" height="17"/></g>
              <g><line x1="168" y1="88" x2="168" y2="140"/><rect x="162" y="96" width="12" height="32"/></g>
              <g><line x1="198" y1="116" x2="198" y2="155"/><rect x="192" y="125" width="12" height="20"/></g>
              <g class="up"><line x1="228" y1="92" x2="228" y2="137"/><rect x="222" y="103" width="12" height="25"/></g>
              <g class="up"><line x1="258" y1="64" x2="258" y2="111"/><rect x="252" y="74" width="12" height="27"/></g>
              <g class="up"><line x1="288" y1="38" x2="288" y2="84"/><rect x="282" y="48" width="12" height="25"/></g>
              <g><line x1="318" y1="60" x2="318" y2="105"/><rect x="312" y="69" width="12" height="25"/></g>
              <g><line x1="348" y1="86" x2="348" y2="132"/><rect x="342" y="96" width="12" height="25"/></g>
              <g><line x1="378" y1="103" x2="378" y2="147"/><rect x="372" y="115" width="12" height="20"/></g>
              <g class="up"><line x1="408" y1="82" x2="408" y2="128"/><rect x="402" y="93" width="12" height="23"/></g>
              <g class="up"><line x1="438" y1="58" x2="438" y2="101"/><rect x="432" y="69" width="12" height="23"/></g>
              <g class="up"><line x1="468" y1="48" x2="468" y2="84"/><rect x="462" y="57" width="12" height="15"/></g>
              <g><line x1="498" y1="69" x2="498" y2="116"/><rect x="492" y="79" width="12" height="25"/></g>
              <g><line x1="528" y1="95" x2="528" y2="137"/><rect x="522" y="106" width="12" height="20"/></g>
              <g class="up"><line x1="558" y1="86" x2="558" y2="128"/><rect x="552" y="97" width="12" height="18"/></g>
              <g class="up"><line x1="588" y1="56" x2="588" y2="105"/><rect x="582" y="66" width="12" height="31"/></g>
              <g class="up"><line x1="618" y1="36" x2="618" y2="78"/><rect x="612" y="44" width="12" height="21"/></g>
            </g>

            <g class="preview-center">
              <rect x="398" y="78" width="148" height="42" rx="7" />
              <path d="M398 88H546M398 110H546" />
              <text x="534" y="103">中枢</text>
            </g>

            <path class="preview-segment" d="M48 166L288 38L378 147L618 36" />
            <path class="preview-stroke" filter="url(#preview-line-glow)" d="M48 166L138 64L198 155L288 38L378 147L468 48L528 137L618 36" />

            <g class="preview-turns">
              <circle cx="48" cy="166" r="4"/><circle cx="138" cy="64" r="4"/>
              <circle cx="198" cy="155" r="4"/><circle cx="288" cy="38" r="4"/>
              <circle cx="378" cy="147" r="4"/><circle cx="468" cy="48" r="4"/>
              <circle cx="528" cy="137" r="4"/><circle cx="618" cy="36" r="4"/>
            </g>
          </svg>
          <div class="preview-legend">
            <span class="candle-key"><i></i>K 线</span>
            <span class="stroke-key"><i></i>笔</span>
            <span class="segment-key"><i></i>线段</span>
            <span class="center-key"><i></i>中枢</span>
          </div>
        </div>
        <h2>观察价格如何形成结构</h2>
        <p>选择标的和周期，系统会把走势拆成笔、线段和中枢，并标出买卖点与背驰。</p>
        <button class="primary" @click="runAnalysis">分析 {{ code }}</button>
      </div>

      <div v-else-if="loading && !result" class="loading-state">
        <span class="large-spinner"></span>
        <p>正在连接行情服务器并构建缠论结构…</p>
      </div>

      <div v-if="result" class="result-workspace" :class="{ refreshing: loading }">
        <section class="summary-strip">
          <div class="summary-context">
            <div class="summary-identity">
              <span class="symbol-name">{{ result.code }}</span>
              <span class="frequency">{{ category }}</span>
            </div>
            <div class="structure-state">
              <span class="state-dot"></span>
              <p>{{ latestStructure }}</p>
            </div>
          </div>
          <div class="summary-metrics">
            <div v-for="item in summary" :key="item.label" class="summary-item">
              <strong>{{ item.value }}</strong>
              <span>{{ item.label }}</span>
            </div>
          </div>
        </section>

        <section class="chart-workspace">
          <p v-if="result.structure_metadata" class="structure-scope">线段基础结构 · 研究版 — 高层级递归尚未完成；买卖点标在极值处，交易依据为确认时间。</p>
          <p v-if="result.structure_metadata?.initial_unresolved_bars" class="structure-scope">开头 {{ result.structure_metadata.initial_unresolved_bars }} 根 K 线缺少前置方向，仅保留行情，不推定包含方向。</p>
          <div v-if="snapshotBars.length" class="replay-toolbar" :aria-busy="replayBusy || industryLoading">
            <strong>{{ replayActive ? '历史回放' : '快照末尾' }}</strong>
            <button :disabled="replayBusy || loading || industryLoading || bars.length <= 1" aria-label="回放上一根 K 线" @click="seekReplay(bars.length - 1)">上一根</button>
            <input ref="replaySlider" v-model.number="replayPosition" type="range" min="1" :max="snapshotBars.length" :disabled="replayBusy || loading || industryLoading" aria-label="K 线回放位置" @change="seekReplay(replayPosition)" />
            <button :disabled="replayBusy || loading || industryLoading || !replayActive" aria-label="回放下一根 K 线" @click="seekReplay(bars.length + 1)">下一根</button>
            <span role="status">{{ replayBusy ? '重新计算…' : `${replayDate} · ${bars.length}/${snapshotBars.length}` }}</span>
            <button :disabled="replayBusy || loading || industryLoading || !replayActive" @click="seekReplay(snapshotBars.length)">返回末尾</button>
            <small>按当前快照回放，不代表历史当天的数据版本；个股与行业以个股所选 K 线时间为共同截止点。</small>
          </div>
          <div class="industry-toolbar">
            <span>所属行业</span>
            <MacSelect v-if="industries.length" v-model="industryCode" :options="industries" aria-label="所属行业" />
            <span v-else>{{ industryError || '暂无行业归属数据' }}</span>
            <div v-if="industries.length" class="industry-modes">
              <button v-for="mode in [{ value: 'stock', label: '个股' }, { value: 'industry', label: '行业' }, { value: 'compare', label: '上下对比' }]" :key="mode.value" :class="{ active: industryView === mode.value }" @click="industryView = mode.value">{{ mode.label }}</button>
            </div>
          </div>
          <div v-if="focusedDivergence && industryView !== 'industry'" ref="focusToolbar" class="focus-toolbar" tabindex="-1" aria-label="图表区间核验">
            <strong>{{ focusedDivergence.title }}</strong>
            <span>{{ focusedDivergence.scope === 'expansion' ? '重组 A / B / C · 不是 MACD 分段或已确认高级别中枢' : focusedDivergence.mode === 'points' ? '前后极值对照（非 A/B/C 分段）' : `${focusedDivergence.ranges.map(range => range.label).join(' / ')} 比较区间` }} · 仅定位，不改变回放时刻</span>
            <button @click="focusedDivergence = null">清除区间定位</button>
          </div>
          <ChartFrame v-if="industryView !== 'industry'" :title="`个股 · ${result.code}`" description="均线与缠论结构叠加；可在下方选择技术指标。">
            <template #actions>
              <div class="chart-legend">
                <span class="legend-bi">笔</span>
                <span class="legend-zs">中枢</span>
                <span class="legend-xd">线段</span>
                <span v-if="layers.xds && result.unfinished_xd" class="legend-pending">候选未确认</span>
                <span class="legend-bc">背驰</span>
              </div>
            </template>
            <ChanlunChart :bars="bars" :result="result" :layers="layers" :ma-periods="maPeriods" :focus="focusedDivergence" />
          </ChartFrame>
          <template v-if="industryView !== 'stock'">
            <p v-if="industryLoading" role="status">正在加载行业结构…</p>
            <p v-else-if="industryError" role="alert">{{ industryError }} <button @click="loadIndustry">重试</button></p>
            <p v-else-if="industryAlignment?.status === 'unavailable'" class="structure-scope" role="status">行业快照在 {{ replayDate }} 及以前没有行情，未补造数据。可向后回放或扩大历史窗口。</p>
            <p v-else-if="industryAlignment" class="structure-scope">共同截止：{{ replayDate }} · 行业最新：{{ industryAlignment.industry_as_of?.replace(' 00:00:00', '') }}{{ industryAlignment.status === 'earlier' ? '（行业数据早于截止时间）' : '（时间已对齐）' }}</p>
            <ChartFrame v-if="industryData && !industryLoading && !industryError" :title="`行业 · ${industries.find(item => item.value === industryCode)?.label}`" description="行业指数 · 不复权；与个股按共同截止时间重新计算。">
              <ChanlunChart :bars="industryData.bars" :result="industryData.result" :layers="layers" :ma-periods="maPeriods" />
            </ChartFrame>
          </template>
        </section>

        <section class="detail-workspace">
          <p class="detail-stock-label">以下结构明细对应个股 {{ result.code }}</p>
          <nav class="detail-tabs" aria-label="缠论结果分类">
            <button :class="{ active: activeTab === 'structure' }" @click="activeTab = 'structure'">
              结构 <span>{{ result.bi_count + displayCentres.length + result.xd_count }}</span>
            </button>
            <button :class="{ active: activeTab === 'signals' }" @click="activeTab = 'signals'">
              买卖点 <span>{{ result.mmd_count }}</span>
            </button>
            <button :class="{ active: activeTab === 'divergence' }" @click="activeTab = 'divergence'">
              背离 / 背驰 <span>{{ result.bcs.filter(item => item.bc && item.status !== 'superseded').length }}</span>
            </button>
          </nav>

          <div v-if="activeTab === 'structure'" class="structure-columns">
            <div class="data-list">
              <h4>最近的笔</h4>
              <div v-for="bi in result.bis.slice(-8).reverse()" :key="bi.index" class="data-row">
                <span class="direction" :class="bi.direction">{{ bi.direction === 'up' ? '↗' : '↘' }}</span>
                <div class="row-primary">
                  <strong>{{ bi.start_date }} → {{ bi.end_date }}</strong>
                  <small>{{ bi.direction === 'up' ? '向上笔' : '向下笔' }} · {{ (bi.structurally_confirmed ?? bi.done) ? '已确认' : '进行中' }}</small>
                  <small v-if="bi.confirmed_date">确认于 {{ bi.confirmed_date }}</small>
                </div>
                <span class="range">{{ bi.low.toFixed(2) }}–{{ bi.high.toFixed(2) }}</span>
              </div>
              <p v-if="result.bis.length === 0" class="no-data">当前窗口未形成有效笔。</p>
            </div>

            <div class="data-list">
              <h4>最近的基础中枢</h4>
              <div v-for="zs in displayCentres.slice(-8).reverse()" :key="zs.index" class="data-row center-row">
                <span class="center-index">{{ zs.index + 1 }}</span>
                <div class="row-primary">
                  <strong>{{ zs.zd.toFixed(2) }} — {{ zs.zg.toFixed(2) }}</strong>
                  <small>{{ zs.start_date }} → {{ zs.end_date || '延续中' }}</small>
                  <small>{{ centreState(zs.state) }}</small>
                </div>
                <span class="range">{{ zs.line_count }} {{ result.structural_centres ? '段' : '笔' }}</span>
                <details v-if="zs.state" class="structure-evidence">
                  <summary>中枢 {{ zs.index + 1 }} · 确认依据</summary>
                  <p v-for="(line, index) in centreEvidence(zs)" :key="index">{{ line }}</p>
                  <ConfirmationReplay :index="zs.formed_index" :total="snapshotBars.length" :busy="replayBusy || loading || industryLoading" :label="`中枢 ${zs.index + 1} 形成`" @seek="jumpToConfirmation" />
                  <ConfirmationReplay :index="zs.exited_index" :total="snapshotBars.length" :busy="replayBusy || loading || industryLoading" :label="`中枢 ${zs.index + 1} 退出`" @seek="jumpToConfirmation" />
                </details>
              </div>
              <p v-if="displayCentres.length === 0" class="no-data">当前窗口尚未形成已确认线段构成的基础中枢。</p>
            </div>

            <section class="segment-list">
              <header>
                <div>
                  <h4>最近的线段</h4>
                  <p>实线为已确认，虚线仅提示候选方向，不参与中枢和买卖点计算。</p>
                </div>
                <span :class="['sequence-status', { valid: segmentSequenceValid }]">
                  <i></i>{{ !result.xds.length ? '暂无确认线段' : segmentSequenceValid ? '端点连接一致' : '连接待核验' }}
                </span>
              </header>
              <div v-if="result.xds.length" class="segment-grid">
                <article
                  v-for="xd in result.xds.slice(-6).reverse()"
                  :key="xd.index"
                  class="segment-card"
                >
                  <span :class="['segment-direction', xd.direction]">
                    {{ xd.direction === 'up' ? '↗' : '↘' }}
                  </span>
                  <div>
                    <strong>线段 {{ xd.index + 1 }}</strong>
                    <small v-if="xd.evidence?.special_inclusion">特殊包含 · 第 71、78 课</small>
                    <small>{{ xd.start_date }} → {{ xd.end_date }}</small>
                  </div>
                  <span class="segment-price">
                    {{ segmentValue(xd, 'start').toFixed(2) }} → {{ segmentValue(xd, 'end').toFixed(2) }}
                  </span>
                  <details class="structure-evidence">
                    <summary>线段 {{ xd.index + 1 }} · 确认依据</summary>
                    <p v-for="(line, index) in segmentEvidence(xd)" :key="index">{{ line }}</p>
                    <ConfirmationReplay :index="xd.confirmed_index" :total="snapshotBars.length" :busy="replayBusy || loading || industryLoading" :label="`线段 ${xd.index + 1}`" @seek="jumpToConfirmation" />
                  </details>
                </article>
              </div>
              <p v-else class="no-data">当前窗口尚未形成已确认线段。</p>
              <p v-if="result.unfinished_xd" class="unfinished-segment">
                <span aria-hidden="true">┄</span> 候选{{ result.unfinished_xd.direction === 'up' ? '向上' : '向下' }}线段 ·
                {{ segmentValue(result.unfinished_xd, 'start').toFixed(2) }} → {{ segmentValue(result.unfinished_xd, 'end').toFixed(2) }}
                <small>端点可能延伸或失效，确认后以实线显示；不是价格预测。</small>
              </p>
            </section>
            <DecompositionInspector :data="result.base_decomposition" :total="snapshotBars.length" :busy="replayBusy || loading || industryLoading" @seek="jumpToConfirmation" />
            <ExtensionHierarchyInspector :data="result.extension_hierarchy" :total="snapshotBars.length" :busy="replayBusy || loading || industryLoading" @seek="jumpToConfirmation" />
            <ExpansionInspector :data="result.expansion_regrouping" :versions="result.regrouping_versions" :total="snapshotBars.length" :visible-count="bars.length" :busy="replayBusy || loading || industryLoading" @seek="jumpToConfirmation" @locate="locateExpansion" />
          </div>

          <div v-else-if="activeTab === 'signals'" class="event-list">
            <div v-for="(signal, index) in result.mmds.slice().reverse()" :key="`${signal.type}-${signal.date}-${index}`" class="event-row">
              <span class="event-tag" :class="signal.type.includes('buy') ? 'buy' : 'sell'">{{ signalLabel(signal.type) }}</span>
              <time>{{ signal.date || '时间未知' }}</time>
              <small v-if="signal.confirmed_date">确认于 {{ signal.confirmed_date }}</small>
              <p>{{ formatMessage(signal.msg) }}</p>
              <details v-if="signal.source === 'confirmed_segment_base_v1'" class="divergence-evidence">
                <summary>查看结构依据</summary>
                <p v-for="line in signalEvidence(signal)" :key="line">{{ line }}</p>
                <ConfirmationReplay :index="signal.confirmed_index" :total="snapshotBars.length" :busy="replayBusy || loading || industryLoading" :label="signalLabel(signal.type)" @seek="jumpToConfirmation" />
              </details>
            </div>
            <p v-if="result.mmds.length === 0" class="no-data">当前窗口没有识别到买卖点。</p>
          </div>

          <div v-else class="event-list">
            <div v-for="(bc, index) in result.bcs.filter(item => item.bc).slice().reverse()" :key="`${bc.type}-${bc.curr_date}-${index}`" class="event-row">
              <span class="event-tag divergence">{{ divergenceName(bc) }}</span>
              <time>{{ bc.curr_date || '时间未知' }}</time>
              <small>{{ bc.status === 'candidate' ? '候选 · 尚未确认' : bc.status === 'superseded' ? '候选已替代或条件失效' : `确认于 ${bc.confirmed_date || '—'}` }} · 对照 {{ bc.prev_date || '—' }}</small>
              <p>{{ formatMessage(bc.msg) }}</p>
              <details class="divergence-evidence">
                <summary>查看判定依据</summary>
                <p v-for="line in divergenceEvidence(bc)" :key="line">{{ line }}</p>
                <button v-if="divergenceFocus(bc, bars.length, '')" :disabled="replayBusy || loading || industryLoading" @click="locateDivergence(bc)">{{ bc.type === 'macd' ? '定位前后极值' : '定位比较区间' }}</button>
                <ConfirmationReplay v-if="bc.status === 'confirmed'" :index="bc.confirmed_index" :total="snapshotBars.length" :busy="replayBusy || loading || industryLoading" :label="divergenceName(bc)" @seek="jumpToConfirmation" />
              </details>
            </div>
            <p v-if="result.bcs.filter(item => item.bc).length === 0" class="no-data">当前窗口没有确认背驰。</p>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.focus-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; padding: 10px 12px; font-size: 11px; border-left: 2px solid var(--accent); background: rgba(74,158,255,.04); }
.focus-toolbar strong { font-weight: 550; }
.focus-toolbar span { color: var(--text-dim); }
.focus-toolbar button { margin-left: auto; min-height: 28px; padding: 4px 9px; font-size: 11px; }
.focus-toolbar:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.structure-evidence { grid-column: 1 / -1; min-width: 0; font-size: 11px; color: var(--text-muted); line-height: 1.7; }
.unfinished-segment { margin-top: 12px; font-size: 11px; color: #a88cdb; line-height: 1.8; font-variant-numeric: tabular-nums; }
.unfinished-segment small { display: block; color: var(--text-muted); font-size: 10px; }
.structure-evidence summary { cursor: pointer; color: var(--accent); padding: 4px 0; }
.structure-evidence p { margin: 5px 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.structure-evidence summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }
.center-row { flex-wrap: wrap; padding: 8px 0; row-gap: 0; }
.center-row > .structure-evidence { flex-basis: 100%; }
.replay-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 10px 0; font-size: 11px; color: var(--text-muted); border-bottom: 1px solid var(--border); }
.replay-toolbar strong { font-size: 11px; font-weight: 500; white-space: nowrap; }
.replay-toolbar button { min-height: 28px; padding: 3px 9px; font-size: 11px; white-space: nowrap; transition: background .15s ease; }
.replay-toolbar input { flex: 1 1 120px; min-width: 90px; max-width: 320px; accent-color: var(--accent); }
.replay-toolbar span { font-variant-numeric: tabular-nums; }
.replay-toolbar small { flex-basis: 100%; color: var(--text-dim); line-height: 1.5; }
.replay-toolbar :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .replay-toolbar button { transition: none; } }
.structure-scope { margin: 0; padding: 10px 14px; color: #a0a5b0; font-size: 12px; line-height: 1.6; border-bottom: 1px solid rgba(255,255,255,.07); }
.detail-stock-label { padding: 12px 14px 0; font-size: 11px; color: var(--text-dim); }
.chart-workspace :deep(.chart-frame + .chart-frame) { margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--border); }
.ma-heading { display: flex; align-items: center; gap: 8px; min-height: 24px; cursor: pointer; list-style: none; }
.ma-heading::-webkit-details-marker { display: none; }
.inspector-section .ma-heading h3 { margin: 0; }
.ma-heading span { margin-left: auto; color: var(--text-dim); font-size: 9px; }
.ma-heading i { width: 5px; height: 5px; margin-right: 3px; border-right: 1px solid var(--text-dim); border-bottom: 1px solid var(--text-dim); transform: rotate(-45deg); transition: transform .15s; }
.ma-section[open] .ma-heading i { transform: rotate(45deg); }
.ma-heading:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }
.ma-settings { display: flex; flex-direction: column; margin-top: 8px; }
.ma-setting { display: grid; grid-template-columns: minmax(0, 1fr) 78px; align-items: center; gap: 14px; min-height: 41px; border-bottom: 1px solid rgba(255,255,255,.045); }
.ma-setting:last-child { border-bottom: 0; }
.ma-toggle { display: flex; align-items: center; gap: 9px; margin: 0; cursor: pointer; color: var(--text-dim); font-size: 11px; white-space: nowrap; }
.ma-setting.enabled .ma-toggle { color: var(--text-muted); }
.ma-toggle i { width: 12px; height: 2px; flex: 0 0 auto; border-radius: 2px; opacity: .35; }
.ma-setting.enabled .ma-toggle i { opacity: 1; }
.ma-help { margin-top: 8px; color: var(--text-dim); font-size: 9px; line-height: 1.5; }
.ma-toggle input { appearance: none; width: 24px; min-height: 14px; height: 14px; padding: 0; margin: 0; border: 0; border-radius: 8px; background: #383b43; box-shadow: none; cursor: pointer; transition: background .15s; }
.ma-toggle input::after { content: ''; display: block; width: 10px; height: 10px; margin: 2px; border-radius: 50%; background: #d7dce4; transition: transform .15s; }
.ma-toggle input:checked { background: #397ab6; }
.ma-toggle input:checked::after { transform: translateX(10px); background: white; }
.ma-toggle input:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.industry-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; font-size: 12px; color: var(--text-muted); }
.industry-toolbar :deep(.mac-select) { width: 180px; }
.industry-toolbar :deep(.mac-select-trigger) { min-height: 28px; padding-top: 3px; padding-bottom: 3px; font-size: 12px; }
.industry-modes { display: flex; flex-shrink: 0; margin-left: auto; gap: 3px; padding: 3px; border: 1px solid var(--border); border-radius: 8px; }
.industry-modes button { padding: 5px 10px; border: 0; border-radius: 5px; background: transparent; color: var(--text-muted); cursor: pointer; }
.industry-modes button.active { background: var(--bg-elevated); color: var(--text); }
.industry-modes button:hover { color: var(--accent); }
.chanlun-view {
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.analysis-inspector {
  width: 286px;
  flex: 0 0 286px;
  display: flex;
  flex-direction: column;
  padding: 16px 16px 12px;
  overflow-y: auto;
  background: rgba(25, 26, 31, 0.9);
  border-right: 1px solid var(--border);
}

.inspector-title {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-bottom: 16px;
}
.inspector-symbol {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  color: #fff;
  background: var(--accent);
  border-radius: 9px;
  box-shadow: 0 6px 16px rgba(10, 132, 255, 0.22);
  font-family: var(--font-mono);
}
.inspector-title h2 { font-size: 14px; font-weight: 650; }
.inspector-title p { margin-top: 2px; color: var(--text-dim); font-size: 10px; }

.inspector-section {
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
}
.inspector-section h3 {
  margin-bottom: 12px;
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.06em;
}
.analysis-inspector .field { margin-bottom: 10px; }
.code-field { position: relative; }
.code-label-row { display: flex; min-height: 23px; align-items: flex-start; justify-content: space-between; gap: 8px; }
.code-field input { padding-right: 68px; font-family: var(--font-mono); }
.market-label {
  position: absolute;
  right: 8px;
  bottom: 7px;
  color: var(--text-dim);
  font-size: 10px;
}

.layer-section { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; }
.layer-section h3 { grid-column: 1 / -1; }
.layer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 26px;
  margin: 0;
  color: var(--text-muted);
  cursor: pointer;
}
.layer-row input {
  appearance: none;
  width: 26px;
  min-height: 16px;
  height: 16px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: #3a3b42;
  box-shadow: none;
  transition: background-color 160ms ease;
}
.layer-row input::after {
  content: '';
  display: block;
  width: 12px;
  height: 12px;
  margin: 2px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
  transition: transform 160ms ease;
}
.layer-row input:checked { background: var(--accent); }
.layer-row input:checked::after { transform: translateX(10px); }

.method-note {
  margin-top: auto;
  padding: 9px 0;
  color: var(--text-dim);
  border-top: 1px solid var(--border);
}
.method-note strong { color: var(--text-muted); font-size: 10px; font-weight: 620; }
.method-note p { margin-top: 4px; font-size: 10px; line-height: 1.45; }
.analyze-button { width: 100%; min-height: 35px; flex-shrink: 0; padding-top: 0; padding-bottom: 0; line-height: 1; }

.spinner,
.large-spinner {
  display: inline-block;
  border: 2px solid rgba(255, 255, 255, 0.28);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}
.spinner { width: 12px; height: 12px; margin-right: 0; vertical-align: 0; }
.large-spinner { width: 24px; height: 24px; border-color: rgba(10,132,255,.2); border-top-color: var(--accent); }

.analysis-workspace {
  position: relative;
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  background:
    linear-gradient(rgba(255,255,255,.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.018) 1px, transparent 1px),
    var(--bg);
  background-size: 34px 34px;
}
.analysis-workspace > .error-banner { margin: 18px 20px 0; padding: 10px 13px; border-radius: var(--radius); }
.review-context {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  margin: 14px 18px 0;
  padding: 10px 12px;
  background: linear-gradient(100deg, rgba(42, 123, 194, .12), rgba(42, 123, 194, .035));
  border: 1px solid rgba(91, 164, 225, .2);
  border-radius: 10px;
}
.review-context-icon {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  color: #9fd0f7;
  background: rgba(70, 150, 217, .12);
  border: 1px solid rgba(109, 180, 237, .18);
  border-radius: 8px;
}
.review-context-icon svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.review-context-copy { min-width: 0; }
.review-context-copy > span { display: block; color: #7fafd5; font-size: 9px; font-weight: 650; letter-spacing: .12em; }
.review-context-copy strong { display: block; margin-top: 2px; color: var(--text); font-size: 12px; font-weight: 620; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.review-context-copy p { margin-top: 2px; color: var(--text-dim); font-size: 10px; }
.review-back { padding: 5px 8px; color: var(--text-muted); border: 1px solid var(--border); border-radius: 6px; font-size: 10px; text-decoration: none; white-space: nowrap; }
.review-back:hover { color: #b9dcff; border-color: rgba(91, 164, 225, .35); }

.empty-state,
.loading-state {
  display: flex;
  min-height: 100%;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 40px;
  text-align: center;
}
.empty-state h2 { margin-top: 22px; font-size: 19px; font-weight: 620; letter-spacing: -0.02em; }
.empty-state > p { max-width: 430px; margin: 8px 0 18px; color: var(--text-dim); font-size: 12px; }
.empty-visual {
  position: relative;
  width: min(680px, 84%);
  aspect-ratio: 680 / 230;
  padding: 25px 16px 10px;
  overflow: hidden;
  background:
    radial-gradient(circle at 58% 28%, rgba(121,185,239,.07), transparent 34%),
    linear-gradient(145deg, rgba(29,31,38,.7), rgba(14,15,19,.42));
  border: 1px solid rgba(255,255,255,.075);
  border-radius: 18px;
  box-shadow: 0 22px 56px rgba(0,0,0,.2), inset 0 1px 0 rgba(255,255,255,.025);
}
.empty-visual::after {
  position: absolute;
  content: '';
  inset: 0;
  pointer-events: none;
  background: linear-gradient(105deg, transparent 28%, rgba(255,255,255,.025) 48%, transparent 66%);
  transform: translateX(-100%);
  animation: preview-sheen 5.8s ease-in-out 1.5s infinite;
}
.empty-visual svg { display: block; width: 100%; height: 100%; overflow: visible; }
.preview-meta {
  position: absolute;
  z-index: 2;
  top: 13px;
  right: 17px;
  left: 17px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  pointer-events: none;
}
.preview-meta > span { color: #8c8e98; font: 8px var(--font-mono); letter-spacing: .14em; }
.preview-meta small { display: flex; align-items: center; gap: 6px; color: #777b86; font-size: 8px; }
.preview-meta small i { width: 5px; height: 5px; background: #6fb2eb; border-radius: 50%; box-shadow: 0 0 0 4px rgba(111,178,235,.08); }
.preview-grid path { fill: none; stroke: rgba(255,255,255,.035); stroke-width: 1; }
.preview-candles line { stroke: rgba(240,118,130,.43); stroke-width: 1; }
.preview-candles rect { fill: rgba(240,118,130,.2); stroke: rgba(240,118,130,.52); stroke-width: 1; rx: 1.5px; }
.preview-candles .up line { stroke: rgba(103,201,166,.43); }
.preview-candles .up rect { fill: rgba(103,201,166,.16); stroke: rgba(103,201,166,.52); }
.preview-center rect { fill: url(#preview-center-fill); stroke: rgba(168,140,219,.55); stroke-width: 1; }
.preview-center path { fill: none; stroke: rgba(168,140,219,.22); stroke-width: 1; stroke-dasharray: 3 5; }
.preview-center text { fill: rgba(199,180,233,.7); font-size: 8px; text-anchor: end; }
.preview-segment {
  fill: none;
  stroke: #a88cdb;
  stroke-width: 1.15;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 4 7;
  opacity: .54;
}
.preview-stroke {
  fill: none;
  stroke: #79b9ef;
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 980;
  stroke-dashoffset: 980;
  opacity: .88;
  animation: preview-draw 1.35s cubic-bezier(.2,.72,.24,1) .12s forwards;
}
.preview-turns circle {
  fill: #b4dcfb;
  stroke: rgba(15,21,28,.92);
  stroke-width: 2;
  opacity: 0;
  transform-box: fill-box;
  transform-origin: center;
  animation: preview-node-in .36s ease-out forwards;
}
.preview-turns circle:nth-child(1){animation-delay:.25s}.preview-turns circle:nth-child(2){animation-delay:.38s}
.preview-turns circle:nth-child(3){animation-delay:.51s}.preview-turns circle:nth-child(4){animation-delay:.64s}
.preview-turns circle:nth-child(5){animation-delay:.77s}.preview-turns circle:nth-child(6){animation-delay:.9s}
.preview-turns circle:nth-child(7){animation-delay:1.03s}.preview-turns circle:nth-child(8){animation-delay:1.16s}
.preview-legend {
  position: absolute;
  z-index: 2;
  right: 18px;
  bottom: 11px;
  display: flex;
  gap: 14px;
  color: #7f828d;
  font-size: 8px;
}
.preview-legend span { display: inline-flex; align-items: center; gap: 5px; }
.preview-legend i { display: inline-block; width: 12px; height: 1px; background: #60636d; }
.preview-legend .candle-key i { width: 5px; height: 9px; background: rgba(103,201,166,.22); border: 1px solid rgba(103,201,166,.55); border-radius: 1px; }
.preview-legend .stroke-key i { background: #79b9ef; }
.preview-legend .segment-key i { background: #a88cdb; }
.preview-legend .center-key i { height: 6px; background: rgba(168,140,219,.14); border: 1px solid rgba(168,140,219,.45); border-radius: 2px; }
@keyframes preview-draw { to { stroke-dashoffset: 0; } }
@keyframes preview-node-in { from { opacity: 0; transform: scale(.35); } to { opacity: 1; transform: scale(1); } }
@keyframes preview-sheen { 0%,55% { transform: translateX(-100%); } 78%,100% { transform: translateX(100%); } }
@media (prefers-reduced-motion: reduce) {
  .empty-visual::after,.preview-stroke,.preview-turns circle { animation: none; }
  .preview-stroke { stroke-dashoffset: 0; }
  .preview-turns circle { opacity: 1; }
}
.loading-state { gap: 13px; color: var(--text-dim); font-size: 12px; }

.result-workspace {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 20px 28px;
  transition: opacity 180ms ease;
}
.result-workspace.refreshing { opacity: 0.55; pointer-events: none; }

.summary-strip {
  display: grid;
  min-height: 112px;
  overflow: hidden;
  grid-template-columns: 272px 1fr;
  background:
    linear-gradient(135deg, rgba(10,132,255,.055), transparent 38%),
    rgba(25, 26, 31, 0.9);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 12px 34px rgba(0,0,0,.16), 0 1px 0 rgba(255,255,255,.025) inset;
}
.summary-context {
  display: flex;
  min-width: 0;
  justify-content: center;
  flex-direction: column;
  padding: 16px 18px;
  border-right: 1px solid var(--border);
}
.summary-identity { display: flex; align-items: center; }
.symbol-name { font-family: var(--font-mono); font-size: 17px; font-weight: 660; letter-spacing: -.02em; }
.frequency { margin-left: 8px; padding: 3px 7px; color: #78b8ff; background: rgba(10,132,255,.12); border: 1px solid rgba(10,132,255,.16); border-radius: 6px; font-size: 9px; }
.structure-state { display: flex; align-items: flex-start; gap: 8px; margin-top: 11px; }
.structure-state p { color: var(--text-muted); font-size: 10px; line-height: 1.5; }
.state-dot { width: 6px; height: 6px; flex: 0 0 auto; margin-top: 4px; border-radius: 50%; background: #5aa9ff; box-shadow: 0 0 0 4px rgba(10,132,255,.1); }
.summary-metrics { display: grid; grid-template-columns: repeat(4, minmax(68px, 1fr)); gap: 6px; padding: 9px; }
.summary-item { display: flex; min-height: 44px; align-items: center; justify-content: center; flex-direction: column; background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.035); border-radius: 8px; }
.summary-item strong { color: #e9e9ed; font-family: var(--font-mono); font-size: 15px; font-weight: 590; font-variant-numeric: tabular-nums; }
.summary-item span { margin-top: 2px; color: var(--text-dim); font-size: 9px; }

.chart-workspace,
.detail-workspace {
  background: rgba(22, 23, 28, 0.91);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 12px 32px rgba(0,0,0,.13);
}
.chart-workspace { padding: 14px 16px 8px; }
.section-bar { display: flex; align-items: center; justify-content: space-between; min-height: 42px; padding: 0 2px 8px; }
.section-bar h3 { font-size: 12px; font-weight: 620; }
.section-bar p { margin-top: 2px; color: var(--text-dim); font-size: 9px; }
.chart-legend { display: flex; flex-wrap: wrap; gap: 8px 12px; color: var(--text-dim); font-size: 9px; }
.chart-legend .legend-pending::before { height: 0; width: 12px; border-top: 1px dashed #a88cdb; border-radius: 0; vertical-align: 3px; }
.chart-legend span::before { content: ''; display: inline-block; width: 7px; height: 7px; margin-right: 5px; border-radius: 2px; vertical-align: -1px; }
.legend-bi::before { background: #79b9ef; }.legend-zs::before { background: #4a9eff; }.legend-xd::before { background: #a88cdb; }.legend-bc::before { background: transparent; border: 1px solid #d9a3ff; transform: rotate(45deg); }

.detail-workspace { overflow: hidden; min-height: 220px; }
.detail-tabs { display: flex; align-items: center; gap: 4px; min-height: 48px; padding: 8px 12px; border-bottom: 1px solid var(--border); }
.detail-tabs button { min-height: 30px; border-color: transparent; background: transparent; box-shadow: none; color: var(--text-dim); }
.detail-tabs button:hover { background: rgba(255,255,255,.04); color: var(--text-muted); }
.detail-tabs button.active { color: var(--text); background: rgba(255,255,255,.075); border-color: var(--border); }
.detail-tabs button span { margin-left: 5px; color: var(--text-dim); font-family: var(--font-mono); font-size: 9px; }

.structure-columns { display: grid; grid-template-columns: 1fr 1fr; }
.data-list { min-width: 0; padding: 15px 16px 18px; }
.data-list + .data-list { border-left: 1px solid var(--border); }
.data-list h4 { margin-bottom: 10px; color: var(--text-dim); font-size: 9px; font-weight: 650; letter-spacing: .06em; }
.data-row { display: flex; align-items: center; gap: 10px; min-height: 44px; border-bottom: 1px solid rgba(255,255,255,.055); }
.data-row:last-child { border-bottom: 0; }
.direction { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 7px; font-size: 14px; }
.direction.up { color: var(--up); background: rgba(255,94,104,.1); }.direction.down { color: var(--down); background: rgba(48,209,123,.1); }
.center-index { display: grid; place-items: center; width: 24px; height: 24px; color: #64adff; background: var(--accent-soft); border-radius: 7px; font-family: var(--font-mono); font-size: 10px; }
.row-primary { display: flex; min-width: 0; flex: 1; flex-direction: column; }
.row-primary strong { overflow: hidden; text-overflow: ellipsis; color: var(--text-muted); font-family: var(--font-mono); font-size: 10px; font-weight: 520; white-space: nowrap; }
.row-primary small { margin-top: 2px; overflow: hidden; text-overflow: ellipsis; color: var(--text-dim); font-size: 9px; white-space: nowrap; }
.range { color: var(--text-muted); font-family: var(--font-mono); font-size: 9px; }

.segment-list { grid-column: 1 / -1; padding: 15px 16px 17px; border-top: 1px solid var(--border); }
.segment-list > header { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 11px; }
.segment-list h4 { color: var(--text-muted); font-size: 10px; font-weight: 650; letter-spacing: .04em; }
.segment-list header p { margin-top: 2px; color: var(--text-dim); font-size: 9px; }
.sequence-status { display: inline-flex; min-height: 24px; align-items: center; gap: 7px; padding: 0 9px; color: #ffb84d; background: rgba(255,159,10,.08); border: 1px solid rgba(255,159,10,.18); border-radius: 999px; font-size: 9px; white-space: nowrap; }
.sequence-status i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; box-shadow: 0 0 0 3px rgba(255,159,10,.1); }
.sequence-status.valid { color: #56d98d; background: rgba(48,209,88,.07); border-color: rgba(48,209,88,.17); }
.sequence-status.valid i { box-shadow: 0 0 0 3px rgba(48,209,88,.09); }
.segment-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: 7px; }
.segment-card { display: grid; min-width: 0; min-height: 52px; align-items: center; grid-template-columns: 28px minmax(0,1fr) auto; gap: 9px; padding: 7px 10px; background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.045); border-radius: 9px; }
.segment-direction { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 7px; font-size: 14px; }
.segment-direction.up { color: var(--up); background: rgba(255,94,104,.09); }
.segment-direction.down { color: var(--down); background: rgba(48,209,123,.09); }
.segment-card > div { display: flex; min-width: 0; flex-direction: column; }
.segment-card strong { color: var(--text-muted); font-size: 10px; font-weight: 580; }
.segment-card small { margin-top: 2px; overflow: hidden; color: var(--text-dim); font-family: var(--font-mono); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.segment-price { color: #c8c9d0; font-family: var(--font-mono); font-size: 9px; font-variant-numeric: tabular-nums; white-space: nowrap; }

.event-list { padding: 8px 14px 16px; }
.event-row { display: grid; align-items: center; grid-template-columns: 82px 112px 1fr; gap: 12px; min-height: 48px; padding: 0 8px; border-bottom: 1px solid rgba(255,255,255,.05); transition: background-color 120ms ease; }
.event-row:hover { background: rgba(255,255,255,.022); }
.event-row:last-child { border-bottom: 0; }
.event-row > small { grid-column: 2 / -1; color: var(--text-dim); font-size: 10px; }
.event-row > p, .divergence-evidence { grid-column: 1 / -1; }
.divergence-evidence { padding-bottom: 10px; color: var(--text-muted); font-size: 10px; line-height: 1.8; }
.divergence-evidence summary { cursor: pointer; color: var(--accent); }
.event-tag { width: fit-content; padding: 4px 8px; border: 1px solid transparent; border-radius: 999px; font-size: 9px; font-weight: 620; }
.event-tag.buy { color: #ff858d; background: rgba(255,94,104,.09); border-color: rgba(255,94,104,.13); }.event-tag.sell { color: #61dfa0; background: rgba(48,209,123,.09); border-color: rgba(48,209,123,.13); }.event-tag.divergence { color: #d9a3ff; background: rgba(191,90,242,.1); border-color: rgba(191,90,242,.14); }
.event-row time { color: var(--text-dim); font-family: var(--font-mono); font-size: 9px; }
.event-row p { color: var(--text-muted); font-size: 10px; }
.no-data { padding: 24px 0; color: var(--text-dim); font-size: 10px; text-align: center; }

@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1150px) {
  .summary-strip { grid-template-columns: 230px 1fr; }
  .segment-grid { grid-template-columns: 1fr; }
}
</style>
