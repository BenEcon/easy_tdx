<script setup lang="ts">
import { queryAction } from '../query-origin'
import ResultDataProvenance from '../components/ResultDataProvenance.vue'
import RadarReviewContext from '../components/RadarReviewContext.vue'
import { readRadarReview, sameReviewInput, sameReviewStrategy } from '../radar-review'
// 回测主页面：左配置面板 / 右报告面板。
// 编排：点击「开始回测」→ 自动取行情 → 回测 → 展示 K线+净值+指标+成交。
// 取行情已整合进「开始回测」（不再有单独的取行情按钮）。

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { readResearchNavigation, canOpenBacktest } from '../research-navigation'
import ResearchEntryContext from '../components/ResearchEntryContext.vue'
import { useAuth } from '../auth'
import { savedStrategyInput, savedStrategyRequestId } from '../saved-strategy-input'
import { readOptimizationQuery } from '../execution-context'
import { researchInputFields } from '../research-input'

import ChartFrame from '../components/ChartFrame.vue'
import { useMobileSettings } from '../mobile-settings'
import EquityChart from '../components/EquityChart.vue'
import GradeDetails from '../components/GradeDetails.vue'
import KlineChart from '../components/KlineChart.vue'
import MacSelect from '../components/MacSelect.vue'
import MetricTable from '../components/MetricTable.vue'
import { resultBasis } from '../metric-state'
import NumberStepper from '../components/NumberStepper.vue'
import StrategyPicker from '../components/StrategyPicker.vue'
import SymbolPicker from '../components/SymbolPicker.vue'
import TradeTable from '../components/TradeTable.vue'
import { fetchSavedStrategy, formatError, saveStrategy, updateSavedStrategy } from '../api'
import { detectMarket } from '../market'
import { useMarketPreferences } from '../market-preferences'
import { useSelectedStock } from '../stock-history'
import { gradeBacktestResult } from '../grading'
import { performanceSnapshot } from '../performance-context'
import type { Category, ExecutionMode, SavedStrategy, SavedStrategyCreate } from '../types'
import { useBacktestStore } from '../stores/backtest'
import CloudResearchArchives from '../components/CloudResearchArchives.vue'
import { detachBacktest, validateBacktestArchive } from '../backtest-archive'
import type { ArchiveDraft } from '../cloud-archives'

const store = useBacktestStore()
function captureBacktest():ArchiveDraft {
  const saved=store.completed
  if(!saved||store.running||saved.owner!==currentUser.value?.id)throw Error('当前没有可保存的完整回测，请重新运行')
  const title=`${saved.request.symbol} · ${saved.request.category} · ${saved.request.strategy}`
  const payload=validateBacktestArchive(detachBacktest({format:'backtest-research-v1',title,savedAt:saved.finishedAt,
    request:saved.request,metadata:saved.metadata,result:saved.result,...(saved.radarSource?{radarSource:saved.radarSource}:{})}))
  return {kind:'backtest',name:title,note:'',payload}
}
function exportBacktest(){
  try{
    const draft=captureBacktest(),url=URL.createObjectURL(new Blob([JSON.stringify(draft.payload,null,2)],{type:'application/json'}))
    const anchor=document.createElement('a');anchor.href=url;anchor.download=`tdx-backtest-${Date.now()}.json`;anchor.click()
    setTimeout(()=>URL.revokeObjectURL(url),1000)
  }catch(error){saveMsg.value=formatError(error)}
}
const { mobile, settingsOpen } = useMobileSettings(() => Boolean(store.result))
const { adjustMode } = useMarketPreferences()
const route = useRoute()
const {currentUser} = useAuth()
const isSavedLoad = computed(() => route.query.savedStrategyId !== undefined)
const isOptimizationLoad=computed(()=>route.query.optimizationContext!==undefined)
const isContextLoad=computed(()=>isSavedLoad.value||isOptimizationLoad.value)
const savedLoadState = ref<'idle'|'loading'|'ready'|'error'>('idle')
const savedLoadName = ref('')
const savedLoadWarnings = ref<string[]>([])
const catalogLoading = ref(true), catalogError = ref(false)
const entryContext = computed(() => readResearchNavigation(route.query))
const entryError = computed(() => entryContext.value.error || (entryContext.value.value && !canOpenBacktest(entryContext.value.value.target) ? '指数与板块请在缠论结构中分析，不能当作普通股票回测' : ''))

// SymbolPicker 实例引用，用于触发取行情
const symbolPicker = ref<InstanceType<typeof SymbolPicker> | null>(null)

// 镜像 SymbolPicker 的代码/周期/日期，与 SymbolPicker 通过 v-model 双向同步。
// 初始值与 SymbolPicker 默认一致；onMounted 时若 URL query 带了寻优页传来的值则覆盖。
const code = useSelectedStock()
const category = ref<Category>('DAY')
function isoDaysFromNow(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}
const startDate = ref('2020-01-06')
const endDate = ref(isoDaysFromNow(0))

// 表单状态（v-model 给子组件）
const strategy = ref('ma_cross')
const params = ref<Record<string, number | string | boolean>>({})
const cash = ref(1000000)
const commission = ref(0.0003)
const minCommission = ref(5)
const stampTax = ref(0.001)
const slippage = ref(0)
const execution = ref<ExecutionMode>('next_open')

// 成交价模式（精简为 开盘价/收盘价）
const EXECUTIONS: { value: ExecutionMode; label: string }[] = [
  { value: 'next_open', label: '开盘价' },
  { value: 'next_close', label: '收盘价' },
]

const isSignalReview = computed(() => route.query.review === 'signal')
const reviewContext = computed(() => readRadarReview(route.query))
const reviewInputMatches = computed(() => sameReviewInput(reviewContext.value.value, code.value, category.value, adjustMode.value))
const reviewMatches = computed(() => reviewInputMatches.value && sameReviewStrategy(reviewContext.value.value, strategy.value, params.value))
const reviewStatus = computed(() => store.error ? `复核未完成：${store.error}` : store.running || symbolPicker.value?.loading ? (reviewContext.value.value?.evidence?'正在读取原任务行情并核验…':'正在按原截止时间重新取数核验…') : store.result ? '已生成当前策略回测；资金、成本和执行方式采用本页设置，回测成交不等于原雷达信号。' : '尚未生成本次复核结果。')
const reviewSourceName = computed(() => String(route.query.strategyName || route.query.strategyLabel || strategy.value))
const editStrategyId = computed(() => typeof route.query.editStrategyId === 'string' ? route.query.editStrategyId : '')
const editingRecord = ref<SavedStrategy | null>(null)
const isStrategyEdit = computed(() => Boolean(editStrategyId.value))
const isStrategyCopyEdit = computed(() => route.query.editMode === 'copy')

let routeGeneration = 0
async function loadRoute() {
  const generation = ++routeGeneration
  const initialInputVersion = inputGeneration, initialOwner = currentUser.value?.id
  catalogLoading.value = true; catalogError.value = false
  showSaveForm.value=false;saving.value=false;saveMsg.value=''
  store.clearResult()
  editingRecord.value = null
  savedLoadState.value = isContextLoad.value ? 'loading' : 'idle'
  savedLoadName.value = ''
  savedLoadWarnings.value = []
  if (isContextLoad.value) store.setOhlcv([], '', null, null)
  if (route.query.researchContext !== undefined) {
    store.setOhlcv([], '', null, null)
    if (entryError.value) { catalogLoading.value=false;catalogError.value=true;store.error = entryError.value; return }
  }
  if (isSignalReview.value) {
    store.clearResult()
    store.setOhlcv([], '', null, null)
    if (!reviewContext.value.value) { catalogLoading.value=false;catalogError.value=true;store.error = reviewContext.value.error; return }
  }
  try {
    await store.loadStrategies()
    if (generation !== routeGeneration || currentUser.value?.id !== initialOwner) return
    if (initialInputVersion !== inputGeneration) throw Error('载入期间参数已修改，已保留当前输入；请确认后重新载入')
    if (!store.strategies.length) throw Error('策略目录为空，请重试')
  } catch(e) {
    if(generation === routeGeneration) {
      catalogError.value=true;savedLoadState.value='error'
      store.error=`载入执行配置失败：${formatError(e)}`
    }
    return
  } finally {
    if(generation === routeGeneration)catalogLoading.value=false
  }
  if (generation !== routeGeneration) return

  if (isContextLoad.value) {
    const owner = currentUser.value?.id
    try {
      if (!owner) throw Error('请先登录再载入策略')
      const id = isOptimizationLoad.value?'':savedStrategyRequestId(route.query)
      await nextTick()
      const inputVersion = inputGeneration
      const record = isOptimizationLoad.value?null:await fetchSavedStrategy(id, owner)
      if (generation !== routeGeneration || currentUser.value?.id !== owner) return
      if (inputVersion !== inputGeneration) throw Error('载入期间参数已修改，请从策略库重新载入')
      if (record && record.id !== id) throw Error('返回的策略与所选记录不一致')
      const input = record?savedStrategyInput(record, {category:category.value,adjust:adjustMode.value,startDate:startDate.value,endDate:endDate.value,
        cash:cash.value,commission:commission.value,minCommission:minCommission.value,stampTax:stampTax.value,slippage:slippage.value,execution:execution.value},store.strategies.map(s=>s.name))
        :readOptimizationQuery(route.query,store.strategies.map(s=>s.name))
      code.value=input.code;category.value=input.category;adjustMode.value=input.adjust
      startDate.value=input.startDate;endDate.value=input.endDate;strategy.value=input.strategy
      cash.value=input.cash;commission.value=input.commission;minCommission.value=input.minCommission
      stampTax.value=input.stampTax;slippage.value=input.slippage;execution.value=input.execution
      await nextTick()
      if (generation !== routeGeneration || currentUser.value?.id !== owner) return
      params.value=input.params
      savedLoadName.value=record?.name??'寻优结果配置';savedLoadWarnings.value=input.warnings;savedLoadState.value='ready'
    } catch(e) {
      if(generation===routeGeneration){savedLoadState.value='error';store.error=formatError(e)}
    }
    return
  }

  if (entryContext.value.value) {
    const entry = entryContext.value.value
    code.value = entry.target.code
    category.value = entry.category
    adjustMode.value = entry.adjust
    return
  }

  // 从 URL query 读取寻优页传来的 strategy + params（跳转自动填充）
  const qStrategy = route.query.strategy as string | undefined
  const qParams = route.query.params as string | undefined
  if (qStrategy) {
    strategy.value = qStrategy
    // 等待 StrategyPicker 的 watch(selectedSchema) 触发完默认值重置后，
    // 再用 query 的 params 覆盖，避免被 watch 重置掉
    await nextTick()
    if (generation !== routeGeneration) return
  }
  if (qParams) {
    try {
      params.value = JSON.parse(qParams) as Record<string, number | string | boolean>
    } catch {
      // query 参数解析失败，忽略
    }
  }

  // 从 URL query 回填标的代码 / 周期 / 日期范围（寻优页「查看」跳转带来）。
  // 各字段独立 if 守卫：老书签（只有 strategy/params）仍保持默认值，向后兼容。
  const qSymbol = route.query.symbol as string | undefined
  const qStartDate = route.query.startDate as string | undefined
  const qEndDate = route.query.endDate as string | undefined
  const qCategory = route.query.category as Category | undefined
  if (qSymbol) code.value = qSymbol
  if (qStartDate) startDate.value = qStartDate
  if (qEndDate) endDate.value = qEndDate
  if (qCategory) category.value = qCategory
  const qAdjust = route.query.adjust
  if (qAdjust === 'QFQ' || qAdjust === 'HFQ' || qAdjust === 'NONE') adjustMode.value = qAdjust
  if (reviewContext.value.value) {
    const review = reviewContext.value.value
    code.value = review.symbol; category.value = review.category; adjustMode.value = review.adjust
    strategy.value = review.strategy
    await nextTick()
    if (generation !== routeGeneration) return
    params.value = { ...review.params }
    endDate.value = review.asOf.slice(0, 10)
  }

  if (editStrategyId.value) {
    try {
      const record = await fetchSavedStrategy(editStrategyId.value, currentUser.value?.id)
      if (generation !== routeGeneration) return
      editingRecord.value = record
      const trade = editingRecord.value.trade_config
      if (typeof trade.cash === 'number') cash.value = trade.cash
      if (typeof trade.commission === 'number') commission.value = trade.commission
      if (typeof trade.min_commission === 'number') minCommission.value = trade.min_commission
      if (typeof trade.stamp_tax === 'number') stampTax.value = trade.stamp_tax
      if (typeof trade.slippage === 'number') slippage.value = trade.slippage
      if (trade.execution === 'next_open' || trade.execution === 'next_close') execution.value = trade.execution
    } catch (e) {
      if(generation===routeGeneration) store.error = `读取待修改策略失败：${formatError(e)}`
    }
  }

  // New scans use frozen task inputs; legacy scans explicitly refetch to cutoff.
  if (isSignalReview.value && route.query.autoRun === '1' && qSymbol) {
    await nextTick()
    if (generation !== routeGeneration) return
    await onRun()
  }
}
onMounted(loadRoute)
watch(() => route.fullPath, () => { if (route.path === '/') void loadRoute() })

// 取行情 + 回测 串联（点击「开始回测」触发）
async function onRun(manual = false) {
  if(catalogLoading.value || catalogError.value){store.error='策略目录及执行配置尚未有效载入，请重新载入';return}
  if(isContextLoad.value && savedLoadState.value!=='ready'){store.error='执行配置尚未有效载入，请从来源重新打开';return}
  if (entryError.value) { store.error = entryError.value; return }
  if (isSignalReview.value && !reviewContext.value.value) { store.error = reviewContext.value.error; return }
  store.error = ''
  const version = inputGeneration
  const request = { strategy: strategy.value, params: { ...params.value }, cash: cash.value,
    commission: commission.value, min_commission:minCommission.value, stamp_tax:stampTax.value, slippage: slippage.value, execution: execution.value }
  // 1. 先取行情（SymbolPicker.loadBars 会校验并填充 store.ohlcv）
  const ok = await symbolPicker.value?.loadBars(manual)
  if (!ok || version !== inputGeneration) return // 不将后来修改的参数套到已提交行情
  // 2. 再回测
  await queryAction(manual)(() => store.run(request))
}
let inputGeneration = 0
watch([code, category, adjustMode, startDate, endDate, strategy, params, cash, commission, minCommission, stampTax, slippage, execution], () => {
  inputGeneration++
  store.clearResult()
}, { deep: true, flush: 'sync' })
onBeforeUnmount(() => { routeGeneration++; inputGeneration++; store.clearResult() })
watch(()=>currentUser.value?.id,()=>{
  catalogLoading.value=false;catalogError.value=true
  routeGeneration++;inputGeneration++;store.clearResult();store.setOhlcv([], '', null, null)
  showSaveForm.value=false;saving.value=false;saveMsg.value='';editingRecord.value=null
  savedLoadState.value='error';savedLoadName.value='';savedLoadWarnings.value=[]
},{flush:'sync'})

// ── 保存策略（把当前结果 + 配置 + 上下文存进策略库）──────────────────────────
const showSaveForm = ref(false)
const saving = ref(false)
const saveName = ref('')
const saveTags = ref('')
const saveNotes = ref('')
const saveMsg = ref('') // 保存后提示（成功/失败）

const strategyLabel = computed(
  () => store.strategies.find((s) => s.name === strategy.value)?.label ?? strategy.value,
)

// 评级：基于完整 Performance，6 维度评分 + 一票否决。
// total_return 不直接计入评分（只通过卡玛/夏普间接体现），
// 体现「哪怕近期收益率高，长期风险大也该低评」的产品诉求。
const grade = computed(() =>
  store.result ? gradeBacktestResult(store.result) : null,
)

// 当前股票完整代码（市场:6位），从 SymbolPicker 同步来的 code 是纯数字，
// 需要带上市场前缀。复用 market.ts 的 detectMarket（与 SymbolPicker /
// StocksPicker 同一套规则），避免分叉导致 ETF/基金（5 开头）等被错判市场。
function fullSymbol(code6: string): string {
  return `${detectMarket(code6)}:${code6}`
}

function openSaveForm() {
  saveName.value = editingRecord.value?.name || `${strategyLabel.value} · ${code.value}`
  saveTags.value = editingRecord.value?.tags.join('，') || ''
  saveNotes.value = editingRecord.value?.notes || ''
  saveMsg.value = ''
  showSaveForm.value = true
}

async function onSave() {
  if (!store.result || !saveName.value.trim() || saving.value) return
  const owner=currentUser.value?.id, generation=routeGeneration
  if(!owner){saveMsg.value='请先登录再保存';return}
  saving.value = true
  saveMsg.value = ''
  try {
    const payload: SavedStrategyCreate = {
      name: saveName.value.trim(),
      kind: 'single',
      strategy: strategy.value,
      strategy_label: strategyLabel.value,
      params: params.value,
      context: {
        symbol: fullSymbol(code.value),
        category: category.value,
        start_date: startDate.value,
        end_date: endDate.value,
        adjust: adjustMode.value,
        ...researchInputFields(store.barsContext),
      },
      trade_config: {
        cash: cash.value,
        commission: commission.value,
        min_commission: minCommission.value,
        stamp_tax: stampTax.value,
        slippage: slippage.value,
        execution: execution.value,
      },
      snapshot: performanceSnapshot({ ...store.result.performance }, resultBasis(store.result)),
      tags: saveTags.value
        .split(/[,，]/)
        .map((t) => t.trim())
        .filter(Boolean),
      notes: saveNotes.value,
    }
    if (editingRecord.value) {
      const saved = await updateSavedStrategy(editingRecord.value.id, payload, owner)
      if(generation!==routeGeneration||currentUser.value?.id!==owner)return
      editingRecord.value = saved
      saveMsg.value = '✓ 策略修改已保存'
    } else {
      await saveStrategy(payload, owner)
      if(generation!==routeGeneration||currentUser.value?.id!==owner)return
      saveMsg.value = '✓ 已保存到策略库'
    }
    showSaveForm.value = false
  } catch (e) {
    if(generation===routeGeneration&&currentUser.value?.id===owner)saveMsg.value = `保存失败：${formatError(e)}`
  } finally {
    if(generation===routeGeneration&&currentUser.value?.id===owner)saving.value = false
  }
}
</script>

<template>
  <div class="backtest-view">
    <!-- 左栏：配置 -->
    <button v-if="mobile" class="mobile-inspector-toggle" type="button" :aria-expanded="settingsOpen" aria-controls="backtest-settings" @click="settingsOpen = !settingsOpen">
      <span>分析设置</span><span>{{ settingsOpen ? '收起' : '展开' }}</span>
    </button>
    <aside v-show="!mobile || settingsOpen" id="backtest-settings" class="config-panel">
      <section class="panel-section">
        <h3>行情数据</h3>
        <SymbolPicker
          ref="symbolPicker"
          v-model:code="code"
          v-model:category="category"
          v-model:start-date="startDate"
          v-model:end-date="endDate"
          :review="reviewInputMatches ? reviewContext.value : null"
        />
      </section>

      <section class="panel-section">
        <h3>策略</h3>
        <StrategyPicker
          v-if="store.strategies.length"
          :strategies="store.strategies"
          :suspend-defaults="catalogLoading || catalogError"
          v-model:strategy="strategy"
          v-model:params="params"
        />
        <p v-else class="loading-text">加载策略中…</p>
      </section>

      <section class="panel-section">
        <h3>资金与成本</h3>
        <div class="field">
          <label>初始资金</label>
          <NumberStepper v-model="cash" :min="1" :step="10000" aria-label="初始资金" />
        </div>
        <div class="row">
          <div class="field">
            <label>佣金率</label>
            <NumberStepper v-model="commission" :min="0" :max="0.01" :step="0.0001" aria-label="佣金率" />
          </div>
          <div class="field">
            <label>滑点</label>
            <NumberStepper v-model="slippage" :min="0" :max="0.05" :step="0.001" aria-label="滑点" />
          </div>
        </div>
        <div class="row">
          <div class="field"><label>最低佣金</label><NumberStepper v-model="minCommission" :min="0" :step="0.01" aria-label="最低佣金" /></div>
          <div class="field"><label>印花税率</label><NumberStepper v-model="stampTax" :min="0" :max="0.01" :step="0.0001" aria-label="印花税率" /></div>
        </div>
        <div class="field">
          <label>成交价</label>
          <MacSelect v-model="execution" :options="EXECUTIONS" aria-label="成交价格模式" />
        </div>
      </section>

      <p v-if="catalogLoading || catalogError" class="loading-text" role="status">
        {{ catalogLoading ? '正在载入策略目录…' : '配置载入已停止，当前输入未被覆盖。' }}
        <button v-if="catalogError" class="ghost" type="button" @click="loadRoute">重新载入</button>
      </p>
      <button
        class="primary run-btn action-button"
        :disabled="catalogLoading || catalogError || store.running || (isContextLoad && savedLoadState !== 'ready')"
        @click="onRun(true)"
      >
        <svg class="button-icon" :class="{ spinning: store.running }" viewBox="0 0 20 20" aria-hidden="true">
          <path v-if="store.running" d="M16.5 10a6.5 6.5 0 1 1-1.9-4.6" />
          <path v-else d="M4 15.5V4.5M4 13l4-3 3 2 5-6M13 6h3v3" />
        </svg>
        <span>{{ store.running ? '取行情+回测中…' : '开始回测' }}</span>
      </button>
    </aside>

    <!-- 右栏：报告 -->
    <main class="report-panel">
      <section v-if="isContextLoad" class="saved-context" aria-label="执行配置载入状态" role="status" :aria-busy="savedLoadState==='loading'">
        <h3>{{ savedLoadState==='loading'?'正在读取执行配置':savedLoadState==='ready'?`已载入：${savedLoadName}`:'执行配置未有效载入' }}</h3>
        <p>载入仅恢复配置，不自动回测。重新计算使用当前可取得的行情，不是原成绩重放。</p>
        <ul v-if="savedLoadWarnings.length" aria-label="旧策略缺失配置"><li v-for="warning in savedLoadWarnings" :key="warning">{{ warning }}</li></ul>
      </section>
      <ResearchEntryContext v-if="route.query.researchContext !== undefined" :value="entryContext.value" :error="entryError" backtest />
      <RadarReviewContext v-if="isSignalReview" :review="reviewContext.value" :error="reviewContext.error" :matches="reviewMatches" :status="reviewStatus" :metadata="store.barsMetadata" />
      <section v-if="isStrategyEdit || isStrategyCopyEdit" class="review-context" aria-label="修改策略上下文">
        <div class="review-context-icon">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <template v-if="isStrategyEdit || isStrategyCopyEdit"><path d="m4 14.8.5-3.2L12.2 4l2.8 2.8-7.7 7.6zM10.8 5.4l2.8 2.8M4 16h12" /></template>
            <template v-else><circle cx="8.5" cy="8.5" r="4.75" /><path d="m12.1 12.1 3.4 3.4M6.4 8.7l1.3 1.3 2.8-3" /></template>
          </svg>
        </div>
        <div class="review-context-copy">
          <template v-if="isStrategyEdit || isStrategyCopyEdit">
            <span>信号雷达 · 修改策略</span>
            <strong>{{ editingRecord?.name || reviewSourceName }} · {{ code }}</strong>
            <p v-if="isStrategyEdit">调整左侧参数后运行验证，再点击“保存修改”覆盖原策略</p>
            <p v-else>这是组合中的子策略；调整并验证后可保存为独立策略，不影响原组合</p>
          </template>
        </div>
        <RouterLink class="review-back" to="/signals">返回信号雷达</RouterLink>
      </section>
      <div v-if="store.error" class="error-banner">⚠ {{ store.error }}</div>

      <div v-if="!store.result && !store.running && !store.error" class="placeholder">
        <p>{{ isSavedLoad ? '核对分析设置后，点击「开始回测」' : '输入代码、配置策略后点击「开始回测」（自动取行情）' }}</p>
      </div>

      <div v-if="store.result" class="report-content">
        <ResultDataProvenance :evidence="store.result.data_provenance" />
        <div class="result-toolbar">
          <button class="ghost" @click="openSaveForm">
            <svg class="button-icon" viewBox="0 0 20 20" aria-hidden="true">
              <path d="M4 3.5h10l2 2v11H4z" /><path d="M7 3.5v5h6v-5M7 16.5v-5h6v5" />
            </svg>
            <span>{{ isStrategyEdit ? '保存修改' : '保存策略' }}</span>
          </button>
          <button class="ghost" :disabled="store.running||!store.completed" @click="exportBacktest">导出回测原档</button>
          <span v-if="saveMsg" class="save-msg">{{ saveMsg }}</span>
        </div>
        <CloudResearchArchives :capture="captureBacktest" :busy="store.running||!store.completed" />

        <section class="report-section">
          <ChartFrame title="K线、买卖点与技术指标" description="主副图同步缩放；支持完整指标库、参数设置与主图叠加。">
            <KlineChart :bars="store.ohlcv" :trades="store.result.trades" />
          </ChartFrame>
        </section>

        <section class="report-section">
          <ChartFrame title="净值曲线与回撤" description="观察收益累积路径与风险区间">
            <EquityChart :equity="store.result.equity_curve" />
          </ChartFrame>
        </section>

        <section v-if="grade" class="report-section">
          <h3>评级</h3>
          <GradeDetails :result="grade" expanded />
        </section>

        <section class="report-section">
          <h3>绩效指标</h3>
          <MetricTable :perf="store.result.performance" :states="resultBasis(store.result)?.metric_status" />
        </section>

        <section class="report-section">
          <h3>成交记录（{{ store.result.trades.length }} 笔）</h3>
          <TradeTable :trades="store.result.trades" />
        </section>
      </div>
    </main>

    <!-- 保存策略对话框 -->
    <div v-if="showSaveForm" class="modal-overlay" @click.self="showSaveForm = false">
      <div class="modal">
        <h3>{{ isStrategyEdit ? '保存策略修改' : '保存到策略库' }}</h3>
        <p class="modal-desc">
          {{ isStrategyEdit ? '保存后将覆盖原策略配置，并保留原策略编号与创建时间。' : '将当前策略、标的上下文和成绩快照存下，下次可在「策略库」载入或重跑。' }}
        </p>
        <div class="field">
          <label>名称</label>
          <input v-model="saveName" type="text" placeholder="给这个策略起个名" />
        </div>
        <div class="field">
          <label>标签（逗号分隔，可选）</label>
          <input v-model="saveTags" type="text" placeholder="如：银行,长线观察" />
        </div>
        <div class="field">
          <label>备注（可选）</label>
          <textarea v-model="saveNotes" rows="2" placeholder="为什么觉得它好？"></textarea>
        </div>
        <div class="modal-summary">
          {{ strategyLabel }} · {{ code }} ·
          {{ store.result ? (store.result.performance.total_return * 100).toFixed(2) + '%' : '' }}
        </div>
        <div class="modal-actions">
          <button class="ghost" :disabled="saving" @click="showSaveForm = false">取消</button>
          <button class="primary" :disabled="saving || !saveName.trim()" @click="onSave">
            {{ saving ? '保存中…' : isStrategyEdit ? '保存修改' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backtest-view {
  display: flex;
  height: 100%;
}

/* 左栏配置面板 */
.config-panel {
  width: 320px;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.panel-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.panel-section:last-of-type {
  border-bottom: none;
}
.panel-section h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 12px;
}
.loading-text {
  color: var(--text-dim);
  font-size: 12px;
}
.run-btn {
  margin-top: auto;
  width: 100%;
  min-height: 35px;
  padding: 0 12px;
  font-size: 11px;
}

/* 右栏报告面板 */
.report-panel {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 16px 20px;
}
.saved-context {
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
  overflow-wrap: anywhere;
}
.saved-context h3 { margin: 0 0 6px; font-size: 13px; font-weight: 600; }
.saved-context p, .saved-context ul { margin: 0; color: var(--text-muted); font-size: 12px; line-height: 1.7; }
.saved-context ul { margin-top: 8px; padding-left: 18px; }
.saved-context + .placeholder { height: auto; min-height: 50vh; }
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-dim);
}
.error-banner {
  background: rgba(239, 65, 70, 0.12);
  border: 1px solid var(--up);
  color: var(--up);
  padding: 10px 14px;
  border-radius: var(--radius);
  margin-bottom: 16px;
  font-size: 13px;
}
.review-context {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
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
.report-section {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  margin-bottom: 16px;
}
.report-section h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 12px;
}

/* 结果工具条 + 保存对话框 */
.result-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.result-toolbar .ghost {
  font-size: 12px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  cursor: pointer;
}
.result-toolbar .ghost:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.save-msg {
  font-size: 12px;
  color: var(--up);
}
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  width: 380px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.modal h3 {
  font-size: 15px;
  font-weight: 600;
}
.modal-desc {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.5;
}
.modal .field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.modal .field label {
  font-size: 12px;
  color: var(--text-muted);
}
.modal .field input,
.modal .field textarea {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 7px 9px;
  font-size: 13px;
  color: var(--text);
  font-family: inherit;
  resize: vertical;
}
.modal .field textarea {
  font-family: inherit;
}
.modal-summary {
  font-size: 12px;
  color: var(--text-dim);
  font-family: var(--font-mono);
  padding: 8px 10px;
  background: var(--bg);
  border-radius: var(--radius);
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
.modal-actions .ghost {
  font-size: 13px;
  padding: 7px 16px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  cursor: pointer;
}
.modal-actions .primary {
  font-size: 13px;
  padding: 7px 16px;
  cursor: pointer;
}
.modal-actions .primary:disabled,
.modal-actions .ghost:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
