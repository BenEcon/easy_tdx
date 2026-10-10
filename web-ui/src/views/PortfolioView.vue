<script setup lang="ts">
import PortfolioArchiveTools from '../components/PortfolioArchiveTools.vue'
import { metricText } from '../metric-state'
import MetricStateNotes from '../components/MetricStateNotes.vue'
import ResultDataProvenance from '../components/ResultDataProvenance.vue'
// 组合回测主页面：左配置（多标的 + 策略 + 日期）/ 右报告（组合净值 + 各标的对比）。

import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import ChartFrame from '../components/ChartFrame.vue'
import { useMobileSettings } from '../mobile-settings'
import AdjustPicker from '../components/AdjustPicker.vue'
import EquityChart from '../components/EquityChart.vue'
import GradeDetails from '../components/GradeDetails.vue'
import MacSelect from '../components/MacSelect.vue'
import NumberStepper from '../components/NumberStepper.vue'
import PortfolioCompareChart from '../components/PortfolioCompareChart.vue'
import PortfolioSummaryTable from '../components/PortfolioSummaryTable.vue'
import StocksPicker from '../components/StocksPicker.vue'
import StrategyPicker from '../components/StrategyPicker.vue'
import { fetchSavedStrategy, formatError, saveStrategy } from '../api'
import { useAuth } from '../auth'
import { savedPortfolioInput, savedStrategyRequestId } from '../saved-strategy-input'
import { gradePortfolio } from '../grading'
import { performanceSnapshot, portfolioBasis } from '../performance-context'
import type { Category, ExecutionMode } from '../types'
import { useBacktestStore } from '../stores/backtest'
import { useMarketPreferences } from '../market-preferences'
import { detectMarket } from '../market'
import { getLastStockCode } from '../stock-history'

const store = useBacktestStore()
const { mobile, settingsOpen } = useMobileSettings(() => Boolean(store.portfolioResult))
const route = useRoute()
const { adjustMode } = useMarketPreferences()
const {currentUser}=useAuth()
const isSavedLoad=computed(()=>route.query.savedStrategyId!==undefined)
const savedState=ref<'idle'|'loading'|'ready'|'error'>('idle')
const savedName=ref(''),savedWarnings=ref<string[]>([]),detachedNotice=ref('')
const catalogLoading=ref(true),catalogError=ref(false)
let generation=0,inputGeneration=0,saveGeneration=0

const recentStockCode = getLastStockCode()
const recentStockSymbol = `${detectMarket(recentStockCode)}:${recentStockCode}`
const stocks = ref<string[]>([
  recentStockSymbol,
  ...['SZ:000001', 'SH:600519'].filter((symbol) => symbol !== recentStockSymbol),
].slice(0, 2))
const strategy = ref('ma_cross')
const params = ref<Record<string, number | string | boolean>>({})
const cash = ref(1000000)
const commission=ref(.0003),minCommission=ref(5),stampTax=ref(.001),slippage=ref(0)
const category = ref<Category>('DAY')
const execution = ref<ExecutionMode>('next_open')

// 成交价模式（精简为 开盘价/收盘价）
const EXECUTIONS: { value: ExecutionMode; label: string }[] = [
  { value: 'next_open', label: '开盘价' },
  { value: 'next_close', label: '收盘价' },
]
const CATEGORIES: Category[] = ['DAY', 'WEEK', 'MONTH', 'MIN_5', 'MIN_15', 'MIN_30', 'MIN_60']
const CATEGORY_OPTIONS = CATEGORIES.map((value) => ({ value, label: value }))

// 日期默认（复用单标的逻辑）
function isoDaysFromNow(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}
const startDate = ref('2020-01-06')
const endDate = ref(isoDaysFromNow(0))

async function loadRoute() {
  const version=++generation,owner=currentUser.value?.id
  const initialInputVersion=inputGeneration
  catalogLoading.value=true;catalogError.value=false
  store.clearPortfolio();showSaveForm.value=false;saving.value=false;saveMsg.value=''
  savedState.value=isSavedLoad.value?'loading':'idle';savedName.value='';savedWarnings.value=[]
  try{
    await store.loadStrategies()
    if(version!==generation||currentUser.value?.id!==owner)return
    if(initialInputVersion!==inputGeneration)throw Error('载入期间参数已修改，已保留当前输入；请确认后重新载入')
    if(!store.strategies.length)throw Error('策略目录为空，请重试')
  }catch(e){
    if(version===generation){catalogError.value=true;savedState.value='error';store.error=`载入执行配置失败：${formatError(e)}`}
    return
  }finally{if(version===generation)catalogLoading.value=false}
  if(version!==generation)return
  if(isSavedLoad.value){
    try{
      if(!owner)throw Error('请先登录再载入策略')
      const id=savedStrategyRequestId(route.query)
      await nextTick()
      const inputVersion=inputGeneration
      const record=await fetchSavedStrategy(id,owner)
      if(version!==generation||currentUser.value?.id!==owner)return
      if(inputVersion!==inputGeneration)throw Error('载入期间参数已修改，请从策略库重新载入')
      if(record.id!==id)throw Error('返回的组合与所选记录不一致')
      const input=savedPortfolioInput(record,{category:category.value,adjust:adjustMode.value,startDate:startDate.value,endDate:endDate.value,cash:cash.value,commission:commission.value,minCommission:minCommission.value,stampTax:stampTax.value,slippage:slippage.value,execution:execution.value},store.strategies.map(s=>s.name))
      stocks.value=input.stocks;strategy.value=input.strategy;category.value=input.category;adjustMode.value=input.adjust
      startDate.value=input.startDate;endDate.value=input.endDate;cash.value=input.cash;execution.value=input.execution
      commission.value=input.commission;minCommission.value=input.minCommission;stampTax.value=input.stampTax;slippage.value=input.slippage
      await nextTick()
      if(version!==generation||currentUser.value?.id!==owner)return
      params.value=input.params;savedName.value=record.name;savedWarnings.value=input.warnings;savedState.value='ready'
    }catch(e){if(version===generation){savedState.value='error';store.error=formatError(e)}}
    return
  }

  // 从 URL query 回填（策略库「载入」组合策略跳转带来）
  const qStrategy = route.query.strategy as string | undefined
  const qParams = route.query.params as string | undefined
  const qStocks = route.query.stocks as string | undefined
  const qStartDate = route.query.startDate as string | undefined
  const qEndDate = route.query.endDate as string | undefined
  const qCategory = route.query.category as Category | undefined
  if (qStrategy) {
    strategy.value = qStrategy
    await nextTick()
    if(version!==generation)return
  }
  if (qParams) {
    try {
      params.value = JSON.parse(qParams) as Record<string, number | string | boolean>
    } catch {
      // 解析失败忽略
    }
  }
  if (qStocks) {
    stocks.value = qStocks
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  }
  if (qStartDate) startDate.value = qStartDate
  if (qEndDate) endDate.value = qEndDate
  if (qCategory) category.value = qCategory
}
onMounted(loadRoute)
watch(()=>route.fullPath,()=>{if(route.path==='/portfolio')void loadRoute()})

async function onRun() {
  if(catalogLoading.value||catalogError.value){store.error='策略目录及执行配置尚未有效载入，请重新载入';return}
  if(isSavedLoad.value&&savedState.value!=='ready'){store.error='保存组合尚未有效载入，请重新从策略库打开';return}
  detachedNotice.value=''
  saveGeneration++;saving.value=false;showSaveForm.value=false;saveMsg.value=''
  await store.runPortfolio({
    strategy: strategy.value,
    params: params.value,
    cash: cash.value,
    execution: execution.value,
    commission:commission.value,min_commission:minCommission.value,stamp_tax:stampTax.value,slippage:slippage.value,
    stocks: stocks.value,
    category: category.value,
    start_date: startDate.value,
    end_date: endDate.value,
    adjust: adjustMode.value,
  })
}

// ── 保存策略（把当前组合结果 + 配置 + 上下文存进策略库）──────────────────────
const showSaveForm = ref(false)
const saving = ref(false)
const saveName = ref('')
const saveTags = ref('')
const saveNotes = ref('')
const saveMsg = ref('')

const strategyLabel = computed(
  () => store.strategies.find((s) => s.name === strategy.value)?.label ?? strategy.value,
)

// 组合评级：从 combined_equity 重算夏普/卡玛/波动率等（组合级净值算不出胜率/利润因子），
// 用 5 维度评分。净值点数过少（< 60 个交易日）视为样本不足。
const grade = computed(() =>
  store.portfolioResult ? gradePortfolio(store.portfolioResult) : null,
)

function openSaveForm() {
  const request=store.portfolioRequest
  if(!request||!store.portfolioResult)return
  saveName.value = `${store.strategies.find(s=>s.name===request.strategy)?.label??request.strategy} · 组合${request.stocks.length}只`
  saveTags.value = ''
  saveNotes.value = ''
  saveMsg.value = ''
  showSaveForm.value = true
}

async function onSave() {
  const request=store.portfolioRequest,owner=currentUser.value?.id,version=generation
  if (!store.portfolioResult || !request || !saveName.value.trim() || saving.value) return
  if(!owner){saveMsg.value='请先登录再保存';return}
  const saveVersion=++saveGeneration
  saving.value = true
  saveMsg.value = ''
  try {
    const perf = store.portfolioResult.total_performance
    await saveStrategy({
      name: saveName.value.trim(),
      kind: 'portfolio',
      strategy: request.strategy,
      strategy_label: store.strategies.find(s=>s.name===request.strategy)?.label??request.strategy,
      params: request.params,
      context: {
        stocks: request.stocks,
        category: request.category,
        start_date: request.start_date,
        end_date: request.end_date,
        adjust: request.adjust,
      },
      trade_config: {
        cash: request.cash,
        execution: request.execution,
        commission:request.commission,min_commission:request.min_commission,stamp_tax:request.stamp_tax,slippage:request.slippage,
      },
      snapshot: performanceSnapshot({ ...perf }, portfolioBasis(store.portfolioResult)),
      tags: saveTags.value
        .split(/[,，]/)
        .map((t) => t.trim())
        .filter(Boolean),
      notes: saveNotes.value,
    },owner)
    if(version!==generation||currentUser.value?.id!==owner||saveVersion!==saveGeneration)return
    saveMsg.value = '✓ 已保存到策略库'
    showSaveForm.value = false
  } catch (e) {
    if(version===generation&&currentUser.value?.id===owner&&saveVersion===saveGeneration)saveMsg.value = `保存失败：${formatError(e)}`
  } finally {
    if(version===generation&&currentUser.value?.id===owner&&saveVersion===saveGeneration)saving.value = false
  }
}
watch([stocks,strategy,params,cash,commission,minCommission,stampTax,slippage,category,execution,startDate,endDate,adjustMode],()=>{
  inputGeneration++
  if(store.portfolioRunning)detachedNotice.value='设置已改变，已停止显示旧任务进度；后台任务未取消，可在个人账户查看。'
  store.clearPortfolio();showSaveForm.value=false;saveGeneration++;saving.value=false;saveMsg.value=''
},{deep:true,flush:'sync'})
watch(()=>currentUser.value?.id,()=>{
  catalogLoading.value=false;catalogError.value=true
  generation++;inputGeneration++;store.clearPortfolio();savedState.value='error';savedName.value='';savedWarnings.value=[]
  showSaveForm.value=false;saving.value=false;saveMsg.value='';detachedNotice.value=''
},{flush:'sync'})
onBeforeUnmount(()=>{generation++;inputGeneration++;store.clearPortfolio()})
</script>

<template>
  <div class="portfolio-view">
    <button v-if="mobile" class="mobile-inspector-toggle" type="button" :aria-expanded="settingsOpen" aria-controls="portfolio-settings" @click="settingsOpen = !settingsOpen">
      <span>组合设置</span><span>{{ settingsOpen ? '收起' : '展开' }}</span>
    </button>
    <aside v-show="!mobile || settingsOpen" id="portfolio-settings" class="config-panel">
      <section class="panel-section">
        <h3>标的列表</h3>
        <StocksPicker v-model="stocks" :category="category" />
      </section>

      <section class="panel-section">
        <h3>策略</h3>
        <StrategyPicker
          v-if="store.strategies.length"
          v-model:strategy="strategy"
          v-model:params="params"
          :strategies="store.strategies"
          :suspend-defaults="catalogLoading || catalogError"
        />
        <p v-else class="loading-text">加载策略中…</p>
      </section>

      <section class="panel-section">
        <h3>周期与日期</h3>
        <div class="field">
          <label>周期</label>
          <MacSelect v-model="category" :options="CATEGORY_OPTIONS" aria-label="行情周期" />
        </div>
        <div class="row">
          <div class="field">
            <label>开始</label>
            <input v-model="startDate" type="date" />
          </div>
          <div class="field">
            <label>结束</label>
            <input v-model="endDate" type="date" />
          </div>
        </div>
        <AdjustPicker />
      </section>

      <section class="panel-section">
        <h3>资金与成本</h3>
        <div class="field">
          <label>组合总资金</label>
          <NumberStepper v-model="cash" :min="1" :step="10000" aria-label="组合总资金" />
        </div>
        <div class="row">
          <div class="field"><label>佣金率</label><NumberStepper v-model="commission" :min="0" :max="0.01" :step="0.0001" aria-label="佣金率" /></div>
          <div class="field"><label>滑点</label><NumberStepper v-model="slippage" :min="0" :max="0.05" :step="0.001" aria-label="滑点" /></div>
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
        :disabled="catalogLoading || catalogError || store.portfolioRunning || stocks.length === 0 || (isSavedLoad && savedState !== 'ready')"
        @click="onRun"
      >
        <svg class="button-icon" :class="{ spinning: store.portfolioRunning }" viewBox="0 0 20 20" aria-hidden="true">
          <path v-if="store.portfolioRunning" d="M16.5 10a6.5 6.5 0 1 1-1.9-4.6" />
          <path v-else d="M3.5 14.5 7.4 10l3 2.2 5.9-7M13 5.2h3.3v3.3" />
        </svg>
        <span>{{ store.portfolioRunning ? '组合回测中…' : '开始组合回测' }}</span>
      </button>
    </aside>

    <main class="report-panel">
      <section v-if="isSavedLoad" class="saved-context" aria-label="保存组合载入状态" role="status" :aria-busy="savedState==='loading'">
        <h3>{{ savedState==='loading'?'正在读取保存组合':savedState==='ready'?`已载入：${savedName}`:'保存组合未有效载入' }}</h3>
        <p>载入仅恢复配置，不自动回测。重新计算使用当前可取得的行情，不是原成绩重放。</p>
        <ul v-if="savedWarnings.length" aria-label="旧组合缺失配置"><li v-for="warning in savedWarnings" :key="warning">{{ warning }}</li></ul>
      </section>
      <p v-if="detachedNotice" class="task-note" role="status">{{ detachedNotice }}</p>
      <div v-if="store.error" class="error-banner">⚠ {{ store.error }}</div>

      <div
        v-if="!store.portfolioResult && !store.portfolioRunning && !store.error"
        class="placeholder"
      >
        <p>添加多只标的，选择策略后点击「开始组合回测」</p>
      </div>

      <div v-if="store.portfolioResult" class="report-content">
        <PortfolioArchiveTools kind="portfolio" :task-id="store.portfolioTaskId" :request="store.portfolioRequest" :result="store.portfolioResult" :busy="store.portfolioRunning" />
        <ResultDataProvenance :evidence="store.portfolioResult.data_provenance" />
        <div class="result-toolbar">
          <button class="ghost" @click="openSaveForm">
            <svg class="button-icon" viewBox="0 0 20 20" aria-hidden="true">
              <path d="M4 3.5h10l2 2v11H4z" /><path d="M7 3.5v5h6v-5M7 16.5v-5h6v5" />
            </svg>
            <span>保存策略</span>
          </button>
          <span v-if="saveMsg" class="save-msg">{{ saveMsg }}</span>
        </div>

        <section v-if="grade" class="report-section">
          <h3>组合评级</h3>
          <GradeDetails :result="grade" expanded />
        </section>

        <section class="report-section">
          <h3>组合整体绩效</h3>
          <div class="perf-summary">
            <div class="perf-item">
              <span class="label">组合总收益</span>
              <span
                class="value"
                :class="store.portfolioResult.total_performance.total_return > 0 ? 'pos' : 'neg'"
              >
                {{ metricText(store.portfolioResult.total_performance.total_return, store.portfolioResult.performance_basis?.metric_status?.total_return, 'percent') }}
              </span>
            </div>
            <div class="perf-item">
              <span class="label">标的数量</span>
              <span class="value">{{ store.portfolioResult.total_performance.total_stocks }}</span>
            </div>
            <div class="perf-item">
              <span class="label">组合总资金</span>
              <span class="value">{{ store.portfolioResult.total_performance.total_cash.toFixed(0) }}</span>
            </div>
          </div>
          <MetricStateNotes :states="store.portfolioResult.performance_basis?.metric_status" :legacy="!store.portfolioResult.performance_basis?.metric_status" />
        </section>

        <section class="report-section">
          <ChartFrame title="组合净值曲线" description="统一资金池下的组合收益轨迹">
            <EquityChart :equity="store.portfolioResult.combined_equity" />
          </ChartFrame>
        </section>

        <section class="report-section">
          <h3>各标的绩效对比</h3>
          <PortfolioSummaryTable
            :results="store.portfolioResult.individual_results"
            :allocation="store.portfolioResult.equity_allocation"
          />
        </section>

        <section class="report-section">
          <ChartFrame title="各标的净值叠加（归一化）" description="比较不同标的的相对表现">
            <PortfolioCompareChart :results="store.portfolioResult.individual_results" />
          </ChartFrame>
        </section>
      </div>
    </main>

    <!-- 保存策略对话框 -->
    <div v-if="showSaveForm" class="modal-overlay" @click.self="showSaveForm = false">
      <div class="modal">
        <h3>保存到策略库</h3>
        <p class="modal-desc">
          将当前组合策略 + 标的列表 + 成绩快照存下，下次可在「策略库」载入或重跑。
        </p>
        <div class="field">
          <label>名称</label>
          <input v-model="saveName" type="text" placeholder="给这个组合策略起个名" />
        </div>
        <div class="field">
          <label>标签（逗号分隔，可选）</label>
          <input v-model="saveTags" type="text" placeholder="如：消费,长线观察" />
        </div>
        <div class="field">
          <label>备注（可选）</label>
          <textarea v-model="saveNotes" rows="2" placeholder="为什么觉得它好？"></textarea>
        </div>
        <div class="modal-summary">
          {{ strategyLabel }} · {{ stocks.length }} 只 ·
          {{
            store.portfolioResult
              ? (store.portfolioResult.total_performance.total_return * 100).toFixed(2) + '%'
              : ''
          }}
        </div>
        <div class="modal-actions">
          <button class="ghost" :disabled="saving" @click="showSaveForm = false">取消</button>
          <button class="primary" :disabled="saving || !saveName.trim()" @click="onSave">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.portfolio-view {
  display: flex;
  height: 100%;
}
.config-panel {
  width: 320px;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  padding: 16px;
  overflow-y: auto;
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
  margin-bottom: 12px;
}
.loading-text {
  color: var(--text-dim);
  font-size: 12px;
}
.run-btn {
  width: 100%;
  min-height: 35px;
  padding: 0 12px;
  font-size: 11px;
}
.report-panel {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 16px 20px;
}
.saved-context { margin-bottom:16px; padding-bottom:14px; border-bottom:1px solid var(--border); overflow-wrap:anywhere; }
.saved-context h3 { margin:0 0 6px; font-size:13px; font-weight:600; }
.saved-context p, .saved-context ul, .task-note { color:var(--text-muted); font-size:12px; line-height:1.7; }
.saved-context ul { margin-top:8px; padding-left:18px; }
.saved-context + .placeholder { height:auto; min-height:50vh; }
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
.perf-summary {
  display: flex;
  gap: 32px;
}
.perf-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.perf-item .label {
  font-size: 12px;
  color: var(--text-dim);
}
.perf-item .value {
  font-size: 20px;
  font-weight: 600;
  font-family: var(--font-mono);
}
.pos {
  color: var(--up);
}
.neg {
  color: var(--down);
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
