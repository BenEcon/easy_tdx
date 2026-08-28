// 后端 API 封装。统一 fetch + 错误处理，返回类型化结果。
// 开发期通过 vite proxy 走 /api（同源），生产期由 FastAPI 同源托管。

import type {
  ApiError,
  AccountListResponse,
  AccountUser,
  AdjustMode,
  AuthStatus,
  BacktestRequest,
  BacktestResult,
  Bar,
  Category,
  ChanlunResult,
  MultiStrategyBacktestRequest,
  OptimizeAllBacktestRequest,
  OptimizeBacktestRequest,
  PortfolioBacktestRequest,
  SavedStrategy,
  SavedStrategyCreate,
  SavedStrategyListResponse,
  ServerHostInfo,
  ServerHostListResponse,
  ServerSwitchResult,
  SignalScanRequest,
  SignalScanResult,
  StrategiesResponse,
  TaskListResponse,
  TaskState,
  TaskSubmitResponse,
} from './types'

const BASE = '/api/v1'

export interface DataRowsResponse {
  data: Array<Record<string, unknown>>
  count: number
}

export interface DictDataResponse {
  data: Record<string, unknown>
}

function queryPath(path: string, params: Record<string, string | number | boolean | undefined>): string {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value))
  })
  const suffix = query.toString()
  return suffix ? `${path}?${suffix}` : path
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as T
}

/** 把未知错误格式化为用户可读的消息（网络错误给友好提示）。 */
export function formatError(e: unknown): string {
  if (e instanceof TypeError && e.message.includes('fetch')) {
    return '网络错误：无法连接后端服务，请确认 easy-tdx serve 已启动'
  }
  return e instanceof Error ? e.message : String(e)
}

/** 把 Response 解析为 ApiError 抛出（后端统一错误格式 {error, detail}）。 */
async function throwError(resp: Response): Promise<never> {
  let detail = `${resp.status} ${resp.statusText}`
  try {
    const body = (await resp.json()) as ApiError
    if (body?.detail) detail = body.detail
  } catch {
    // 非 JSON 错误体，用 statusText
  }
  throw new Error(detail)
}

// ── 账户认证与管理员平台 ───────────────────────────────────────────────────

export function fetchAuthStatus(): Promise<AuthStatus> {
  return request<AuthStatus>('/auth/status')
}

export async function loginAccount(username: string, password: string): Promise<AccountUser> {
  const body = await request<{ user: AccountUser }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  return body.user
}

export async function setupAdmin(username: string, password: string): Promise<AccountUser> {
  const body = await request<{ user: AccountUser }>('/auth/setup', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  return body.user
}

export function logoutAccount(): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>('/auth/logout', { method: 'POST' })
}

export async function fetchMyAccount(): Promise<AccountUser> {
  const body = await request<{ user: AccountUser }>('/auth/me')
  return body.user
}

export async function saveAccountPreferences(
  preferences: Record<string, unknown>,
): Promise<AccountUser> {
  const body = await request<{ user: AccountUser }>('/auth/me/preferences', {
    method: 'PUT',
    body: JSON.stringify({ preferences }),
  })
  return body.user
}

export function changeAccountPassword(currentPassword: string, newPassword: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
}

export function fetchAccounts(): Promise<AccountListResponse> {
  return request<AccountListResponse>('/admin/users')
}

export async function createAccount(
  username: string,
  password: string,
  role: 'admin' | 'user',
): Promise<AccountUser> {
  const body = await request<{ user: AccountUser }>('/admin/users', {
    method: 'POST',
    body: JSON.stringify({ username, password, role }),
  })
  return body.user
}

export async function updateAccount(
  id: string,
  update: { role?: 'admin' | 'user'; active?: boolean },
): Promise<AccountUser> {
  const body = await request<{ user: AccountUser }>(`/admin/users/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(update),
  })
  return body.user
}

export function resetAccountPassword(id: string, newPassword: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/admin/users/${id}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword }),
  })
}

export function fetchAdminDataStatus(): Promise<{
  capabilities: Array<Record<string, unknown>>
  tdx_home: string | null
  vipdoc: string | null
  offline: Record<string, unknown>
  config_dir: string
}> {
  return request('/admin/data/status')
}

/** 枚举预置策略 + 参数 schema。 */
export async function fetchStrategies(): Promise<StrategiesResponse> {
  const resp = await fetch(`${BASE}/backtest/strategies`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as StrategiesResponse
}

/**
 * 按标的取 K 线行情（OHLCV）。
 *
 * 后端 /bars 单次最多 800 根。当 startDate 到 endDate 跨度超过 800 根时，
 * 自动分页拉取（start=0, 800, 1600...）拼接，直到覆盖 startDate 或达上限。
 * 可选 startDate/endDate 对结果做闭区间过滤（ISO 日期字符串，如 "2024-01-01"）。
 */
const MAX_PAGES = 10 // 翻页上限：10 × 800 = 8000 根（约 32 年日线）

export async function fetchBars(
  market: string,
  code: string,
  category: Category,
  startDate?: string,
  endDate?: string,
  adjust: AdjustMode = 'QFQ',
): Promise<Bar[]> {
  let allBars: Bar[] = []
  for (let page = 0; page < MAX_PAGES; page++) {
    const params = new URLSearchParams({
      market,
      code,
      category,
      count: '800',
      start: String(page * 800),
      adjust,
    })
    const resp = await fetch(`${BASE}/bars?${params}`)
    if (!resp.ok) await throwError(resp)
    const body = (await resp.json()) as { data: Record<string, unknown>[] }
    const pageBars = body.data.map((row) => normalizeBar(row))
    if (pageBars.length === 0) break // 无更多数据

    allBars = allBars.concat(pageBars)

    // 若已覆盖到 startDate（本页最早一根 ≤ startDate），停止翻页
    if (startDate && pageBars.length > 0) {
      const oldest = pageBars[pageBars.length - 1].datetime.slice(0, 10)
      if (oldest <= startDate) break
    }
    // 不足 800 根说明已到数据起点
    if (pageBars.length < 800) break
  }

    // 按日期范围过滤（闭区间）
    let bars = allBars
    if (startDate) bars = bars.filter((b) => b.datetime.slice(0, 10) >= startDate)
    if (endDate) bars = bars.filter((b) => b.datetime.slice(0, 10) <= endDate)
    // 翻页拼接后按时间正序排序：每页内部是正序，但页间是逆序
    // （page1=最新段，page2=更旧段），concat 后需排序保证整体正序，
    // 否则引擎/图表只正确处理第一页的数据。
    bars.sort((a, b) => a.datetime.localeCompare(b.datetime))
    return bars
}

/** 批量读取股票简称，用于把历史记录展示为「代码-名称」。 */
export async function fetchStockNames(
  stocks: Array<{ market: string; code: string }>,
): Promise<Record<string, string>> {
  if (stocks.length === 0) return {}
  const resp = await fetch(`${BASE}/quotes`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stocks }),
  })
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as { data: Array<Record<string, unknown>> }
  const names = Object.fromEntries(body.data.flatMap((row) => {
    const code = String(row.code ?? '')
    const name = String(row.name ?? '').trim()
    return code && name ? [[code, name]] : []
  }))
  // 部分标准行情节点会返回空批量报价；Mac 快照接口可作为稳定的名称回退源。
  const missing = stocks.filter((stock) => !names[stock.code])
  if (missing.length) {
    const fallback = await Promise.allSettled(missing.map((stock) => (
      request<DataRowsResponse>(queryPath('/mac/symbol-info', stock))
    )))
    fallback.forEach((result, index) => {
      if (result.status !== 'fulfilled') return
      const row = result.value.data[0]
      const name = String(row?.name ?? '').trim()
      if (name) names[missing[index].code] = name
    })
  }
  return names
}

// ── 行情、板块与公司研究 ───────────────────────────────────────────────────

export function fetchMarketRanking(params: {
  category: string
  count?: number
  sortType?: string
  sortOrder?: 'ASC' | 'DESC'
}): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/mac/quote-list', {
    category: params.category,
    count: params.count ?? 80,
    sort_type: params.sortType ?? 'CHANGE_PCT',
    sort_order: params.sortOrder ?? 'DESC',
  }))
}

export function fetchMarketUnusual(market: string, count = 80): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/mac/unusual', { market, count }))
}

export function fetchMarketStat(): Promise<DataRowsResponse> {
  return request<DataRowsResponse>('/market/stat')
}

export function fetchBoardList(params: {
  boardType: string
  sortColumn?: string
  count?: number
}): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/board-mac/list', {
    board_type: params.boardType,
    sort_column: params.sortColumn ?? 'CHANGE_PCT',
    count: params.count ?? 200,
  }))
}

export function fetchBoardMembers(boardSymbol: string, count = 200): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/board-mac/members', {
    board_symbol: boardSymbol,
    count,
  }))
}

export function fetchBoardBelong(market: string, code: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/board-mac/belong', { market, code }))
}

export function fetchQuote(market: string, code: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>('/quotes', {
    method: 'POST',
    body: JSON.stringify({ stocks: [{ market, code }] }),
  })
}

export function fetchSymbolInfo(market: string, code: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/mac/symbol-info', { market, code }))
}

export function fetchCapitalFlow(market: string, code: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/mac/capital-flow', { market, code }))
}

export function fetchFundFlowHistory(market: string, code: string, count = 100): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/fund-flow/history', { market, code, count }))
}

export function fetchAuction(market: string, code: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/mac/auction', { market, code }))
}

export function fetchFinanceInfo(market: string, code: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/finance', { market, code }))
}

export function fetchXdxrInfo(market: string, code: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/xdxr', { market, code }))
}

export function fetchAnnouncements(code: string, count = 30): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/announcements', { code, count }))
}

export function fetchFinancialReport(
  code: string,
  reportType: 'lrb' | 'fzb' | 'llb',
  num = 8,
): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/sina/financial-report', {
    code,
    type: reportType,
    num,
  }))
}

// ── 盘中研究、深层资料与高级市场能力 ───────────────────────────────────────

export function fetchMinuteData(market: string, code: string, date?: string): Promise<DataRowsResponse> {
  const normalizedDate = date?.replaceAll('-', '')
  return request<DataRowsResponse>(queryPath(normalizedDate ? '/minute/history' : '/minute', {
    market, code, date: normalizedDate,
  }))
}

export function fetchTransactionData(
  market: string,
  code: string,
  date?: string,
  count = 800,
): Promise<DataRowsResponse> {
  const normalizedDate = date?.replaceAll('-', '')
  return request<DataRowsResponse>(queryPath(normalizedDate ? '/transaction/history' : '/transaction', {
    market, code, date: normalizedDate, start: 0, count,
  }))
}

export function fetchIndexBars(
  market: string,
  code: string,
  category = 'DAY',
  count = 300,
): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/bars/index', { market, code, category, start: 0, count }))
}

export function fetchServerSession(): Promise<DataRowsResponse> {
  return request<DataRowsResponse>('/mac/server-info')
}

export function fetchSecurityDirectory(market: string, start = 0): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/security/list', { market, start }))
}

export function fetchSecurityCount(market: string): Promise<{ count: number }> {
  return request<{ count: number }>(queryPath('/security/count', { market }))
}

export function fetchMarketStrength(params: {
  preset: 'steady' | 'breakout' | 'balanced'
  universe: 'all' | 'sh' | 'sz'
  topN?: number
  minAmount?: number
}): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/market/strength', {
    preset: params.preset,
    universe: params.universe,
    top_n: params.topN ?? 50,
    min_amount: params.minAmount ?? 0,
  }))
}

export function fetchCurrentFundFlow(market: string, code: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/fund-flow', { market, code }))
}

export function fetchBoardSummary(boardSymbol: string): Promise<DictDataResponse> {
  return request<DictDataResponse>(queryPath('/board-mac/summary', { board_symbol: boardSymbol }))
}

export function fetchBoardRanking(params: {
  boardType: string
  topN?: number
  sortBy?: string
  ascending?: boolean
}): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/board-mac/ranking', {
    board_type: params.boardType,
    top_n: params.topN ?? 30,
    sort_by: params.sortBy ?? 'change_pct',
    ascending: params.ascending ?? false,
  }))
}

export function fetchBoardChangeRanking(params: {
  boardType: string
  days: number
  topN?: number
  ascending?: boolean
}): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/board-mac/change-ranking', {
    board_type: params.boardType,
    days: params.days,
    top_n: params.topN ?? 30,
    ascending: params.ascending ?? false,
  }))
}

export function fetchBlockInfo(filename: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/block', { filename }))
}

export function fetchCompanyCategories(market: string, code: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/company/category', { market, code }))
}

export function fetchCompanyContent(
  market: string,
  code: string,
  category: Record<string, unknown>,
): Promise<{ content: string }> {
  return request<{ content: string }>(queryPath('/company/content', {
    market,
    code,
    filename: String(category.filename ?? ''),
    offset: Number(category.start ?? 0),
    length: Number(category.length ?? 1024),
  }))
}

export function fetchFinancialFiles(): Promise<DataRowsResponse> {
  return request<DataRowsResponse>('/financial/file-list')
}

export function fetchFinancialRecords(filename: string, code?: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/financial/records', { filename, code }))
}

export function fetchIndicatorList(): Promise<Array<Record<string, unknown>>> {
  return request<Array<Record<string, unknown>>>('/indicator/list')
}

export function computeIndicators(
  data: Array<Record<string, unknown>>,
  indicators: string[],
  params?: Record<string, Record<string, number>>,
): Promise<DataRowsResponse> {
  return request<DataRowsResponse>('/indicator/compute', {
    method: 'POST',
    body: JSON.stringify({ data, indicators, params, keep_ohlcv: false }),
  })
}

export function fetchExtendedMarket(
  kind: 'bars' | 'quote' | 'minute' | 'transaction',
  market: string,
  code: string,
  category = 'DAY',
): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath(`/ex/${kind}`, {
    market, code, category: kind === 'bars' ? category : undefined,
    start: kind === 'bars' || kind === 'transaction' ? 0 : undefined,
    count: kind === 'bars' ? 500 : kind === 'transaction' ? 1000 : undefined,
  }))
}

export function fetchExtendedMarkets(): Promise<DataRowsResponse> {
  return request<DataRowsResponse>('/ex/markets')
}

export function fetchExtendedInstruments(market: string, start = 0, count = 500): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/ex/instruments', { market, start, count }))
}

export function fetchResearchFactors(): Promise<Array<Record<string, unknown>>> {
  return request<Array<Record<string, unknown>>>('/research/factors')
}

export function computeResearchFactors(payload: {
  market: string
  code: string
  category: string
  count: number
  factors: string[]
  adjust?: AdjustMode
}): Promise<DictDataResponse> {
  return request<DictDataResponse>('/research/factors/compute', {
    method: 'POST', body: JSON.stringify(payload),
  })
}

export function analyzePortfolioRisk(payload: {
  stocks: Array<{ market: string; code: string }>
  method: 'equal' | 'factor_weighted' | 'risk_parity' | 'mean_variance'
  category: string
  count: number
  adjust?: AdjustMode
}): Promise<DictDataResponse> {
  return request<DictDataResponse>('/research/portfolio-risk', {
    method: 'POST', body: JSON.stringify(payload),
  })
}

/** 把后端 bars 的单条记录归一化为统一 Bar（datetime 字段）。 */
function normalizeBar(row: Record<string, unknown>): Bar {
  const raw = (row.datetime ?? row.date) as string | undefined
  if (!raw) throw new Error('行情数据缺少 datetime/date 字段')
  return {
    datetime: raw.slice(0, 19).replace(' ', 'T'),
    open: Number(row.open),
    high: Number(row.high),
    low: Number(row.low),
    close: Number(row.close),
    vol: Number(row.vol),
    amount: Number(row.amount),
  }
}

/** 获取最近 N 根 K 线，供缠论主图与后端结构分析使用同一时间窗口。 */
export async function fetchRecentBars(
  market: string,
  code: string,
  category: Category,
  count: number,
  adjust: AdjustMode = 'QFQ',
): Promise<Bar[]> {
  const params = new URLSearchParams({
    market,
    code,
    category,
    count: String(count),
    start: '0',
    adjust,
  })
  const resp = await fetch(`${BASE}/bars?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as { data: Record<string, unknown>[] }
  return body.data.map(normalizeBar).sort((a, b) => a.datetime.localeCompare(b.datetime))
}

/** 执行完整缠论管道：K 线合并 → 分型 → 笔 → 中枢 → 线段 → 买卖点 → 背驰。 */
export async function analyzeChanlun(req: {
  market: string
  code: string
  category: Category
  count: number
  start?: number
  adjust?: AdjustMode
}): Promise<ChanlunResult> {
  const resp = await fetch(`${BASE}/chanlun/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...req, start: req.start ?? 0 }),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as ChanlunResult
}

/** 同步回测（内联 OHLCV，快速）。 */
export async function runBacktest(req: BacktestRequest): Promise<BacktestResult> {
  const resp = await fetch(`${BASE}/backtest/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as BacktestResult
}

/** 提交后台回测任务，返回 task_id。 */
export async function submitBacktestTask(req: BacktestRequest): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交组合回测后台任务，返回 task_id。 */
export async function submitPortfolioTask(
  req: PortfolioBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/portfolio/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交多策略组合回测后台任务（资金分仓），返回 task_id。 */
export async function submitMultiStrategyTask(
  req: MultiStrategyBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/multi-strategy/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交参数网格寻优后台任务，返回 task_id。 */
export async function submitOptimizeTask(
  req: OptimizeBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/optimize/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交「一键寻优所有策略」后台任务，返回 task_id。 */
export async function submitOptimizeAllTask(
  req: OptimizeAllBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/optimize-all/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 查询后台任务状态（轮询用）。 */
export async function fetchTask(taskId: string): Promise<TaskState> {
  const resp = await fetch(`${BASE}/backtest/tasks/${taskId}`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskState
}

/** 列出最近任务摘要（供对比页选择）。 */
export async function fetchTaskList(limit = 20): Promise<TaskListResponse> {
  const resp = await fetch(`${BASE}/backtest/tasks?limit=${limit}`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskListResponse
}

/**
 * 提交后台任务并轮询直到 done/failed。
 * @param req 回测请求
 * @param onPoll 每次轮询回调（可选，用于更新 UI 进度）
 * @param intervalMs 轮询间隔（默认 300ms）
 * @param timeoutMs 总超时（默认 120s）
 */
export async function runBacktestWithPolling(
  req: BacktestRequest,
  onPoll?: (state: TaskState) => void,
  intervalMs = 300,
  timeoutMs = 120_000,
): Promise<TaskState> {
  const { task_id } = await submitBacktestTask(req)
  const start = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const state = await fetchTask(task_id)
    onPoll?.(state)
    if (state.status === 'done' || state.status === 'failed') return state
    if (Date.now() - start > timeoutMs) {
      throw new Error(`回测任务超时（${timeoutMs / 1000}s）`)
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

// ── 策略库（已保存策略）──────────────────────────────────────────────────────

/** 提交「信号雷达」一键扫描后台任务，返回 task_id。 */
export async function submitSignalScanTask(
  req: SignalScanRequest = {},
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/signal-scan/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/**
 * 提交信号扫描并轮询直到 done/failed。
 *
 * 与 runBacktestWithPolling 的区别：扫描要在请求内逐标的取行情（提交本身
 * 就可能耗时数十秒），且标的较多时总时长可能超过 2 分钟，故默认 300s 超时。
 */
export async function runSignalScanWithPolling(
  req: SignalScanRequest = {},
  onPoll?: (state: TaskState) => void,
  intervalMs = 500,
  timeoutMs = 300_000,
): Promise<TaskState> {
  const { task_id } = await submitSignalScanTask(req)
  const start = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const state = await fetchTask(task_id)
    onPoll?.(state)
    if (state.status === 'done' || state.status === 'failed') return state
    if (Date.now() - start > timeoutMs) {
      throw new Error(`信号扫描超时（${timeoutMs / 1000}s），可稍后重试或减小窗口`)
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

/** 断言任务结果为信号扫描结果（类型收窄用）。 */
export function asSignalScanResult(state: TaskState): SignalScanResult {
  if (state.status === 'failed') throw new Error(state.error || '信号扫描失败')
  const result = state.result as SignalScanResult | null
  if (!result || !Array.isArray(result.rows)) {
    throw new Error('信号扫描结果格式异常（缺少 rows）')
  }
  return result
}

/** 列出全部已保存策略（按创建时间倒序）。 */
export async function fetchSavedStrategies(): Promise<SavedStrategyListResponse> {
  const resp = await fetch(`${BASE}/strategies`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategyListResponse
}

/** 查看单条已保存策略。 */
export async function fetchSavedStrategy(id: string): Promise<SavedStrategy> {
  const resp = await fetch(`${BASE}/strategies/${id}`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategy
}

/** 保存一条策略（含当时的标的上下文与成绩快照）。 */
export async function saveStrategy(req: SavedStrategyCreate): Promise<SavedStrategy> {
  const resp = await fetch(`${BASE}/strategies`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategy
}

/** 更新一条已有策略，保留其 id 与创建时间。 */
export async function updateSavedStrategy(id: string, req: SavedStrategyCreate): Promise<SavedStrategy> {
  const resp = await fetch(`${BASE}/strategies/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategy
}

/** 删除一条已保存策略。 */
export async function deleteSavedStrategy(id: string): Promise<void> {
  const resp = await fetch(`${BASE}/strategies/${id}`, { method: 'DELETE' })
  if (!resp.ok) await throwError(resp)
}

// ── 服务器设置 ──────────────────────────────────────────────────────────────

/** 列出所有候选通达信服务器 + 当前使用的 host（不含延迟，需点测速）。 */
export async function fetchServerHosts(): Promise<ServerHostListResponse> {
  const resp = await fetch(`${BASE}/server/hosts`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as ServerHostListResponse
}

/** 并发测速全部（或指定）host，返回延迟和可达性。 */
export async function testServerHosts(hosts?: string[]): Promise<ServerHostInfo[]> {
  const resp = await fetch(`${BASE}/server/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hosts: hosts ?? null }),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as ServerHostInfo[]
}

/** 切换到指定 host（热重连，无需重启服务）。 */
export async function switchServerHost(host: string): Promise<ServerSwitchResult> {
  const resp = await fetch(`${BASE}/server/switch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ host }),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as ServerSwitchResult
}
