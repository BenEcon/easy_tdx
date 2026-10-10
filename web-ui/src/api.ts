// 后端 API 封装。统一 fetch + 错误处理，返回类型化结果。
// 开发期通过 vite proxy 走 /api（同源），生产期由 FastAPI 同源托管。
import { assertMarketData, type MarketDataMetadata } from './market-data-contract.ts'
import { isTaskTerminal, taskFailureMessage, validateTaskList } from './task-state.ts'
import { queryIntentHeaders } from './query-origin.ts'
import { frozenRadarSnapshot } from './radar-evidence.ts'

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

type ResearchRequest = { code: string; category: Category; bars: Bar[]; visible_count: number; structure_settings?: import('./structure-settings').StructureSettings }
export function replayExhaustive(req: ResearchRequest & {cursor?: string | null; page_size?: number}, signal?: AbortSignal) {
  return request<import('./exhaustive-research').SearchPage>('/chanlun/replay/exhaustive', {method: 'POST', body: JSON.stringify(req), signal})
}
export function replayCandidateAudit(req: ResearchRequest & {solution_token?: string; offset?: number}, signal?: AbortSignal) {
  return request<import('./exhaustive-research').CandidateAudit>('/chanlun/replay/candidate-audit', {method: 'POST', body: JSON.stringify(req), signal})
}

export function replayReleaseHistory(req: ResearchRequest & { start_count: number }, signal?: AbortSignal) {
  return request<import('./release-review').ReleaseHistoryBatch>('/chanlun/replay/release-history', {
    method: 'POST', body: JSON.stringify(req), signal,
  })
}

export function replayReleaseComparison(req: ResearchRequest, signal?: AbortSignal) {
  return request<import('./release-review').ReleaseComparison>('/chanlun/replay/release-comparison', {
    method: 'POST', body: JSON.stringify(req), signal,
  })
}

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
      ...queryIntentHeaders(),
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as T
}

/** 把未知错误格式化为用户可读的消息（网络错误给友好提示）。 */
export function formatError(e: unknown): string {
  if (e instanceof TypeError && /fetch|load failed|networkerror/i.test(e.message)) {
    return '网络错误：暂时无法连接服务器，请稍后重试'
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
  throw Object.assign(new Error(detail), {status:resp.status})
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
  owner: string,
  trackingRevision?: string,
): Promise<AccountUser> {
  const body = await request<{ user: AccountUser }>('/auth/me/preferences', {
    method: 'PATCH',
    headers: { 'X-Preferences-Owner': owner },
    body: JSON.stringify({ preferences, ...(trackingRevision===undefined?{}:{tracking_revision:trackingRevision}) }),
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

export function fetchAuditRecords(filters: {
  before?: number; action?: string; outcome?: string; limit?: number
} = {}): Promise<import('./security-audit').AuditPage> {
  return request(queryPath('/admin/audit', filters))
}

export function logoutAllDevices(): Promise<{ ok: boolean }> {
  return request('/auth/logout-all', { method: 'POST' })
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
  update: { role?: 'admin' | 'user'; active?: boolean; tracking_allowed?: boolean },
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
 * 后端统一分页、复核重叠及首段，并返回完整区间的数据口径。
 * 到达上限但未覆盖请求范围时明确报错，不使用被截断的数据。
 * 可选 startDate/endDate 对结果做闭区间过滤（ISO 日期字符串，如 "2024-01-01"）。
 */
export async function fetchBars(
  market: string,
  code: string,
  category: Category,
  startDate?: string,
  endDate?: string,
  adjust: AdjustMode = 'QFQ',
  onMetadata?: (metadata: MarketDataMetadata) => void,
  signal?: AbortSignal,
): Promise<Bar[]> {
  const params = new URLSearchParams({ market, code, category, adjust })
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const body = await request<{ data: Record<string, unknown>[]; metadata: MarketDataMetadata }>(`/bars/range?${params}`, { signal })
  if (signal?.aborted) throw new DOMException('查询已取消', 'AbortError')
  assertMarketData(body.metadata, adjust)
  const bars = body.data.map(normalizeBar)
  if (bars.some(bar => bar.is_closed !== true)) throw new Error('历史查询包含未确认收盘的数据，已停止分析')
  onMetadata?.(body.metadata)
  return bars
}

/** 批量读取股票简称，用于把历史记录展示为「代码-名称」。 */
export async function fetchStockNames(
  stocks: Array<{ market: string; code: string }>,
  signal?: AbortSignal,
): Promise<Record<string, string>> {
  if (stocks.length === 0) return {}
  const resp = await fetch(`${BASE}/quotes`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stocks }),
    signal,
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
      request<DataRowsResponse>(queryPath('/mac/symbol-info', stock), { signal })
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
}, signal?: AbortSignal): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/board-mac/list', {
    board_type: params.boardType,
    sort_column: params.sortColumn ?? 'CHANGE_PCT',
    count: params.count ?? 200,
  }), { signal })
}

export function fetchBoardMembers(boardSymbol: string, count = 200, signal?: AbortSignal, trackingOwner?: string): Promise<DataRowsResponse> {
  return request<DataRowsResponse>(queryPath('/board-mac/members', {
    board_symbol: boardSymbol,
    count,
  }), { signal, headers: trackingOwner ? {'X-Tracking-Owner':trackingOwner} : {} })
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

export async function fetchIndexBars(
  market: string,
  code: string,
  category = 'DAY',
  count = 300,
): Promise<DataRowsResponse & { metadata: MarketDataMetadata }> {
  const snapshot = await request<DataRowsResponse & { metadata: MarketDataMetadata }>(queryPath('/bars/index', {
    market, code, category, start: 0, count, bar_time: 'native',
  }))
  assertMarketData(snapshot.metadata, 'NONE')
  return snapshot
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

export function submitFactorRecomputeTask(payload:{source_archive_id:string;expected_digest:string;expected_revision:number},context:{owner:string;signal:AbortSignal}):Promise<TaskSubmitResponse> {
  return request('/research/factors/recompute/async',{method:'POST',body:JSON.stringify(payload),signal:context.signal,headers:{'X-Task-Owner':context.owner,'X-Research-Owner':context.owner}})
}

export function evaluateResearchFactors(payload:{stocks:Array<{market:string;code:string}>;factors:string[];factor_parameters?:import('./factor-parameters').FactorParameters;count:number;horizon:number;horizons?:number[]|null;groups:number;preprocess:string;adjust:string;validation?:import('./factor-validation').FactorValidationConfig|null;composition?:import('./factor-composition').CompositionConfig|null;benchmark?:string|null},signal?:AbortSignal) {
  return request<{data:import('./factor-research').FactorEvaluation}>('/research/factors/evaluate',{method:'POST',body:JSON.stringify(payload),signal})
}

export function submitFactorEvaluationTask(payload:Parameters<typeof evaluateResearchFactors>[0],context:{owner:string;signal:AbortSignal}):Promise<TaskSubmitResponse> {
  return request('/research/factors/evaluate/async',{method:'POST',body:JSON.stringify(payload),signal:context.signal,headers:{'X-Task-Owner':context.owner}})
}

export function computeResearchFactors(payload: {
  market: string
  code: string
  category: string
  count: number
  factors: string[]
  factor_parameters?: import('./factor-parameters').FactorParameters
  benchmark?: string|null
  adjust?: AdjustMode
}, signal?: AbortSignal): Promise<DictDataResponse> {
  return request<DictDataResponse>('/research/factors/compute', {
    method: 'POST', body: JSON.stringify(payload), signal,
  })
}

export function submitFactorSeriesTask(payload:Parameters<typeof computeResearchFactors>[0],context:{owner:string;signal:AbortSignal}):Promise<TaskSubmitResponse> {
  return request('/research/factors/compute/async',{method:'POST',body:JSON.stringify(payload),signal:context.signal,headers:{'X-Task-Owner':context.owner}})
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
    period_end: typeof row.period_end === 'string' ? row.period_end : undefined,
    is_closed: typeof row.is_closed === 'boolean' ? row.is_closed : undefined,
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
  return (await fetchBarSnapshot(market, code, category, count, adjust)).bars
}

export interface BarSnapshot {
  bars: Bar[]
  metadata: MarketDataMetadata
  radarSource?: import('./radar-archive').RadarArchiveSource
}

export async function fetchRadarSnapshot(review: import('./radar-review').RadarReview, owner: string, signal?: AbortSignal): Promise<BarSnapshot> {
  if(!owner||!review.evidence)throw Error('请使用原账户重新打开扫描记录')
  const data=await request<unknown>(`/backtest/tasks/${encodeURIComponent(review.evidence.taskId)}/scan-evidence/${review.evidence.rowIndex}`,{signal,cache:'no-store',headers:{'X-Task-Owner':owner}})
  return frozenRadarSnapshot(data,review)
}

export async function fetchResearchSnapshot(target: import('./chanlun-target').ResearchTarget, category: Category | 'MIN_120', count: number, adjust: AdjustMode = 'QFQ', signal?: AbortSignal, trackingOwner?: string): Promise<BarSnapshot> {
  if (target.kind === 'stock') return fetchBarSnapshot(target.market, target.code, category, count, adjust, signal, trackingOwner)
  const body = await request<{data: Record<string, unknown>[]; metadata: BarSnapshot['metadata']}>(queryPath('/bars/research', {
    kind: target.kind, code: target.code, market: target.kind === 'index' ? target.market : 'SH',
    board_type: target.boardType ?? 'HY', category, count,
  }), { signal, headers:trackingOwner ? {'X-Tracking-Owner':trackingOwner} : {} })
  assertMarketData(body.metadata, 'NONE')
  return { bars: body.data.map(normalizeBar).sort((a, b) => a.datetime.localeCompare(b.datetime)), metadata: body.metadata }
}

export async function fetchBarSnapshot(market: string, code: string, category: Category | 'MIN_120', count: number, adjust: AdjustMode = 'QFQ', signal?: AbortSignal, trackingOwner?: string): Promise<BarSnapshot> {
  const params = new URLSearchParams({
    market,
    code,
    category,
    count: String(count),
    start: '0',
    adjust,
    bar_time: 'native',
  })
  const resp = await fetch(`${BASE}/bars?${params}`, { signal, headers: {...queryIntentHeaders(), ...(trackingOwner?{'X-Tracking-Owner':trackingOwner}:{})} })
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as { data: Record<string, unknown>[]; metadata: BarSnapshot['metadata'] }
  assertMarketData(body.metadata, adjust)
  return { bars: body.data.map(normalizeBar).sort((a, b) => a.datetime.localeCompare(b.datetime)), metadata: body.metadata }
}

/** 执行完整缠论管道：K 线合并 → 分型 → 笔 → 中枢 → 线段 → 买卖点 → 背驰。 */
export function analyzeIndustry(req: { stock_market: string; stock_code: string; board_code: string; category: Category; count: number; structure_settings?: import('./structure-settings').StructureSettings }, signal?: AbortSignal): Promise<{ bars: Bar[]; result: ChanlunResult }> {
  return request('/chanlun/industry?ownership_history=summary', { method: 'POST', body: JSON.stringify(req), signal })
}

export function fetchStockIndustries(market: string, code: string, signal?: AbortSignal): Promise<DataRowsResponse> {
  return request(queryPath('/chanlun/industries', { market, code }), { signal })
}

export function replayChanlun(req: ResearchRequest, signal?: AbortSignal): Promise<ChanlunResult> {
  return request('/chanlun/replay?ownership_history=summary', { method: 'POST', body: JSON.stringify(req), signal })
}

export function replayChanlunComparison(req: {
  stock: ResearchRequest
  industry: { code: string; bars: Bar[] }
}, signal?: AbortSignal): Promise<{
  stock: ChanlunResult
  industry: { bars: Bar[]; result: ChanlunResult } | null
  alignment: { as_of: string; industry_as_of: string | null; status: 'aligned' | 'earlier' | 'unavailable' }
}> {
  return request('/chanlun/replay/compare?ownership_history=summary', { method: 'POST', body: JSON.stringify(req), signal })
}

export async function analyzeChanlun(req: {
  market: string
  code: string
  category: Category
  count: number
  start?: number
  adjust?: AdjustMode
}): Promise<ChanlunResult> {
  const resp = await fetch(`${BASE}/chanlun/analyze?ownership_history=summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...queryIntentHeaders() },
    body: JSON.stringify({ ...req, start: req.start ?? 0 }),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as ChanlunResult
}

/** 同步回测（内联 OHLCV，快速）。 */
export async function runBacktest(req: BacktestRequest, owner?:string): Promise<BacktestResult> {
  const resp = await fetch(`${BASE}/backtest/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...queryIntentHeaders(), ...(owner?{'X-Task-Owner':owner}:{}) },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as BacktestResult
}

/** 提交后台回测任务，返回 task_id。 */
export async function submitBacktestTask(req: BacktestRequest): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...queryIntentHeaders() },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交组合回测后台任务，返回 task_id。 */
export async function submitPortfolioTask(
  req: PortfolioBacktestRequest,
  context?: { owner: string; signal: AbortSignal },
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/portfolio/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...queryIntentHeaders(), ...(context?{'X-Task-Owner':context.owner}:{}) },
    signal: context?.signal,
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交多策略组合回测后台任务（资金分仓），返回 task_id。 */
export async function submitMultiStrategyTask(
  req: MultiStrategyBacktestRequest,
  context?: { owner: string; signal: AbortSignal },
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/multi-strategy/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...queryIntentHeaders(), ...(context?{'X-Task-Owner':context.owner}:{}) },
    signal: context?.signal,
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交参数网格寻优后台任务，返回 task_id。 */
export async function submitOptimizeTask(
  req: OptimizeBacktestRequest,
  context?: { owner: string; signal: AbortSignal },
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/optimize/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...queryIntentHeaders(), ...(context?{'X-Task-Owner':context.owner}:{}) },
    signal: context?.signal,
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交「一键寻优所有策略」后台任务，返回 task_id。 */
export async function submitOptimizeAllTask(
  req: OptimizeAllBacktestRequest,
  context?: { owner: string; signal: AbortSignal },
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/optimize-all/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...queryIntentHeaders(), ...(context?{'X-Task-Owner':context.owner}:{}) },
    signal: context?.signal,
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 查询后台任务状态（轮询用）。 */
export async function fetchTask(taskId: string, context?: { owner: string; signal: AbortSignal }): Promise<TaskState> {
  const resp = await fetch(`${BASE}/backtest/tasks/${encodeURIComponent(taskId)}`, {headers:context?{'X-Task-Owner':context.owner}:{},signal:context?.signal})
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskState
}

export function cancelTask(taskId: string,context?:{owner:string;signal:AbortSignal}): Promise<TaskState> {
  return request(`/backtest/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST',signal:context?.signal,headers:context?{'X-Task-Owner':context.owner}:{} })
}

export async function deleteTask(taskId: string): Promise<void> {
  const resp = await fetch(`${BASE}/backtest/tasks/${encodeURIComponent(taskId)}`, {
    method: 'DELETE', credentials: 'same-origin',
  })
  if (!resp.ok) await throwError(resp)
}

/** 列出最近任务摘要（供对比页选择）。 */
export async function fetchTaskList(limit = 20): Promise<TaskListResponse> {
  const resp = await fetch(`${BASE}/backtest/tasks?limit=${limit}`)
  if (!resp.ok) await throwError(resp)
  return validateTaskList(await resp.json())
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
    if (isTaskTerminal(state.status)) return state
    if (Date.now() - start > timeoutMs) {
      throw new Error(`等待超过 ${timeoutMs / 1000} 秒；任务可能仍在计算，请到个人账户查看或取消`)
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

// ── 策略库（已保存策略）──────────────────────────────────────────────────────

/** 提交「信号雷达」一键扫描后台任务，返回 task_id。 */
export async function submitSignalScanTask(
  req: SignalScanRequest = {},
  context?: { owner: string; signal: AbortSignal },
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/signal-scan/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...queryIntentHeaders(), ...(context?{'X-Task-Owner':context.owner}:{}) },
    signal: context?.signal,
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
    if (isTaskTerminal(state.status)) return state
    if (Date.now() - start > timeoutMs) {
      throw new Error(`等待超过 ${timeoutMs / 1000} 秒；扫描可能仍在计算，请到个人账户查看或取消`)
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

/** 断言任务结果为信号扫描结果（类型收窄用）。 */
export function asSignalScanResult(state: TaskState): SignalScanResult {
  if (state.status !== 'done') throw new Error(taskFailureMessage(state))
  const result = state.result as SignalScanResult | null
  if (!result || !Array.isArray(result.rows)) {
    throw new Error('信号扫描结果格式异常（缺少 rows）')
  }
  return result
}

/** 列出全部已保存策略（按创建时间倒序）。 */
export async function fetchSavedStrategies(owner?:string): Promise<SavedStrategyListResponse> {
  const resp = await fetch(`${BASE}/strategies`, {headers:owner?{'X-Strategy-Owner':owner}:{}})
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategyListResponse
}

/** 查看单条已保存策略。 */
export async function fetchSavedStrategy(id: string, owner?: string): Promise<SavedStrategy> {
  const resp = await fetch(`${BASE}/strategies/${encodeURIComponent(id)}`, {headers:owner?{'X-Strategy-Owner':owner}:{}})
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategy
}

/** 保存一条策略（含当时的标的上下文与成绩快照）。 */
export async function saveStrategy(req: SavedStrategyCreate, owner?: string): Promise<SavedStrategy> {
  const resp = await fetch(`${BASE}/strategies`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(owner?{'X-Strategy-Owner':owner}:{}) },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategy
}

/** 更新一条已有策略，保留其 id 与创建时间。 */
export async function updateSavedStrategy(id: string, req: SavedStrategyCreate, owner?: string): Promise<SavedStrategy> {
  const resp = await fetch(`${BASE}/strategies/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...(owner?{'X-Strategy-Owner':owner}:{}) },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategy
}

/** 删除一条已保存策略。 */
export async function deleteSavedStrategy(id: string,owner?:string): Promise<void> {
  const resp = await fetch(`${BASE}/strategies/${encodeURIComponent(id)}`, { method: 'DELETE',headers:owner?{'X-Strategy-Owner':owner}:{}})
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
