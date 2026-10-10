<script setup lang="ts">
import { queryAction } from '../query-origin'
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import FactorEvaluationPanel from '../components/FactorEvaluationPanel.vue'
import FactorDiagnosticChart from '../components/FactorDiagnosticChart.vue'
import FactorDefinitionDetails from '../components/FactorDefinitionDetails.vue'
import FactorParameterEditor from '../components/FactorParameterEditor.vue'
import FactorArchiveTools from '../components/FactorArchiveTools.vue'
import FactorSeriesComparison from '../components/FactorSeriesComparison.vue'
import FactorFavoriteButton from '../components/FactorFavoriteButton.vue'
import {useFactorFavorites} from '../use-factor-favorites'
import {taskExecution} from '../task-execution'
import {taskStatusLabel,taskElapsed} from '../task-state'
import {taskProgressLabel} from '../task-progress'
import {factorArchiveDraft} from '../factor-archive'
import {factorParameterError,factorWarmupWarnings,parameterizedFactorName,selectedFactorParameters,type FactorParameters} from '../factor-parameters'
import { factorValue, factorSearchKey, factorAliasVisible } from '../factor-research'
import { browseFactors, factorLibraries, factorAvailabilityReason, initializeFactorCatalog } from '../factor-catalog'
import { useAuth } from '../auth'
import DataGrid from '../components/DataGrid.vue'
import DataProvenance from '../components/DataProvenance.vue'
import type { MarketDataMetadata } from '../market-data-contract'
import AdjustPicker from '../components/AdjustPicker.vue'
import FactorBenchmarkPicker from '../components/FactorBenchmarkPicker.vue'
import {needsBenchmark} from '../factor-benchmark'
import ChartFrame from '../components/ChartFrame.vue'
import MacSelect from '../components/MacSelect.vue'
import StockQueryField from '../components/StockQueryField.vue'
import StocksPicker from '../components/StocksPicker.vue'
import { analyzePortfolioRisk, submitFactorSeriesTask, fetchTask, cancelTask, fetchResearchFactors, formatError } from '../api'
import { detectMarket } from '../market'
import { getLastStockCode, useSelectedStock, recordStockHistory, stockDisplayName } from '../stock-history'
import { useMarketPreferences } from '../market-preferences'

type Row = Record<string, unknown>
type Tab = 'factor' | 'evaluation' | 'risk'
type GlossaryScope = 'all' | 'factor' | 'risk'
type FactorTerm = { zh: string; en: string; description: string }
type GlossaryEntry = FactorTerm & { key: string; category: string; scope: Exclude<GlossaryScope, 'all'> }

const tab = ref<Tab>('factor')
const recentStockCode = getLastStockCode()
const recentStockSymbol = `${detectMarket(recentStockCode)}:${recentStockCode}`
const code = useSelectedStock()
const category = ref('DAY')
const factorCount=ref('500')
const factors = ref<Row[]>([])
const selectedFactors = ref<string[]>(['momentum_20d', 'rsi_14', 'volatility_20d', 'sharpe_20d'])
const factorParameters=ref<FactorParameters>({})
const benchmark=ref('SH:000001')
const benchmarkRequired=computed(()=>needsBenchmark(selectedFactors.value,factors.value))
const resultDefinitions=ref<Record<string,Row>>({})
const parameterError=computed(()=>factorParameterError(selectedFactors.value,factors.value,factorParameters.value))
const warmupWarnings=computed(()=>factorWarmupWarnings(selectedFactors.value,factors.value,factorParameters.value,Number(factorCount.value)))
const factorRows = ref<Row[]>([])
const factorResult = ref<Row|null>(null)
const factorErrors = ref<Record<string, string>>({})
const factorMetadata = ref<MarketDataMetadata | null>(null)
const factorInputCount = ref(0)
const riskProvenance = ref<Array<{code: string; market: string; count: number; metadata: MarketDataMetadata}>>([])
const riskAlignment = ref<{note?: string; excluded_observations?: number; start?: string; end?: string}>({})
const stocks = ref([
  recentStockSymbol,
  ...['SZ:000001', 'SH:600519', 'SH:600036'].filter((symbol) => symbol !== recentStockSymbol),
].slice(0, 3))
const method = ref<'equal' | 'factor_weighted' | 'risk_parity' | 'mean_variance'>('risk_parity')
const assetRows = ref<Row[]>([])
const correlationRows = ref<Row[]>([])
const risk = ref<Record<string, unknown>>({})
const loading = ref(false)
const error = ref('')
const showGlossary = ref(false)
const glossaryQuery = ref('')
const glossaryScope = ref<GlossaryScope>('all')
const { adjustMode } = useMarketPreferences()
const unavailableReason=(factor:Row)=>factorAvailabilityReason(factor,adjustMode.value,category.value)
const availabilityWarnings=computed(()=>selectedFactors.value.flatMap(name=>{
  const factor=factors.value.find(f=>f.name===name)
  const reason=factor?unavailableReason(factor):''
  return reason?[`${factorChineseName(name)}：${reason}`]:[]
}))
const { currentUser } = useAuth()
const favorites=useFactorFavorites(),onlyFavorites=ref(false)
const favoriteKey=(factor:Row)=>String(factor.canonical_name??factor.name)
const factorTask=taskExecution<Parameters<typeof submitFactorSeriesTask>[0],Row>({owner:()=>currentUser.value?.id,submit:submitFactorSeriesTask,poll:fetchTask,cancel:cancelTask,timeout:12*60*1000,interval:1000})
const {running:factorBusy,state:factorTaskState,taskId:factorTaskId,error:factorTaskError,cancelError:factorCancelError,cancelling:factorCancelling}=factorTask
const factorTaskStatus=computed(()=>factorTaskState.value?`${taskStatusLabel(factorTaskState.value)} · ${taskElapsed(factorTaskState.value.elapsed??0)}`:factorBusy.value?'正在获取并冻结本次行情…':'')
const chartFactor = ref('momentum_20d')
const chartMode=ref('single')
const factorSearch = ref('')
const factorLibrary = ref('easy_tdx_builtin')
const factorLimit = ref(24)
watch([factorSearch, factorLibrary,onlyFavorites], () => { factorLimit.value = 24 })
const matchingFactors = computed(() => browseFactors(factors.value, factorLibrary.value, factorSearch.value, selectedFactors.value).filter(f=>!onlyFavorites.value||favorites.items.value.includes(favoriteKey(f))))
const factorPrecision = ref<'auto'|'raw'>('auto')
const factorDiagnostics = ref<Record<string,{valid_count:number;missing_count:number;reason:string}>>({})
const catalogCounts = computed(() => {
  const unique = factors.value.filter(f=>!f.alias_of)
  return {registered:factors.value.length, unique:unique.length, available:unique.filter(f=>f.available===true&&!unavailableReason(f)).length, evaluation:unique.filter(f=>f.evaluation_available===true&&!factorAvailabilityReason(f,adjustMode.value,'DAY',true)).length}
})
const formattedFactorRows = computed(()=>factorRows.value.map(row=>({...row,...Object.fromEntries(selectedFactors.value.map(name=>[name,factorValue(row[name],false,factorPrecision.value)]))})))
let factorGeneration = 0
let pageActive = true
function clearFactorResult() {
  factorGeneration++; factorTask.clear()
  factorRows.value=[];factorErrors.value={};factorMetadata.value=null;factorInputCount.value=0
  factorDiagnostics.value={}
  resultDefinitions.value={}
  factorResult.value=null
}
watch(()=>JSON.stringify([code.value,category.value,factorCount.value,adjustMode.value,selectedFactors.value,factorParameters.value,benchmark.value,currentUser.value?.id]),clearFactorResult,{flush:'sync'})
watch(()=>currentUser.value?.id,()=>{factorParameters.value={};benchmark.value='SH:000001'},{flush:'sync'})
watch(tab,clearFactorResult,{flush:'sync'})
onBeforeUnmount(() => { pageActive=false; clearFactorResult() })
const factorNames = computed(()=>Object.fromEntries(factors.value.map(f=>[String(f.name),factorChineseName(String(f.name))])))
const chartOptions = computed(()=>selectedFactors.value.filter(n=>!factorErrors.value[n]).map(n=>({value:n,label:factorChineseName(n)})))

const categoryLabels: Record<string, string> = {
  chanlun: '缠论结构', momentum: '动量与反转', quality: '质量与稳定性',
  technical: '技术指标', value: '估值指标', volatility: '波动与活跃度',
  volume: '成交量与资金', other: '其他因子',
}
const factorTerms: Record<string, FactorTerm> = {
  chanlun_bi_dir: { zh: '缠论笔方向', en: 'ChanLun Stroke Direction', description: '表示当前笔的运行方向：向上、向下或尚未形成。' },
  chanlun_mmd: { zh: '缠论买卖点', en: 'ChanLun Trading Point', description: '表示最近出现的缠论买点、卖点或无有效信号。' },
  momentum_20d: { zh: '二十日动量', en: '20-Day Momentum', description: '衡量当前收盘价相对二十个交易日前的涨跌幅。' },
  momentum_60d: { zh: '六十日动量', en: '60-Day Momentum', description: '衡量当前收盘价相对六十个交易日前的涨跌幅。' },
  reversal_5d: { zh: '五日反转', en: '5-Day Reversal', description: '用近期收益的反方向刻画短期超涨或超跌后的回归倾向。' },
  sharpe_20d: { zh: '二十日夏普比率', en: '20-Day Sharpe Ratio', description: '比较二十日平均收益与收益波动，数值越高代表单位风险收益越好。' },
  max_drawdown_20d: { zh: '二十日最大回撤', en: '20-Day Maximum Drawdown', description: '衡量最近二十个交易日从阶段高点到低点的最大跌幅。' },
  win_rate_20d: { zh: '二十日上涨胜率', en: '20-Day Win Rate', description: '最近二十个交易日中上涨天数所占的比例。' },
  macd_hist_signal: { zh: '指数平滑异同移动平均线柱信号', en: 'MACD Histogram Signal', description: '利用快慢均线差的柱体判断当前多头或空头动能。' },
  rsi_14: { zh: '十四日相对强弱指标', en: '14-Day Relative Strength Index', description: '衡量十四日价格涨跌力量，并归一化为便于比较的区间。' },
  boll_position: { zh: '布林带相对位置', en: 'Bollinger Band Position', description: '衡量价格处于布林带下轨、中轨和上轨之间的相对位置。' },
  pe_ratio: { zh: '市盈率', en: 'Price-to-Earnings Ratio', description: '股价相对每股收益的估值倍数，需要财务数据支持。' },
  pb_ratio: { zh: '市净率', en: 'Price-to-Book Ratio', description: '股价相对每股净资产的估值倍数，需要财务数据支持。' },
  volatility_20d: { zh: '二十日波动率', en: '20-Day Volatility', description: '衡量最近二十个交易日收益率的离散程度。' },
  atr_14d: { zh: '十四日平均真实波幅', en: '14-Day Average True Range', description: '综合跳空与日内振幅，衡量十四日平均价格波动范围。' },
  turnover_rate: { zh: '成交活跃度', en: 'Turnover Rate Proxy', description: '用当日成交额相对二十日平均成交额刻画交易活跃程度。' },
  amount_relative_20: { zh: '成交额相对均值', en: 'Relative Trading Amount', description: '当期成交额相对二十周期平均成交额，不是真正换手率。' },
  obv_trend: { zh: '能量潮趋势', en: 'On-Balance Volume Trend', description: '结合涨跌方向累计成交量，衡量量价资金趋势。' },
  vol_surge: { zh: '成交量突增', en: 'Volume Surge', description: '比较当日成交量与二十日平均成交量，识别异常放量。' },
  amount_ma_ratio: { zh: '成交额均线比', en: 'Amount Moving-Average Ratio', description: '比较五日与二十日平均成交额，判断资金活跃度变化。' },
}
const riskTerms: GlossaryEntry[] = [
  { key:'rank_ic', zh:'秩相关', en:'Rank Information Coefficient (Rank IC)', category:'因子检验', scope:'factor', description:'同一天各标的因子排名与远期收益排名的相关系数；常数或样本不足时未定义。' },
  { key:'ic_ir', zh:'信息比率', en:'Information Ratio (IC IR)', category:'因子检验', scope:'factor', description:'有效日秩相关均值除以样本标准差；未年化，不是组合夏普比率。' },
  { key:'mad_zscore', zh:'中位去极值与标准化', en:'MAD Winsorization and Z-score', category:'因子检验', scope:'factor', description:'按当日横截面中位绝对偏差裁剪极值，再减均值除以标准差；不填充缺失值。' },
  { key:'quantile_return', zh:'分层平均远期收益', en:'Quantile Forward Return', category:'因子检验', scope:'factor', description:'把同日因子从低到高分组，比较后续价格变化的平均值；不等于扣除成本后的可成交收益。' },
  { key: 'risk_parity', zh: '风险平价', en: 'Risk Parity', category: '组合模型', scope: 'risk', description: '让各资产对组合整体风险的贡献尽量均衡。' },
  { key: 'mean_variance', zh: '均值方差优化', en: 'Mean-Variance Optimization', category: '组合模型', scope: 'risk', description: '在预期收益与波动风险之间寻找权衡后的权重。' },
  { key: 'factor_weighted', zh: '因子加权', en: 'Factor Weighted', category: '组合模型', scope: 'risk', description: '依据资产因子得分分配组合权重。' },
  { key: 'equal', zh: '等权配置', en: 'Equal Weight', category: '组合模型', scope: 'risk', description: '为组合中的每只股票分配相同权重。' },
  { key: 'annual_return', zh: '年化收益率', en: 'Annualized Return', category: '风险指标', scope: 'risk', description: '把样本期平均收益换算为年度口径。' },
  { key: 'annual_volatility', zh: '年化波动率', en: 'Annualized Volatility', category: '风险指标', scope: 'risk', description: '把收益波动换算为年度口径，用于衡量整体风险。' },
  { key: 'risk_contribution', zh: '风险贡献', en: 'Risk Contribution', category: '风险指标', scope: 'risk', description: '单个资产对组合总风险的贡献比例。' },
  { key: 'correlation', zh: '相关系数', en: 'Correlation Coefficient', category: '风险指标', scope: 'risk', description: '衡量两只资产收益走势的同步程度，范围为负一到一。' },
]

const categoryOptions = [
  { value: 'DAY', label: '日线' }, { value: 'WEEK', label: '周线' },
  { value: 'MIN_60', label: '60 分钟' }, { value: 'MIN_30', label: '30 分钟' },
]
const methodOptions = [
  { value: 'risk_parity' as const, label: '风险平价' },
  { value: 'mean_variance' as const, label: '均值方差' },
  { value: 'factor_weighted' as const, label: '因子加权' },
  { value: 'equal' as const, label: '等权配置' },
]
const factorGroups = computed(() => {
  const groups: Record<string, Row[]> = {}
  matchingFactors.value.slice(0, factorLimit.value).forEach((factor) => {
    const categoryName = String(factor.category ?? 'other')
    ;(groups[categoryName] ??= []).push(factor)
  })
  return Object.entries(groups).map(([key, items]) => ({ key, label: categoryLabels[key] ?? '其他因子', items }))
})
const latestFactor = computed(() => factorRows.value.at(-1) ?? {})
const factorMetrics = computed(() => selectedFactors.value.map((name) => ({
  name: factorChineseName(name),
  value: latestFactor.value[name],
})))
const factorColumns = computed(() => [
  { key: 'datetime', label: '日期时间' }, { key: 'open', label: '开盘价' },
  { key: 'high', label: '最高价' }, { key: 'low', label: '最低价' },
  { key: 'close', label: '收盘价' }, { key: 'vol', label: '成交量' },
  { key: 'amount', label: '成交额' },
  ...selectedFactors.value.map((name) => ({ key: name, label: factorChineseName(name) })),
])
const assetColumns = [
  { key: 'code', label: '股票代码' }, { key: 'market', label: '市场' },
  { key: 'annual_return', label: '年化收益率' }, { key: 'volatility', label: '年化波动率' },
  { key: 'score', label: '风险收益得分' }, { key: 'weight', label: '建议权重' },
  { key: 'risk_contribution', label: '风险贡献' },
]
const glossaryEntries = computed<GlossaryEntry[]>(() => {
  const factorEntries = factors.value.filter(f=>factorAliasVisible(f,glossaryQuery.value)).map((factor) => {
    const key = String(factor.name ?? '')
    const term = factorTerms[key]
    return {
      key,
      zh: String(factor.display_name ?? term?.zh ?? factor.description ?? '未命名因子').split(/[（(]/)[0],
      en: term?.en ?? key,
      description: String(factor.description ?? term?.description ?? ''),
      category: categoryLabels[String(factor.category ?? 'other')] ?? '其他因子',
      scope: 'factor' as const,
    }
  })
  const query = factorSearchKey(glossaryQuery.value)
  return [...factorEntries, ...riskTerms].filter((entry) => {
    if (glossaryScope.value !== 'all' && entry.scope !== glossaryScope.value) return false
    return !query || [entry.zh, entry.en, entry.key, entry.category, entry.description]
      .some((value) => factorSearchKey(value).includes(query))
  })
})
const riskMetrics = computed(() => [
  { label: '年化波动率', value: `${(Number(risk.value.total_volatility ?? 0) * 100).toFixed(2)}%` },
  { label: '最大风险贡献', value: `${(Number(risk.value.max_risk_contribution ?? 0) * 100).toFixed(2)}%` },
  { label: '有效持仓', value: String(risk.value.n_positions ?? 0) },
])

function factorChineseName(name: string): string {
  const definition=factors.value.find(f=>f.name===name)
  return (definition?parameterizedFactorName(definition,factorParameters.value[name]):factorTerms[name]?.zh??name).split(/[（(]/)[0]
}

function factorChineseDescription(name: string): string {
  return String(factors.value.find(f=>f.name===name)?.description ?? factorTerms[name]?.description ?? '')
}

function openGlossary(factorName = '') {
  glossaryScope.value = factorName ? 'factor' : 'all'
  glossaryQuery.value = factorName
  showGlossary.value = true
}

function closeGlossary() {
  showGlossary.value = false
  glossaryQuery.value = ''
}

function toggleFactor(name: string) {
  const definition=factors.value.find(f=>f.name===name)
  const canonical=definition?.canonical_name ?? name
  if(!selectedFactors.value.includes(name)&&selectedFactors.value.some(n=>(factors.value.find(f=>f.name===n)?.canonical_name??n)===canonical))return
  selectedFactors.value = selectedFactors.value.includes(name)
    ? selectedFactors.value.filter((item) => item !== name)
    : selectedFactors.value.length < 12 ? [...selectedFactors.value, name] : selectedFactors.value
}

async function runFactor(manual = false) {
  if(parameterError.value){error.value=parameterError.value;return}
  if (!/^\d{6}$/.test(code.value) || !selectedFactors.value.length) {
    error.value = !selectedFactors.value.length ? '请至少选择一个因子' : '股票代码必须是 6 位数字'
    return
  }
  clearFactorResult()
  const stamp=factorGeneration
  const capturedCode=code.value
  error.value = ''
  factorMetadata.value = null
  try {
    const completed = await factorTask.run({
      market: detectMarket(code.value), code: code.value, category: category.value,
      count: Number(factorCount.value), factors: selectedFactors.value,
      factor_parameters: selectedFactorParameters(selectedFactors.value,factorParameters.value),
      adjust: adjustMode.value,
      benchmark: benchmarkRequired.value?benchmark.value:null,
    },manual)
    if(stamp!==factorGeneration||!completed)return
    const result=factorTask.result.value
    factorArchiveDraft('series',result) // Only a complete, archivable response is adopted.
    if(!result)throw Error('因子序列结果缺失')
    factorRows.value = Array.isArray(result.rows) ? result.rows as Row[] : []
    factorErrors.value = (result.errors ?? {}) as Record<string, string>
    factorMetadata.value = (result.metadata ?? null) as MarketDataMetadata | null
    factorInputCount.value = Number(result.input_count ?? 0)
    factorDiagnostics.value = (result.diagnostics ?? {}) as typeof factorDiagnostics.value
    resultDefinitions.value=(result.factor_definitions??{}) as Record<string,Row>
    factorResult.value=factorRows.value.length?result:null
    if (!factorRows.value.length) {
      error.value = '当前行情服务器未返回可用 K 线，请在“行情服务器”中切换节点后重试'
    }
    recordStockHistory({ code: capturedCode, category: category.value as 'DAY' })
  } catch (e) {
    if(stamp!==factorGeneration)return
    error.value = formatError(e)
    factorRows.value = []
  }
}

async function runRisk() {
  if (stocks.value.length < 2) { error.value = '组合风险分析至少需要 2 只股票'; return }
  loading.value = true
  error.value = ''
  riskProvenance.value = []
  riskAlignment.value = {}
  risk.value = {}
  correlationRows.value = []
  try {
    const response = await queryAction(true)(() => analyzePortfolioRisk({
      stocks: stocks.value.map((symbol) => {
        const [market, stockCode] = symbol.split(':')
        return { market, code: stockCode }
      }),
      method: method.value, category: 'DAY', count: 500,
      adjust: adjustMode.value,
    }))
    assetRows.value = Array.isArray(response.data.assets) ? response.data.assets as Row[] : []
    correlationRows.value = Array.isArray(response.data.correlation) ? response.data.correlation as Row[] : []
    risk.value = (response.data.risk ?? {}) as Record<string, unknown>
    riskProvenance.value = (response.data.provenance ?? []) as typeof riskProvenance.value
    riskAlignment.value = (response.data.alignment ?? {}) as typeof riskAlignment.value
    if (assetRows.value.length < 2) {
      error.value = '有效行情不足 2 只股票，请切换行情服务器或调整组合后重试'
    }
  } catch (e) {
    error.value = formatError(e)
    assetRows.value = []
  } finally {
    loading.value = false
  }
}

async function initialize() {
  const stamp=factorGeneration
  await initializeFactorCatalog({
    load:fetchResearchFactors, active:()=>pageActive,
    initialContext:()=>stamp===factorGeneration,
    publish:rows=>{factors.value=rows}, fail:e=>{error.value=formatError(e)},
    run:()=>runFactor(false),
  })
}

watch(chartOptions, options => {
  if (!options.some(option => option.value === chartFactor.value)) {
    chartFactor.value = options[0]?.value ?? ''
  }
})
onMounted(initialize)
</script>

<template>
  <div class="quant-page" @keydown.esc.window="closeGlossary">
    <section class="quant-header">
      <div><span>量化研究工作台</span><h2>因子与风险实验室</h2><p>计算内置因子，分析组合权重、相关性与风险贡献。</p></div>
      <div class="header-actions">
        <button class="glossary-button" @click="openGlossary()">
          <svg class="button-icon" viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="M8.6 7.6a1.6 1.6 0 0 1 3.1.5c0 1.4-1.7 1.6-1.7 3M10 14.1h.01"/></svg>
          中英术语对照
        </button>
        <nav><button :class="{ active: tab === 'factor' }" @click="tab = 'factor'">因子序列</button><button :class="{ active: tab === 'evaluation' }" @click="tab = 'evaluation'">因子检验</button><button :class="{ active: tab === 'risk' }" @click="tab = 'risk'">组合风险</button></nav>
      </div>
    </section>
    <p v-if="error" class="error-banner status-banner">{{ error }}</p>

    <template v-if="tab === 'factor'">
      <section class="factor-controls">
        <StockQueryField v-model="code" />
        <div class="period-field"><label>数据周期</label><MacSelect v-model="category" :options="categoryOptions" /></div>
        <div class="period-field"><label>历史长度</label><MacSelect v-model="factorCount" aria-label="因子历史长度" :options="[120,300,500,800].map(n=>({value:String(n),label:`${n} 根`}))" /></div>
        <AdjustPicker compact />
        <div class="selected-count"><small>已选因子</small><strong>{{ selectedFactors.length }}</strong><span>/ 12</span></div>
        <button class="primary run-button action-button" :disabled="factorBusy" @click="runFactor(true)">{{ factorBusy ? '计算中' : '计算因子' }}</button>
      </section>
      <section v-if="factorBusy||factorTaskId||factorTaskError" class="series-task-status" aria-label="因子序列任务状态">
        <p role="status" aria-live="polite">{{ factorTaskStatus }}</p>
        <p v-if="factorTaskState?.progress">{{ taskProgressLabel(factorTaskState.progress) }} · 本阶段处理量，不是总体完成比例</p>
        <div><button v-if="factorBusy&&factorTaskId" :disabled="factorCancelling||factorTaskState?.status==='cancelling'" @click="factorTask.cancel">{{ factorCancelling?'正在提交取消…':'取消后台任务' }}</button><button v-if="factorBusy" @click="clearFactorResult">停止等待</button><RouterLink v-if="factorTaskId" to="/account">查看后台任务</RouterLink></div>
        <p>停止等待或修改输入不会取消后台计算；取得编号后可取消，未取得编号时请到个人账户确认提交状态。</p>
        <p v-if="factorTaskError" role="alert" class="error-banner">{{ factorTaskError }}</p><p v-if="factorCancelError" role="alert">取消未确认：{{ factorCancelError }}</p>
      </section>
      <div class="catalog-toolbar"><MacSelect v-model="factorLibrary" aria-label="因子库" :options="factorLibraries" /><label class="factor-search">库内搜索<input v-model="factorSearch" type="search" placeholder="名称、公式族或标识，例如 RANK20" /></label></div>
      <label class="favorites-filter"><input v-model="onlyFavorites" type="checkbox">仅看收藏 · {{ favorites.items.value.length }} 项<span>按当前账户保存，仍按所选库和搜索筛选</span></label>
      <p v-if="favorites.message.value" role="alert" class="factor-note">{{ favorites.message.value }}</p>
      <div class="selected-factors" aria-label="已选因子"><span>已选</span><button v-for="name in selectedFactors" :key="name" :aria-label="`移除${factorChineseName(name)}`" @click="toggleFactor(name)">{{ factorChineseName(name) }} <span aria-hidden="true">×</span></button></div>
      <FactorParameterEditor v-model="factorParameters" :names="selectedFactors" :definitions="factors" />
      <FactorBenchmarkPicker v-if="benchmarkRequired" v-model="benchmark" />
      <p v-if="parameterError" class="error-banner" role="alert">{{ parameterError }}</p>
      <p v-for="warning in warmupWarnings" :key="warning" class="factor-note" role="status">{{ warning }}</p>
      <p v-for="warning in availabilityWarnings" :key="warning" class="factor-note" role="status">{{ warning }}</p>
      <p class="factor-note" role="status">登记 {{ catalogCounts.registered }} 个标识 · 去重 {{ catalogCounts.unique }} 项 · 当前周期／复权可计算 {{ catalogCounts.available }} 项 · 当前复权可截面检验 {{ catalogCounts.evaluation }} 项。仍需请求时核验数据；可计算不等于通过独立验收，旧别名默认隐藏。</p>
      <section class="factor-library">
        <div v-for="group in factorGroups" :key="group.key" class="factor-group">
          <header><h3>{{ group.label }}</h3><span>{{ group.items.length }} 项</span></header>
          <div v-for="factor in group.items" :key="String(factor.name)" class="factor-item" :class="{ selected: selectedFactors.includes(String(factor.name)) }">
            <button class="factor-select" :disabled="!!unavailableReason(factor)&&!selectedFactors.includes(String(factor.name))" :aria-pressed="selectedFactors.includes(String(factor.name))" @click="toggleFactor(String(factor.name))">
              <span class="check"><svg viewBox="0 0 16 16"><path d="m3.5 8 2.8 2.8 6.2-6.2" /></svg></span>
              <span><strong>{{ factorChineseName(String(factor.name)) }}</strong><small>{{ unavailableReason(factor)||factorChineseDescription(String(factor.name)) }}</small></span>
            </button>
            <FactorFavoriteButton :name="factorChineseName(String(factor.name))" :active="favorites.items.value.includes(favoriteKey(factor))" :busy="favorites.saving.value" @toggle="favorites.toggle(favoriteKey(factor))" />
            <button class="factor-help" :aria-label="`查看${factorChineseName(String(factor.name))}术语说明`" @click="openGlossary(String(factor.name))">释义</button>
          </div>
        </div>
      </section>
      <p v-if="!matchingFactors.length" class="factor-note">当前筛选没有结果。可切换到全部因子库或清空搜索。</p>
      <div v-else class="catalog-paging"><span>显示 {{ Math.min(factorLimit, matchingFactors.length) }} / {{ matchingFactors.length }} 项</span><button v-if="matchingFactors.length>factorLimit" @click="factorLimit+=24">再展开 24 项</button><button v-if="factorLimit>24" @click="factorLimit=24">收起列表</button></div>
      <p class="factor-note">普通窗口按所选周期的 K 线根数计算；条件样本数按参数标注另计。预热、缺失及不可用值显示为「—」，不是 0。</p>
      <p v-for="(message,key) in factorErrors" :key="key" class="error-banner status-banner">{{ factorChineseName(String(key)) }}：{{ message }}</p>
      <section class="factor-output">
        <div class="metric-rail">
          <div><small>标的</small><strong>{{ stockDisplayName(code) }}</strong></div>
          <div v-for="metric in factorMetrics" :key="metric.name"><small>{{ metric.name }}</small><strong>{{ factorValue(metric.value) }}</strong></div>
        </div>
        <div class="factor-results">
        <FactorArchiveTools mode="series" :result="factorResult" :busy="factorBusy" />
        <div v-if="factorRows.length" class="chart-mode"><MacSelect v-model="chartMode" aria-label="因子曲线布局" :options="[{value:'single',label:'单因子原值'},{value:'compare',label:'多因子分轨对比'}]" /></div>
        <ChartFrame v-if="factorRows.length&&chartMode==='single'" title="因子变化曲线" description="每次展示一个因子的原始尺度，缺失处不连线">
          <template #actions><MacSelect v-model="chartFactor" aria-label="曲线因子" :options="chartOptions" /></template>
          <FactorDiagnosticChart :precision="factorPrecision" :labels="factorRows.map(r=>String(r.datetime))" :series="[{name:factorChineseName(chartFactor),values:factorRows.map(r=>typeof r[chartFactor]==='number'?r[chartFactor] as number:null)}]" />
        </ChartFrame>
        <FactorSeriesComparison v-if="factorRows.length&&chartMode==='compare'" :key="factorGeneration" :rows="factorRows" :names="chartOptions.map(o=>o.value)" :labels="Object.fromEntries(chartOptions.map(o=>[o.value,o.label]))" :precision="factorPrecision" />
        <ChartFrame
          class="result-table"
          title="因子时间序列"
          :description="`全部 ${factorRows.length} 条已返回数据 · 未截断 · 支持横纵滚动查看`"
        >
          <template #actions><MacSelect v-model="factorPrecision" aria-label="因子显示精度" :options="[{value:'auto',label:'两位小数 · 小值科学计数'},{value:'raw',label:'原始精度'}]" /></template>
          <DataProvenance v-if="factorMetadata" :metadata="factorMetadata" :count="factorInputCount" />
          <details v-if="Object.keys(resultDefinitions).length" class="factor-note"><summary>本次计算的实际参数与公式</summary><section v-for="(definition,key) in resultDefinitions" :key="key"><h4>{{ definition.display_name }}</h4><FactorDefinitionDetails :definition="definition" /></section></details>
          <p v-for="(item,name) in factorDiagnostics" :key="name" class="factor-note">{{ factorChineseName(String(name)) }}：有效 {{ item.valid_count }} / {{ factorInputCount }} 根<span v-if="item.reason"> · {{ item.reason }}</span></p>
          <DataGrid :rows="formattedFactorRows" :columns="factorColumns" :empty-text="factorBusy ? '正在计算因子…' : '暂无结果'" />
        </ChartFrame>
        </div>
      </section>
    </template>

    <FactorEvaluationPanel v-else-if="tab==='evaluation'" :factors="factors" :names="factorNames" />
    <template v-else>
      <section class="risk-workspace">
        <aside class="risk-config">
          <div><span>组合风险模型</span><h3>组合设置</h3><p>以最近 500 根日线估计收益、相关性与风险贡献。</p></div>
          <StocksPicker v-model="stocks" category="DAY" />
          <div><label>权重模型</label><MacSelect v-model="method" :options="methodOptions" /></div>
          <AdjustPicker />
          <details v-if="riskProvenance.length" class="risk-provenance">
            <summary>数据与计算口径</summary>
            <p>{{ riskAlignment.note }}排除 {{ riskAlignment.excluded_observations ?? 0 }} 条非共同有效观测。</p>
            <p>{{ riskAlignment.start }} — {{ riskAlignment.end }}</p>
            <div v-for="item in riskProvenance" :key="item.market + item.code">
              <strong>{{ item.market }} · {{ item.code }}</strong>
              <DataProvenance v-if="item.metadata" :metadata="item.metadata" :count="item.count" />
            </div>
          </details>
          <button class="primary risk-button action-button" :disabled="loading" @click="runRisk">{{ loading ? '分析中' : '分析组合风险' }}</button>
        </aside>
        <div class="risk-results">
          <div class="risk-metrics"><div v-for="metric in riskMetrics" :key="metric.label"><small>{{ metric.label }}</small><strong>{{ metric.value }}</strong></div></div>
          <section class="risk-table"><header><h3>资产权重与风险贡献</h3><p>权重及风险贡献以百分比阅读</p></header><DataGrid :rows="assetRows" :columns="assetColumns" :empty-text="loading ? '正在估计风险…' : '运行后显示组合分析'" /></section>
          <section class="correlation-table"><header><h3>相关系数矩阵</h3><p>越接近 1，走势同步程度越高</p></header><DataGrid :rows="correlationRows" empty-text="暂无相关性数据" /></section>
        </div>
      </section>
    </template>

    <Teleport to="body">
      <Transition name="glossary-fade">
        <div v-if="showGlossary" class="glossary-backdrop" @click.self="closeGlossary">
          <section class="glossary-modal" role="dialog" aria-modal="true" aria-labelledby="glossary-title">
            <header class="glossary-header">
              <div><span>术语查询</span><h3 id="glossary-title">中英术语对照</h3><p>界面统一使用中文，英文名称集中在此处查询。</p></div>
              <button class="modal-close" aria-label="关闭术语对照" @click="closeGlossary">
                <svg viewBox="0 0 20 20"><path d="m6 6 8 8M14 6l-8 8"/></svg>
              </button>
            </header>
            <div class="glossary-tools">
              <label class="glossary-search"><span>搜索中文、英文或系统标识</span><input v-model="glossaryQuery" type="search" autocomplete="off" placeholder="例如：波动率、Volatility" autofocus /></label>
              <div class="glossary-scopes">
                <button :class="{ active: glossaryScope === 'all' }" @click="glossaryScope = 'all'">全部</button>
                <button :class="{ active: glossaryScope === 'factor' }" @click="glossaryScope = 'factor'">因子术语</button>
                <button :class="{ active: glossaryScope === 'risk' }" @click="glossaryScope = 'risk'">组合与风险</button>
              </div>
            </div>
            <div class="glossary-result-head"><span>中文名称</span><span>英文名称</span><span>{{ glossaryEntries.length }} 条结果</span></div>
            <div class="glossary-list">
              <article v-for="entry in glossaryEntries" :key="`${entry.scope}-${entry.key}`" class="glossary-entry">
                <div class="term-zh"><small>{{ entry.category }}</small><strong>{{ entry.zh }}</strong></div>
                <div class="term-en"><strong>{{ entry.en }}</strong><code>{{ entry.key }}</code></div>
                <p class="term-description">{{ entry.description }}</p>
                <FactorDefinitionDetails v-if="entry.scope==='factor' && factors.find(f=>f.name===entry.key)" :definition="factors.find(f=>f.name===entry.key)!" />
              </article>
              <div v-if="!glossaryEntries.length" class="glossary-empty">没有找到对应术语，请尝试其他关键词</div>
            </div>
          </section>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.series-task-status{border-bottom:1px solid var(--border);padding:0 0 12px;min-width:0}.series-task-status p{font-size:11px;line-height:1.8;color:var(--text-muted);overflow-wrap:anywhere}.series-task-status>div{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.series-task-status button,.series-task-status a{font-size:11px}.series-task-status a{color:var(--accent)}
.favorites-filter{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--text-muted)}.favorites-filter input{width:14px;height:14px;min-height:0;accent-color:var(--accent)}.favorites-filter span{font-size:11px}.chart-mode{display:flex;justify-content:flex-end;margin-block:12px}.chart-mode :deep(.mac-select){width:210px;max-width:100%}
.factor-controls{flex-wrap:wrap}
.catalog-toolbar{display:flex;align-items:center;gap:14px;min-width:0}.catalog-toolbar :deep(.mac-select){flex:0 0 230px}.catalog-toolbar .factor-search{flex:1;min-width:0}.selected-factors{display:flex;align-items:center;flex-wrap:wrap;gap:7px;font-size:11px;color:var(--text-dim);margin:8px 0}.selected-factors button{padding:5px 9px;font-size:11px}.selected-factors button span{margin-left:7px;color:var(--text-dim)}.catalog-paging{display:flex;gap:12px;align-items:center;padding:8px 0;color:var(--text-dim);font-size:11px}.catalog-paging button{padding:5px 10px;font-size:11px}@media(max-width:600px){.catalog-toolbar{flex-direction:column;align-items:stretch;gap:8px}.catalog-toolbar :deep(.mac-select){flex:auto}}
.factor-search{display:flex;gap:12px;align-items:center;font-size:11px;color:var(--text-muted)}.factor-search input{max-width:320px;flex:1;min-width:0}.factor-note{font-size:11px;line-height:1.7;color:var(--text-muted);margin:8px 0}.factor-select:disabled{opacity:.45;cursor:not-allowed}.quant-page{overflow-y:auto;overflow-x:hidden}.factor-output{flex-shrink:0}.header-actions nav{flex-wrap:wrap}.factor-output :deep(.factor-chart){min-height:310px}@media(max-width:760px){.quant-header{flex-wrap:wrap}.factor-controls{flex-wrap:wrap}.selected-count{margin-left:0!important}.factor-library{flex-shrink:0}.factor-search{flex-wrap:wrap}}
.quant-page{display:flex;height:100%;min-height:0;flex-direction:column;gap:12px}.quant-header{display:flex;align-items:center;justify-content:space-between;padding:15px 17px;background:linear-gradient(120deg,rgba(94,92,230,.1),rgba(10,132,255,.04));border:1px solid var(--border);border-radius:14px}.quant-header>div>span,.risk-config>div:first-child>span{color:#9491ff;font-size:9px;font-weight:750;letter-spacing:.16em}.quant-header h2{margin-top:2px;font-size:18px}.quant-header p,.risk-config p{color:var(--text-dim);font-size:10px}.quant-header nav{display:flex;padding:2px;background:rgba(0,0,0,.22);border:1px solid var(--border);border-radius:9px}.quant-header nav button{min-height:29px;color:var(--text-dim);background:transparent;border-color:transparent;box-shadow:none}.quant-header nav button.active{color:var(--text);background:rgba(255,255,255,.09);border-color:var(--border)}.status-banner{padding:8px 11px;border-radius:8px;font-size:11px}.factor-controls{display:flex;align-items:flex-end;gap:10px;padding:11px 13px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:12px}.period-field{width:140px}.selected-count{display:flex;height:35px;align-items:baseline;gap:3px;margin-left:auto;padding:7px 10px;background:rgba(0,0,0,.16);border:1px solid var(--border);border-radius:8px}.selected-count small{margin-right:5px;color:var(--text-dim);font-size:9px}.selected-count strong{font-size:15px}.selected-count span{color:var(--text-dim);font-size:9px}.run-button{min-height:35px}.factor-library{display:flex;min-height:132px;gap:8px;padding:9px;overflow-x:auto;background:rgba(255,255,255,.014);border:1px solid var(--border);border-radius:12px}.factor-group{min-width:210px;padding-right:8px;border-right:1px solid var(--border)}.factor-group:last-child{border-right:0}.factor-group header{display:flex;align-items:center;justify-content:space-between;padding:0 4px 5px}.factor-group h3{color:var(--text-dim);font-size:9px;letter-spacing:.08em;text-transform:uppercase}.factor-group header span{color:var(--text-dim);font-size:8px}.factor-group>button{width:100%;min-height:38px;justify-content:flex-start;padding:5px 7px;color:var(--text-muted);background:transparent;border-color:transparent;box-shadow:none;text-align:left}.factor-group>button:hover{background:rgba(255,255,255,.035)}.factor-group>button.selected{color:var(--text);background:rgba(10,132,255,.1);border-color:rgba(10,132,255,.18)}.factor-group button>span:last-child{display:flex;min-width:0;flex-direction:column}.factor-group strong{font:10px var(--font-mono)}.factor-group small{overflow:hidden;color:var(--text-dim);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.check{display:grid;width:16px;height:16px;place-items:center;flex:0 0 auto;border:1px solid var(--border-strong);border-radius:5px}.check svg{width:12px}.check path{fill:none;stroke:transparent;stroke-width:1.8}.selected .check{background:var(--accent);border-color:var(--accent)}.selected .check path{stroke:#fff}.factor-output{display:flex;min-height:0;flex:1;gap:10px}.metric-rail{width:170px;padding:8px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:12px;overflow-y:auto}.metric-rail>div{padding:8px;border-bottom:1px solid var(--border)}.metric-rail>div:last-child{border-bottom:0}.metric-rail small{display:block;overflow:hidden;color:var(--text-dim);font:8px var(--font-mono);text-overflow:ellipsis}.metric-rail strong{display:block;overflow:hidden;color:var(--text-muted);font-size:12px;text-overflow:ellipsis}.result-table,.risk-table,.correlation-table{display:flex;min-width:0;min-height:0;flex:1;flex-direction:column;padding:11px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:12px}.result-table header,.risk-table header,.correlation-table header{display:flex;align-items:center;justify-content:space-between;padding:0 3px 8px}.result-table h3,.risk-table h3,.correlation-table h3{font-size:12px}.result-table p,.risk-table p,.correlation-table p{color:var(--text-dim);font-size:9px}.risk-workspace{display:grid;min-height:0;flex:1;grid-template-columns:250px 1fr;gap:12px}.risk-config{display:flex;min-height:0;flex-direction:column;gap:15px;padding:16px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:13px;overflow-y:auto}.risk-config h3{margin-top:2px;font-size:15px}.risk-button{min-height:40px;margin-top:auto}.risk-results{display:grid;min-height:0;grid-template-rows:auto 1fr 1fr;gap:10px}.risk-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.risk-metrics>div{padding:10px 12px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:10px}.risk-metrics small{display:block;color:var(--text-dim);font-size:9px}.risk-metrics strong{font-size:17px}.correlation-table{flex:auto}@media(max-width:1000px){.quant-page{overflow:auto}.risk-workspace{grid-template-columns:1fr}.risk-config{min-height:280px}.factor-output{min-height:440px}}
.result-table:deep(.chart-frame-content){display:flex;min-height:0;flex:1}.result-table:deep(.data-grid-wrap){min-height:0;flex:1}.result-table:fullscreen,.result-table.fallback-expanded{border:0;border-radius:0;background:#0d0e12}
.header-actions{display:flex;align-items:center;gap:8px}.glossary-button{min-height:35px;padding:0 11px;color:var(--text-muted);background:rgba(255,255,255,.035);border-color:var(--border-strong);box-shadow:none}.glossary-button:hover{color:var(--text);background:rgba(255,255,255,.075);border-color:rgba(148,145,255,.45)}.glossary-button svg{width:14px;height:14px}.factor-item{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;margin-bottom:2px;border:1px solid transparent;border-radius:9px;transition:background .16s ease,border-color .16s ease}.factor-item:hover{background:rgba(255,255,255,.035)}.factor-item.selected{background:linear-gradient(90deg,rgba(10,132,255,.13),rgba(94,92,230,.075));border-color:rgba(94,157,255,.2)}.factor-select{width:100%;min-width:0;min-height:43px;justify-content:flex-start;padding:5px 5px 5px 7px;color:var(--text-muted);background:transparent;border:0;box-shadow:none;text-align:left}.factor-select:hover,.factor-select:focus-visible{background:transparent}.factor-item.selected .factor-select{color:var(--text)}.factor-help{min-height:24px;margin-right:5px;padding:0 7px;color:var(--text-dim);font-size:8px;background:transparent;border-color:transparent;border-radius:6px;box-shadow:none}.factor-help:hover,.factor-help:focus-visible{color:#bbb9ff;background:rgba(94,92,230,.13);border-color:rgba(148,145,255,.16)}

.glossary-backdrop{position:fixed;z-index:300;inset:0;display:grid;padding:24px;place-items:center;background:rgba(4,5,8,.67);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}.glossary-modal{display:flex;width:min(880px,calc(100vw - 40px));height:min(680px,calc(100vh - 48px));min-height:420px;flex-direction:column;overflow:hidden;background:linear-gradient(145deg,rgba(40,42,50,.98),rgba(21,22,27,.99));border:1px solid rgba(255,255,255,.13);border-radius:19px;box-shadow:0 28px 90px rgba(0,0,0,.56),0 0 0 1px rgba(0,0,0,.22)}.glossary-header{display:flex;align-items:flex-start;justify-content:space-between;padding:21px 23px 17px;border-bottom:1px solid var(--border)}.glossary-header .eyebrow{color:#a9a7ff;font-size:9px;font-weight:760;letter-spacing:.14em}.glossary-header h3{margin-top:3px;font-size:18px;letter-spacing:-.01em}.glossary-header p{margin-top:4px;color:var(--text-dim);font-size:10px}.glossary-close{display:grid;width:32px;height:32px;min-height:32px;padding:0;place-items:center;color:var(--text-dim);background:rgba(255,255,255,.035);border-color:var(--border);border-radius:50%;box-shadow:none}.glossary-close:hover{color:var(--text);background:rgba(255,255,255,.09)}.glossary-close svg{width:15px;height:15px}.glossary-tools{display:flex;align-items:flex-end;gap:14px;padding:14px 20px;background:rgba(0,0,0,.09);border-bottom:1px solid var(--border)}.glossary-search{display:flex;min-width:220px;flex:1;flex-direction:column;gap:5px}.glossary-search span{color:var(--text-dim);font-size:9px}.glossary-search input{width:100%;height:38px;padding:0 12px;color:var(--text);background:rgba(0,0,0,.22);border:1px solid var(--border-strong);border-radius:9px;outline:0}.glossary-search input:focus{border-color:rgba(10,132,255,.66);box-shadow:0 0 0 3px rgba(10,132,255,.12)}.glossary-scopes{display:flex;padding:2px;background:rgba(0,0,0,.22);border:1px solid var(--border);border-radius:9px}.glossary-scopes button{min-height:32px;padding:0 10px;color:var(--text-dim);font-size:9px;background:transparent;border-color:transparent;box-shadow:none}.glossary-scopes button.active{color:var(--text);background:rgba(255,255,255,.09);border-color:var(--border)}.glossary-result-head{display:grid;grid-template-columns:1fr 1fr 1.6fr;gap:16px;padding:9px 22px;color:var(--text-dim);font-size:8px;letter-spacing:.08em;border-bottom:1px solid var(--border)}.glossary-list{min-height:0;flex:1;overflow-y:auto}.glossary-entry{display:grid;grid-template-columns:1fr 1fr 1.6fr;gap:16px;align-items:start;padding:14px 22px;border-bottom:1px solid rgba(255,255,255,.055);transition:background .15s ease}.glossary-entry:hover{background:rgba(255,255,255,.026)}.term-zh,.term-en{display:flex;min-width:0;flex-direction:column;gap:3px}.term-zh strong{font-size:12px}.term-zh small{color:#9e9ca8;font-size:8px}.term-en strong{color:#c7c6d0;font:10px var(--font-mono);line-height:1.45}.term-en code{overflow:hidden;color:#817f8c;font:8px var(--font-mono);text-overflow:ellipsis;white-space:nowrap}.term-description{color:var(--text-muted);font-size:10px;line-height:1.65}.glossary-empty{display:grid;min-height:220px;place-items:center;color:var(--text-dim);font-size:11px}.glossary-fade-enter-active,.glossary-fade-leave-active{transition:opacity .18s ease}.glossary-fade-enter-active .glossary-modal,.glossary-fade-leave-active .glossary-modal{transition:transform .18s ease,opacity .18s ease}.glossary-fade-enter-from,.glossary-fade-leave-to{opacity:0}.glossary-fade-enter-from .glossary-modal,.glossary-fade-leave-to .glossary-modal{opacity:0;transform:translateY(8px) scale(.985)}

@media(max-width:760px){.quant-header{align-items:flex-start;gap:12px}.header-actions{width:100%;flex-wrap:wrap}.glossary-button{flex:1}.quant-header nav{flex:1}.quant-header nav button{flex:1}.glossary-backdrop{padding:10px}.glossary-modal{width:100%;height:calc(100vh - 20px);border-radius:15px}.glossary-tools{align-items:stretch;flex-direction:column}.glossary-scopes button{flex:1}.glossary-result-head{display:none}.glossary-entry{grid-template-columns:1fr;gap:8px;padding:14px 18px}.term-en{padding-top:6px;border-top:1px dashed var(--border)}}
.risk-config .risk-button{min-height:35px}
.glossary-header .modal-close svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.5}
.factor-results :deep(.chart-frame-actions .mac-select){width:220px;max-width:100%}
@media(max-width:760px){.header-actions nav{flex:1 0 100%}.quant-header nav button{white-space:nowrap}}
.result-table:deep(.chart-frame-content){flex-direction:column}
.risk-provenance{font-size:11px;line-height:1.7;overflow-wrap:anywhere}.risk-provenance summary{cursor:pointer;padding:8px 0}.risk-provenance p{color:var(--text-dim);margin:6px 0}.risk-provenance strong{font-size:11px;font-weight:500}
.factor-output{display:grid;grid-template-columns:170px minmax(0,1fr);align-items:start;flex:none}.factor-results{display:flex;min-width:0;flex-direction:column;gap:12px}.factor-results>.result-table{min-height:480px;max-height:680px}.metric-rail{box-sizing:border-box;width:100%;max-height:600px}.metric-rail strong{overflow-wrap:anywhere}.factor-group small{white-space:normal;line-height:1.5}.factor-note{flex-shrink:0}.factor-results :deep(.chart-frame-actions){min-width:0;flex-wrap:wrap}@media(max-width:760px){.factor-output{grid-template-columns:1fr}.metric-rail{display:flex;overflow:auto;gap:12px;max-height:none}.metric-rail>div{flex:0 0 125px;border-bottom:0}.factor-results>.result-table{max-height:580px}}

/* The route owns vertical scrolling; grids retain their own data scrolling. */
.quant-page{box-sizing:border-box;overflow-y:auto;overflow-x:hidden;overscroll-behavior-y:contain;scrollbar-gutter:stable;padding-bottom:max(24px,env(safe-area-inset-bottom))}
.quant-page>header,.quant-page>section,.quant-page>.status-banner{flex-shrink:0}
.factor-output{flex:none;min-height:460px}
.factor-output>.result-table{height:clamp(420px,60dvh,680px);flex:1;min-width:0}
.factor-library{flex-shrink:0;min-height:180px}
.metric-rail{min-width:0;flex-shrink:0;max-height:680px}
.risk-workspace{flex:none;min-height:650px;align-items:start}
.risk-results{min-width:0;grid-template-rows:auto minmax(260px,auto) minmax(260px,auto)}
.risk-config{min-width:0;overflow:visible}
.risk-table,.correlation-table{height:300px;min-width:0}
@media(max-width:760px){.factor-output{flex-direction:column}.factor-output>.metric-rail{width:100%;max-height:180px}.factor-output>.result-table{flex:none;width:100%;height:460px;box-sizing:border-box}.factor-controls{flex-wrap:wrap}.selected-count{margin-left:0}.risk-workspace{grid-template-columns:minmax(0,1fr)}.risk-config{min-height:0}.risk-results{min-width:0}.quant-header{flex-wrap:wrap;gap:12px}}
</style>
