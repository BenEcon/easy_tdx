// 后端 API 的 TypeScript 类型镜像。
// 与 src/easy_tdx/web/backtest_schemas.py 及 backtest router 的响应保持一致。
// 后端是唯一事实源；这里只做类型契约。

// ── 策略 schema（GET /api/v1/backtest/strategies） ───────────────────────────

export type ParamType = 'int' | 'float' | 'bool' | 'str'

export interface ParamSchema {
  name: string
  type: ParamType
  default: number | string | boolean
  label: string
  min_value?: number
  max_value?: number
  choices?: string[]
  description?: string
}

export interface StrategySchema {
  name: string
  label: string
  description: string
  params: ParamSchema[]
  preset_grid?: Record<string, Array<number | string>>
}

export interface StrategiesResponse {
  strategies: StrategySchema[]
  count: number
}

// ── OHLCV 行情（GET /api/v1/bars） ────────────────────────────────────────────

export interface Bar {
  period_end?: string
  is_closed?: boolean
  datetime: string
  open: number
  high: number
  low: number
  close: number
  vol: number
  amount: number
}

export interface DataFrameResponse {
  data: Record<string, unknown>[]
  count: number
}

// ── 缠论结构分析（POST /api/v1/chanlun/analyze）──────────────────────────────

export interface ChanlunBi {
  index: number
  direction: 'up' | 'down'
  start_date: string
  end_date: string
  start_value?: number
  end_value?: number
  high: number
  low: number
  done: boolean
  structurally_confirmed?: boolean
  confirmed_index?: number | null
  confirmed_date?: string | null
}

export interface ChanlunCenter {
  index: number
  zg: number
  zd: number
  gg: number
  dd: number
  line_count: number
  start_date: string | null
  end_date: string | null
  done: boolean
  state?: string
  formed_date?: string
  formed_index?: number
  exited_index?: number | null
  exited_date?: string | null
  seed_segments?: number[]
  member_segments?: number[]
  relation_at_formation?: string
  relation_current?: string
  relation_history?: {
    relation: string; known_index: number; known_date: string; segment_index: number
    previous_centre: number; previous_envelope: [number, number]
    current_envelope: [number, number]; envelope_overlap: [number, number] | null
    member_segments: number[]; both_exited: boolean; higher_level_confirmed: boolean
  }[]
  transitions?: { state: string; segment_index: number; known_date: string }[]
}

export interface ChanlunFeature {
  low: number
  high: number
  pen_indices: number[]
  high_pen: number
  low_pen: number
}

export interface ChanlunSegment {
  index: number
  direction: 'up' | 'down'
  start_date: string
  end_date: string
  start_value?: number
  end_value?: number
  high: number
  low: number
  confirmed_date?: string | null
  confirmed_index?: number | null
  evidence?: {
    case: string
    start_pen: number
    end_pen: number
    supporting_pen?: number
    features?: ChanlunFeature[]
    reverse_features?: ChanlunFeature[]
    special_inclusion?: boolean
  }
}

export interface ChanlunSignal {
  type: '1buy' | '2buy' | '3buy' | '1sell' | '2sell' | '3sell'
  date: string | null
  msg: string
  confirmed_date?: string | null
  confirmed_index?: number | null
  source?: string
  evidence?: Record<string, unknown>
}

export interface ChanlunDivergence {
  preliminary_index?: number | null
  preliminary_date?: string | null
  invalidated_index?: number | null
  invalidated_date?: string | null
  failure_reason?: string
  failure_audit?: WaveAudit
  signal_index?: number | null
  reference_index?: number | null
  type: 'bi' | 'pz' | 'qs' | 'macd' | 'macd_wave'
  bc: boolean
  curr_date: string | null
  prev_date: string | null
  msg: string
  status?: 'candidate' | 'confirmed' | 'superseded'
  direction?: 'up' | 'down'
  detected_date?: string | null
  confirmed_date?: string | null
  confirmed_index?: number | null
  evidence?: Record<string, number>
  intervals?: Record<string, string>
}

export interface BaseDecomposition {
  rule: string
  recursive_levels_ready: boolean
  input_segment_count: number
  accepted_segment_count: number
  rejected_suffix_count: number
  as_of_index: number | null
  blocks: {
    role: string; centre_index: number | null; ownership_frozen: boolean
    segment_indices: number[]; known_index: number; known_date?: string
    start_index: number; end_index: number; high: number; low: number
    recursive_type_complete: boolean
  }[]
}

export interface CentreAdmission {
  segment_index: number; segment_confirmed_index: number; admitted_index: number
  admission_segment_index?: number
  segment_confirmed_date?: string; admitted_date?: string; reason: string
}

export interface ExtensionProof {
  id: string; level: number; source_segment_indices: number[]
  start_index: number; end_index: number; known_index: number
  start_date: string; end_date: string; known_date: string
  zd: number; zg: number; low: number; high: number
  children: ExtensionProof[]; child_ranges: number[][]
  natural_type_complete: false
  member_admissions?: CentreAdmission[]
}

export interface ExtensionHierarchy {
  rule: string; scope: string; natural_type_recursion_ready: false
  accepted_segment_count: number; rejected_suffix_count: number
  highest_proven_level: number; proofs: ExtensionProof[]
}

export interface ExpansionPart {
  component_kind?: 'consolidation_candidate' | 'trend_candidate'
  centre_chain?: {
    seed_segment_indices: number[]; formed_index: number; formed_date?: string
    zd: number; zg: number; low: number; high: number
  }[]
  source_segment_indices: number[]; seed_segment_indices: number[]
  start_index: number; end_index: number; known_index: number
  start_date?: string; end_date?: string; known_date?: string
  start_value: number; end_value: number; direction: 'up' | 'down'
  low: number; high: number; zd: number; zg: number
  natural_type_complete: false
}

export interface ExpansionCandidate {
  id: string; centre_indices: number[]; envelope_overlap: number[]
  status: string; known_index: number | null; known_date?: string | null
  source_segment_indices: number[]; parts: ExpansionPart[]
  candidate_core: number[] | null; partition_selection?: string | null
  natural_type_complete: false; higher_level_confirmed: false
}

export interface ExpansionPartAudit {
  engineering_completion?: HistoricalEngineeringCompletion | null
  part_index: number; source_segment_indices: number[]
  start_extreme: number; end_extreme: number
  start_is_extreme: boolean; end_is_extreme: boolean
  opposite_segment_index: number | null; opposite_known_index: number | null
  opposite_known_date?: string | null; status: string; blocking_reasons: string[]
  natural_type_complete: false
  opposite_evidence?: {
    segment_index: number; direction: 'up' | 'down'
    start_index: number; end_index: number; known_index: number
    start_value: number; end_value: number; source_part_index: number | null
    start_date?: string; end_date?: string; known_date?: string
  } | null
}

export interface HistoricalEngineeringCompletion {
  rule: string; movement_rule: string; status: 'historical_engineering_match'
  movement_id: string; kind: 'trend' | 'consolidation'; level: 1; direction: 'up' | 'down'
  source_segment_indices: number[]; start_index: number; end_index: number
  start_value: number; end_value: number; known_index: number; known_date?: string
  as_of_index: number; opposite_id: string; macd_evidence: Record<string, number>
  natural_type_complete: false; eligible_for_recursive_input: false
}

export interface ExpansionAudit {
  candidate_id: string; as_of_index: number; as_of_date?: string
  parts: ExpansionPartAudit[]; eligible_for_recursive_input: false
}

export interface ExpansionRegrouping {
  rule: string; scope: string; accepted_segment_count: number; rejected_suffix_count: number
  candidates: ExpansionCandidate[]; completion_audits?: ExpansionAudit[]
}

export interface MixedSourceCover {
  rule: string; interpretation_id: string; as_of_index: number; as_of_date?: string
  source_segment_indices: number[]; status: 'covered' | 'blocked'
  natural_type_complete: false; eligible_for_recursive_input: false
  joint_regrouping_required: boolean
  blocks: {
    kind: 'extension_proof' | 'base_run'; proof_id: string | null; level: number
    source_segment_indices: number[]; known_index: number; known_date?: string
    low: number; high: number; natural_type_complete: false
    crosses_role_boundary: boolean
    role_spans: { role: string; source_segment_indices: number[] }[]
  }[]
  conflicts: {
    reason: string; proof_id: string; source_segment_indices: number[]
    known_index: number; known_date?: string
  }[]
}

export interface RegroupingRevision {
  completion_audit?: VersionCompletionAudit
  mixed_source_cover?: MixedSourceCover
  id: string; version: number; supersedes: string | null
  known_index: number; known_date?: string; reason: string; status: string
  source_segment_indices: number[]; parts: ExpansionPart[]
  candidate_core: number[] | null; higher_proof_ids: string[]
  natural_type_complete: false; eligible_for_recursive_input: false
  retained_prefix_segment_indices?: number[]; prefix_role?: string
  start_change?: {
    previous_start_segment_index: number; current_start_segment_index: number
    detached_segment_indices: number[]; reincorporated_segment_indices: number[]
  } | null
}

export interface RegroupingCase {
  completion_audit?: VersionCompletionAudit
  mixed_source_cover?: MixedSourceCover
  candidate_id: string; formation_known_index: number; formation_known_date?: string
  as_of_index: number; as_of_date?: string; current_revision_id: string
  revisions: RegroupingRevision[]; pending_segment_indices: number[]
  origin_start_segment_index?: number; start_anchor_segment_indices?: number[]
}

export interface VersionCompletionAudit {
  rule: string; interpretation_id: string; as_of_index: number; as_of_date?: string
  parts: ExpansionPartAudit[]; blocking_reasons: string[]
  natural_type_complete: false; eligible_for_recursive_input: false
}

export interface RegroupingVersions {
  rule: string; scope: string; history_policy: string; natural_type_recursion_ready: false
  accepted_segment_count: number; rejected_suffix_count: number; cases: RegroupingCase[]
}

export interface EngineeringTrend {
  kind?: 'trend' | 'consolidation'
  id: string; level: number; direction: 'up' | 'down'; engineering_complete: true
  start_index: number; end_index: number; known_index: number
  start_date?: string; end_date?: string; known_date?: string; divergence_known_date?: string
  start_value: number; end_value: number; source_segment_indices: number[]
  child_ids: string[]; opposite_id: string; macd_evidence: Record<string, number>
  centres: { source_unit_indices: number[]; zd: number; zg: number; low: number; high: number }[]
}

export interface EngineeringTrendHierarchy {
  scope: 'engineering_trends_only'; highest_completed_trend_level: number
  natural_type_recursion_ready: false; accepted_segment_count: number; rejected_suffix_count: number
  levels: { level: number; input_count: number; input_chain_count: number
    types: EngineeringTrend[]; unresolved_input_ids: string[] }[]
  remaining_input_ids: string[]
  structure_layers?: RecursiveStructureLayer[]
}

export interface EngineeringMovementHierarchy extends Omit<EngineeringTrendHierarchy,
  'scope' | 'highest_completed_trend_level'> {
  scope: 'engineering_mixed_movements'
  highest_completed_movement_level: number
}

export interface InternalMovement extends EngineeringTrend {
  owner_id: string; eligible_for_internal_recursion: true; eligible_for_external_recursion: false
  original_known_index?: number; original_known_date?: string
  ownership_known_index?: number; ownership_known_date?: string
  current_owner_id?: string
  current_owner_known_index?: number; current_owner_known_date?: string
  ownership_transfers?: { from_owner_id: string; to_owner_id: string; known_index: number; known_date?: string }[]
}

export interface ReleasedPlacement {
  accepted: boolean; reason: string | null; known_index: number; known_date?: string
  conflicts: { reason: string; domain_id: string }[]
  enclosing_domain_ids: string[]; released_domain_ids: string[]
  eligible_for_external_recursion: boolean
}

export interface ReleasedMovement extends EngineeringTrend {
  opposite_start_index?: number; opposite_end_index?: number
  rule: string; theory_equivalence_claim: false
  original_known_index: number; original_known_date?: string
  required_domain_ids: string[]; current_placement: ReleasedPlacement
  eligible_for_external_recursion: boolean; on_frontier: boolean
  represented_by_id: string | null; eligible_for_trading: false
}

export interface ReleasedDomain {
  id: string; input_level: number; required_parent_level: number
  known_index: number; known_date?: string; source_segment_indices: number[]
  claim_kinds: string[]; released_by_id: string | null
  context_known_index: number; source_unit_ids: string[]
  member_admissions: { source_segment_indices: number[]; admitted_index: number }[]
  status: 'retained' | 'released_by_parent'
}

export interface ReleasedRecursion {
  rule: string; scope: string; as_of_index: number | null; as_of_date?: string
  accepted_segment_count: number; rejected_suffix_count: number
  highest_completed_level: number; highest_external_level: number
  levels: { level: number; types: ReleasedMovement[] }[]
  domains: ReleasedDomain[]; frontier_ids: string[]
  external_frontier_ids: string[]; internal_frontier_ids: string[]; deferred_ids: string[]
  unresolved_segment_indices: number[]
  source_cover: { movement_id: string | null; level: number
    status: 'external_completed' | 'internal_completed' | 'unresolved'
    source_segment_indices: number[]; start_index: number; end_index: number }[]
  theory_equivalence_claim: false; eligible_for_trading: false
}

export interface NestedOwnership {
  id: string; parent_owner_id: string; input_level: number; known_index: number; known_date?: string
  source_segment_indices: number[]; source_unit_ids: string[]
  claim_kinds: ('promotion' | 'expansion')[]
  natural_type_complete: false; eligible_for_external_recursion: false
  member_admissions: { unit_id: string; admitted_index: number; admitted_date?: string }[]
  lifecycle_events?: OwnershipLifecycleEvent[]
}

export interface OwnershipLifecycleEvent {
  id: string; known_index: number; known_date?: string
  kind: 'formed' | 'expanded' | 'merged'; previous_owner_ids: string[]
  first_source_segment_index: number; last_source_segment_index: number
  source_unit_count: number; added_unit_ids: string[]
}

export interface OwnershipVersion {
  id: string; known_index: number; known_date?: string; source_segment_indices: number[]
  previous_owner_ids: string[]; highest_completed_internal_level: number
  natural_type_complete: false; eligible_for_external_recursion: false
  levels: { level: number; types: InternalMovement[] }[]
  frontier_ids: string[]; unresolved_segment_indices: number[]
  claims: { key: string; kind: 'promotion' | 'expansion'; sources: number[] }[]
  nested_owners?: NestedOwnership[]
  blocked_ownership_candidates?: BlockedOwnershipCandidate[]
}

export interface BlockedOwnershipCandidate {
  reason: string; source_unit_ids: string[]; original_known_index: number; original_known_date?: string
  ownership_conflict?: {
    input_level: number; source_segment_indices: number[]; source_domains: number[][]
    opposite: { unit_id: string; source_segment_indices: number[]; known_index: number
      known_date?: string; owner_source_segment_indices: number[] | null }
  }
}

export interface LayeredMovementOwnership {
  rule: string; natural_type_recursion_ready: false; versions: OwnershipVersion[]
  current_owner_ids: string[]; external_m1_ids: string[]; external_unresolved_segment_indices: number[]
  history_format?: 'summary_v1'
  history_summaries?: Pick<OwnershipVersion, 'id' | 'known_index' | 'known_date' | 'source_segment_indices' | 'highest_completed_internal_level'>[]
}

export interface RecursiveStructureLayer {
  input_level: number
  chains: {
    id: string; input_ids: string[]; as_of_index: number; as_of_date?: string
    centres: {
      id: string; state: string; zd: number; zg: number; low: number; high: number
      formed_index: number; formed_date?: string; exited_index: number | null; exited_date?: string | null
      source_unit_ids: string[]; source_segment_indices: number[]
      departure_id: string | null; return_id: string | null; relation_current: string
      transitions: { state: string; unit_id: string; known_index: number; known_date?: string }[]
      member_admissions: RecursiveAdmission[]
    }[]
    extension_proofs: RecursiveExtensionProof[]
  }[]
}

export interface RecursiveAdmission {
  unit_id: string; witness_id: string; unit_confirmed_index: number; unit_confirmed_date?: string
  admitted_index: number; admitted_date?: string; reason: string
}

export interface RecursiveExtensionProof {
  id: string; input_level: number; relative_depth: number; known_index: number; known_date?: string
  zd: number; zg: number; source_unit_ids: string[]; source_segment_indices: number[]
  member_admissions: RecursiveAdmission[]; children: RecursiveExtensionProof[]
}

export interface WaveCheck {
  gate: string; passed: boolean
  values: Record<string, number | string | boolean | null>
  dates?: Record<string, string>
}
export interface WaveAudit {
  dates: Record<string, string>
  checks: WaveCheck[]
  closed: boolean
}
export interface WaveComparison extends WaveAudit {
  mode: 'full_a' | 'equal_price' | 'full_a_equal_price' | 'dea_tolerance'
  research_only: true
  passed: boolean
}
export interface WaveDiagnostic extends WaveAudit {
  direction: 'up' | 'down'
  status: 'blocked' | 'candidate' | 'confirmed'
  closed: boolean
  c_start: number
  first_candidate_index: number | null
  comparisons?: WaveComparison[]
  rejections: Array<{ from_date: string; through_date: string; gates: string[] }>
}

export interface ChanlunResult {
  wave_diagnostics?: WaveDiagnostic[]
  macd?: { dif: number[]; dea: number[]; hist: number[] }
  pen_consolidations?: Array<{
    pen_indices: number[]; start_date: string; end_date: string
    lower: number; upper: number; confirmed: boolean
    source: string; eligible_for_trading: false
  }>
  released_movement_recursion?: ReleasedRecursion
  engineering_movement_hierarchy?: EngineeringMovementHierarchy
  layered_movement_ownership?: LayeredMovementOwnership
  recursive_movement_ownership?: LayeredMovementOwnership
  engineering_trend_hierarchy?: EngineeringTrendHierarchy
  regrouping_versions?: RegroupingVersions
  expansion_regrouping?: ExpansionRegrouping
  extension_hierarchy?: ExtensionHierarchy
  base_decomposition?: BaseDecomposition
  structure_metadata?: { signals_source: string; recursive_levels_ready: boolean; initial_unresolved_bars?: number }
  structural_centres?: (ChanlunCenter & { state: string; formed_date: string; exited_date: string | null })[]
  code: string
  frequency: string
  kline_count: number
  ckline_count: number
  fractal_count: number
  bi_count: number
  zs_count: number
  xd_count: number
  mmd_count: number
  bc_count: number
  bis: ChanlunBi[]
  zss: ChanlunCenter[]
  xds: ChanlunSegment[]
  unfinished_xd?: ChanlunSegment | null
  mmds: ChanlunSignal[]
  bcs: ChanlunDivergence[]
}

// ── 回测请求（POST /api/v1/backtest/run） ─────────────────────────────────────

export type ExecutionMode = 'next_open' | 'next_close'
export type Category = 'DAY' | 'WEEK' | 'MONTH' | 'MIN_1' | 'MIN_5' | 'MIN_15' | 'MIN_30' | 'MIN_60'

export interface BacktestRequest {
  strategy: string
  params?: Record<string, number | string | boolean>
  cash?: number
  commission?: number
  min_commission?: number
  stamp_tax?: number
  slippage?: number
  execution?: ExecutionMode
  ohlcv?: Bar[]
  symbol?: string
  category?: Category
  count?: number
}

// ── 回测结果 ──────────────────────────────────────────────────────────────────

export interface Performance {
  total_return: number
  annual_return: number
  max_drawdown: number
  max_dd_duration: number
  sharpe: number
  sortino: number
  calmar: number
  total_trades: number
  win_trades: number
  lose_trades: number
  rejected_trades: number
  win_rate: number
  profit_factor: number
  avg_win: number
  avg_loss: number
  max_win: number
  max_loss: number
  avg_holding_days: number
  volatility: number
}

export interface EquityPoint {
  datetime: string
  cash: number
  position_value: number
  total: number
  drawdown: number
  drawdown_pct: number
}

export interface Trade {
  datetime: string
  direction: 'BUY' | 'SELL'
  size: number
  price: number
  commission: number
  slippage: number
  pnl: number
  rejected: boolean
}

export interface BacktestResult {
  performance: Performance
  equity_curve: EquityPoint[]
  trades: Trade[]
  positions: Record<string, unknown>[]
  config: Record<string, unknown>
}

// ── 后台任务（POST /api/v1/backtest/run/async + GET /tasks/{id}） ─────────────

export interface TaskSubmitResponse {
  task_id: string
  status: 'pending' | 'running'
}

export type TaskStatus = 'pending' | 'running' | 'done' | 'failed'

export interface TaskState {
  task_id: string
  status: TaskStatus
  result:
    | BacktestResult
    | PortfolioResult
    | OptimizeResult
    | OptimizeAllResult
    | SignalScanResult
    | null
  error: string | null
  description: string
  elapsed: number
}

// ── 任务摘要（Phase 5 对比页） ────────────────────────────────────────────────

export interface TaskSummary {
  task_id: string
  status: TaskStatus
  description: string
  created_at: number
  elapsed: number
}

export interface TaskListResponse {
  tasks: TaskSummary[]
  count: number
}

// ── 组合回测（Phase 3） ───────────────────────────────────────────────────────

export type AdjustMode = 'NONE' | 'QFQ' | 'HFQ'

export interface PortfolioBacktestRequest {
  strategy: string
  params?: Record<string, number | string | boolean>
  cash?: number
  commission?: number
  slippage?: number
  execution?: ExecutionMode
  stocks: string[]
  category?: Category
  start_date?: string
  end_date?: string
  adjust?: AdjustMode
}

export interface PortfolioResult {
  total_performance: {
    total_return: number
    annual_return: number
    total_stocks: number
    total_cash: number
  }
  individual_results: Record<string, BacktestResult>
  equity_allocation: Record<string, number>
  combined_equity: EquityPoint[]
}

// ── 参数网格寻优（Phase 4） ──────────────────────────────────────────────────

export interface OptimizeBacktestRequest {
  strategy: string
  cash?: number
  commission?: number
  slippage?: number
  execution?: ExecutionMode
  param_grid: Record<string, Array<number | string>>
  ohlcv?: Bar[]
  symbol?: string
  category?: Category
  count?: number
  start_date?: string
  end_date?: string
  adjust?: AdjustMode
}

export interface GridPointResult {
  params: Record<string, number | string>
  total_return: number | null
  sharpe: number | null
  max_drawdown: number | null
  total_trades: number
  win_rate: number | null
  profit_factor: number | null
}

export interface OptimizeHeatmap {
  x_name: string
  y_name: string
  x: Array<number | string>
  y: Array<number | string>
  data: Array<[number, number, number | null]>
}

export interface OptimizeResult {
  strategy: string
  param_names: string[]
  results: GridPointResult[]
  best: GridPointResult | null
  heatmap: OptimizeHeatmap | null
}

// ── 一键寻优所有策略（Phase 6） ──────────────────────────────────────────────

export interface OptimizeAllBacktestRequest {
  cash?: number
  commission?: number
  slippage?: number
  execution?: ExecutionMode
  workers?: number
  ohlcv?: Bar[]
  symbol?: string
  category?: Category
  count?: number
  start_date?: string
  end_date?: string
  adjust?: AdjustMode
}

export interface OptimizeAllRankEntry {
  strategy: string
  strategy_label: string
  params: Record<string, number | string>
  total_return: number | null
  sharpe: number | null
  max_drawdown: number | null
  total_trades: number
  win_rate: number | null
  profit_factor: number | null
  grid_points: number
}

export interface OptimizeAllResult {
  ranking: OptimizeAllRankEntry[]
  best: OptimizeAllRankEntry | null
  per_strategy: Record<string, OptimizeAllRankEntry>
  total_grid_points: number
}

// ── 错误响应（后端 ApiErrorResponse） ─────────────────────────────────────────

export interface ApiError {
  error: string
  detail: string
}

// ── 策略库（已保存策略，GET/POST/DELETE /api/v1/strategies） ─────────────────

/** 新建一条已保存策略的请求体（前端在回测结果区点「保存」时提交）。 */
export interface SavedStrategyCreate {
  name: string
  kind: 'single' | 'portfolio' | 'multi'
  strategy: string
  strategy_label?: string
  params?: Record<string, number | string | boolean>
  /** 标的上下文：single 存 symbol/category/start_date/end_date；portfolio 存 stocks；multi 存 items + cash/execution */
  context?: Record<string, unknown>
  /** 资金与成本配置（cash/commission/...） */
  trade_config?: Record<string, unknown>
  /** 保存时的成绩快照（total_return/sharpe/...） */
  snapshot?: Record<string, unknown>
  tags?: string[]
  notes?: string
}

/** 一条已保存策略（响应模型，含 id 与时间戳）。 */
export interface SavedStrategy {
  id: string
  name: string
  kind: 'single' | 'portfolio' | 'multi'
  strategy: string
  strategy_label: string
  params: Record<string, number | string | boolean>
  context: Record<string, unknown>
  trade_config: Record<string, unknown>
  snapshot: Record<string, unknown>
  tags: string[]
  notes: string
  created_at: string
  updated_at: string
  app_version: string
}

export interface SavedStrategyListResponse {
  strategies: SavedStrategy[]
  count: number
}

// ── 账户与个人数据 ──────────────────────────────────────────────────────────

export interface AccountUser {
  id: string
  username: string
  role: 'admin' | 'user'
  active: boolean
  preferences: Record<string, unknown>
  created_at: string
  updated_at: string
  last_login_at: string
  saved_strategy_count?: number
}

export interface AuthStatus {
  setup_required: boolean
  authenticated: boolean
  user: AccountUser | null
}

export interface AccountListResponse {
  users: AccountUser[]
  count: number
  active_count: number
}

// ── 信号雷达（POST /api/v1/backtest/signal-scan/run/async） ──────────────────

/** 信号扫描请求：window_bars = 检查最近 N 根 K 线内的信号。 */
export interface SignalScanRequest {
  window_bars?: number
  adjust?: AdjustMode
}

/** 窗口内单根 K 线的信号。 */
export interface SignalScanRecentSignal {
  date: string
  direction: 'BUY' | 'SELL'
}

/** 扫描结果单行：一个"策略×标的"子任务的信号摘要。 */
export interface SignalScanRow {
  strategy_id: string
  strategy_name: string
  kind: 'single' | 'portfolio' | 'multi'
  strategy: string
  strategy_label: string
  params: Record<string, number | string | boolean>
  symbol: string
  category: string
  latest_signal: 'BUY' | 'SELL' | null
  signal_date: string | null
  recent_signals: SignalScanRecentSignal[]
  position: 'holding' | 'flat' | null
  last_close: number | null
  last_bar_date: string | null
  error: string | null
}

/** 信号扫描结果：全部子任务行 + 汇总计数。 */
export interface SignalScanResult {
  rows: SignalScanRow[]
  total: number
  buy_count: number
  sell_count: number
  error_count: number
  elapsed: number
}

// ── 多策略组合回测（资金分仓，POST /api/v1/backtest/multi-strategy/run/async） ──

/** 多策略组合的单个策略槽位（一个策略 + 参数 + 它要跑的原标的 + 日期）。 */
export interface MultiStrategyItem {
  strategy: string
  strategy_label?: string
  params?: Record<string, number | string | boolean>
  symbol: string
  category?: Category
  start_date?: string
  end_date?: string
}

/** 多策略组合回测请求（各策略各拿 1/N 资金，结果结构同 PortfolioResult）。 */
export interface MultiStrategyBacktestRequest {
  items: MultiStrategyItem[]
  cash?: number
  commission?: number
  min_commission?: number
  stamp_tax?: number
  slippage?: number
  execution?: ExecutionMode
  adjust?: AdjustMode
}

// ── 服务器设置（GET /api/v1/server/hosts 等） ────────────────────────────────

/** 单个通达信服务器的状态信息。 */
export interface ServerHostInfo {
  host: string
  /** 延迟（毫秒）。null = 未测速或不可达。 */
  latency_ms: number | null
  reachable: boolean
  is_current: boolean
}

/** GET /server/hosts 的响应。 */
export interface ServerHostListResponse {
  hosts: ServerHostInfo[]
  current_host: string
  total: number
}

/** POST /server/switch 的响应。 */
export interface ServerSwitchResult {
  ok: boolean
  host: string
  message: string
}
