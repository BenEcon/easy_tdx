// 回测状态管理（Pinia）。
// 持有：策略列表、当前 OHLCV、回测结果、运行状态、错误信息。

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import type { MarketDataMetadata } from '../market-data-contract'
import { researchInputFields } from '../research-input'
import { taskExecution } from '../task-execution'
import { useAuth } from '../auth'

import {
  fetchStrategies,
  formatError,
  runBacktest,
  submitPortfolioTask,
  submitOptimizeAllTask,
  submitOptimizeTask,
  submitMultiStrategyTask,
  fetchTask,
} from '../api'
import type {
  BacktestRequest,
  BacktestResult,
  Bar,
  Category,
  MultiStrategyBacktestRequest,
  PortfolioBacktestRequest,
  PortfolioResult,
  OptimizeAllBacktestRequest,
  OptimizeAllResult,
  OptimizeBacktestRequest,
  OptimizeResult,
  StrategySchema,
} from '../types'

export const useBacktestStore = defineStore('backtest', () => {
  // ── 策略 ─────────────────────────────────────────────────────────────────
  const strategies = ref<StrategySchema[]>([])
  const strategiesLoaded = ref(false)

  async function loadStrategies() {
    if (strategiesLoaded.value) return
    const resp = await fetchStrategies()
    if (!Array.isArray(resp.strategies) || !resp.strategies.length) {
      throw Error('策略目录为空或格式错误，请重试')
    }
    strategies.value = resp.strategies
    strategiesLoaded.value = true
  }

  // ── OHLCV 行情（前端始终持有，回测与 K 线共用） ───────────────────────────
  const ohlcv = ref<Bar[]>([])
  const barsSource = ref<string>('') // 来源描述，如 "SZ:000001 DAY×250"
  const barsMetadata = ref<MarketDataMetadata | null>(null)
  const barsContext = ref<import('../research-input').LoadedResearchInput | null>(null)
  const radarSource = ref<import('../radar-archive').RadarArchiveSource | null>(null)

  function setOhlcv(bars: Bar[], source: string, metadata: MarketDataMetadata | null = null,
    context: import('../research-input').LoadedResearchInput | null = null,
    originalSource: import('../radar-archive').RadarArchiveSource | null = null) {
    clearResult()
    ohlcv.value = bars
    barsSource.value = source
    barsMetadata.value = metadata
    barsContext.value = context ? { ...context } : null
    radarSource.value = originalSource
  }

  const hasBars = computed(() => ohlcv.value.length >= 2)

  // ── 回测结果 ──────────────────────────────────────────────────────────────
  const result = ref<BacktestResult | null>(null)
  const completed = ref<{owner:string;finishedAt:string;request:BacktestRequest;metadata:MarketDataMetadata|null;result:BacktestResult;radarSource:import('../radar-archive').RadarArchiveSource|null}|null>(null)
  const detach = <T,>(value:T):T => JSON.parse(JSON.stringify(value,(_key,item)=>{
    if(typeof item==='number'&&!Number.isFinite(item))throw Error('回测输入或结果含非有限数值')
    return item
  })) as T
  const running = ref(false)
  const error = ref<string>('')
  let runVersion = 0

  /** 运行同步回测（内联 OHLCV）。 */
  async function run(req: Omit<BacktestRequest, 'ohlcv'>) {
    const version = ++runVersion
    result.value = null; completed.value = null
    running.value = false
    if (!hasBars.value) {
      error.value = '请先取行情数据或粘贴 OHLCV'
      return
    }
    running.value = true
    error.value = ''
    try {
      const identity=owner()
      if(!identity)throw Error('请先登录再回测')
      const fullReq: BacktestRequest = detach({ ...req, ...researchInputFields(barsContext.value), ohlcv: ohlcv.value })
      const metadata=detach(barsMetadata.value),source=detach(radarSource.value)
      const next = await runBacktest(fullReq,identity)
      if (version === runVersion&&owner()===identity) {
        const frozen=detach({owner:identity,finishedAt:new Date().toISOString(),request:fullReq,metadata,result:next,radarSource:source})
        completed.value=frozen;result.value=detach(frozen.result)
      }
    } catch (e) {
      if (version === runVersion) { error.value = formatError(e); result.value = null }
    } finally {
      if (version === runVersion) running.value = false
    }
  }

  function clearResult() {
    runVersion++
    running.value = false
    result.value = null
    completed.value = null
    error.value = ''
  }

  // ── 组合回测（Phase 3） ───────────────────────────────────────────────────
  const {currentUser}=useAuth()
  const owner=()=>currentUser.value?.id
  const portfolioTask=taskExecution<PortfolioBacktestRequest,PortfolioResult>({owner,submit:submitPortfolioTask,poll:fetchTask,timeout:120_000,interval:300})
  const {result:portfolioResult,running:portfolioRunning,request:portfolioRequest}=portfolioTask
  let errorVersion=0
  async function runPortfolio(req:PortfolioBacktestRequest) {
    const version=++errorVersion;error.value=''
    const ok=await portfolioTask.run(req)
    if(version===errorVersion)error.value=portfolioTask.error.value
    return ok
  }
  function clearPortfolio(){errorVersion++;portfolioTask.clear();error.value=''}

  // ── 多策略组合回测（资金分仓） ─────────────────────────────────────────
  const multiTask=taskExecution<MultiStrategyBacktestRequest,PortfolioResult>({owner,submit:submitMultiStrategyTask,poll:fetchTask,timeout:180_000,interval:400})
  const {result:multiStrategyResult,running:multiStrategyRunning,request:multiStrategyRequest}=multiTask

  /** 提交多策略组合回测后台任务并轮询直到完成。
   * 结果结构同 PortfolioResult（复用组合页图表组件）。 */
  async function runMultiStrategy(req: MultiStrategyBacktestRequest) {
    const version=++errorVersion;error.value=''
    const ok=await multiTask.run(req)
    if(version===errorVersion)error.value=multiTask.error.value
    return ok
  }

  function clearMultiStrategy() {
    errorVersion++;multiTask.clear();error.value=''
  }

  // ── 参数网格寻优（Phase 4） ─────────────────────────────────────────────
  const optimizeTask=taskExecution<OptimizeBacktestRequest,OptimizeResult>({owner,submit:submitOptimizeTask,poll:fetchTask,timeout:180_000,interval:400})
  const {result:optimizeResult,running:optimizeRunning,request:optimizeRequest}=optimizeTask

  /** 寻优实际使用的标的上下文（取行情成功那一刻冻结）。
   * 放在 store 而非组件里，是为了在用户切走再回 /optimize 时，「查看」按钮仍能拼出正确 URL
   * —— 组件 ref 在卸载后丢失，而 store 与 optimizeResult 同生命周期保留。
   * 由 OptimizeView 在 loadBars() 成功后通过 setOptimizeContext() 写入。 */
  const optimizeContext = ref<{
    code: string
    category: Category
    startDate: string
    endDate: string
  } | null>(null)

  function setOptimizeContext(ctx: { code: string; category: Category; startDate: string; endDate: string }) {
    optimizeContext.value = ctx
  }

  /** 提交寻优后台任务并轮询直到完成。 */
  async function runOptimize(req: OptimizeBacktestRequest) {
    const version=++errorVersion;error.value=''
    const ok=await optimizeTask.run(req)
    if(version===errorVersion)error.value=optimizeTask.error.value
    return ok
  }

  // ── 一键寻优所有策略（Phase 6） ─────────────────────────────────────────
  const optimizeAllTask=taskExecution<OptimizeAllBacktestRequest,OptimizeAllResult>({owner,submit:submitOptimizeAllTask,poll:fetchTask,timeout:300_000,interval:500})
  const {result:optimizeAllResult,running:optimizeAllRunning,request:optimizeAllRequest}=optimizeAllTask

  /** 提交「一键寻优所有策略」后台任务并轮询直到完成。 */
  async function runOptimizeAll(req: OptimizeAllBacktestRequest) {
    const version=++errorVersion;error.value=''
    const ok=await optimizeAllTask.run(req)
    if(version===errorVersion)error.value=optimizeAllTask.error.value
    return ok
  }

  function clearOptimize(){errorVersion++;optimizeTask.clear();optimizeAllTask.clear();optimizeContext.value=null;error.value=''}
  function detachOptimize(){
    errorVersion++
    if(optimizeTask.running.value)optimizeTask.clear()
    if(optimizeAllTask.running.value)optimizeAllTask.clear()
    error.value=''
  }
  watch(()=>currentUser.value?.id,()=>{
    clearResult();clearPortfolio();clearMultiStrategy();clearOptimize()
    setOhlcv([], '', null, null)
  },{flush:'sync'})

  return {
    // state
    strategies,
    strategiesLoaded,
    ohlcv,
    barsSource,
    barsMetadata,
    barsContext,
    result,
    completed,
    running,
    error,
    portfolioResult,
    portfolioRunning,
    portfolioRequest,
    portfolioTaskId:portfolioTask.taskId,
    multiStrategyResult,
    multiStrategyRunning,
    multiStrategyRequest,
    multiStrategyTaskId:multiTask.taskId,
    optimizeResult,
    optimizeRunning,
    optimizeRequest,
    optimizeContext,
    optimizeAllResult,
    optimizeAllRunning,
    optimizeAllRequest,
    // getters
    hasBars,
    // actions
    loadStrategies,
    setOhlcv,
    run,
    clearResult,
    runPortfolio,
    clearPortfolio,
    runMultiStrategy,
    clearMultiStrategy,
    runOptimize,
    runOptimizeAll,
    setOptimizeContext,
    clearOptimize,
    detachOptimize,
  }
})
