export interface MarketDataMetadata {
  original_task?: {task_id:string;row_index:number;execution_version:string;current_execution_version:string;storage:string;compatible:boolean}
  source: string; requested_adjust: string; actual_adjust: string; observed_at: string
  category: string; bar_time?: 'start' | 'end'; completion_note: string
  volume_policy: string; historical_data_vintage: boolean
  calendar_version?: string; data_fingerprint?: string; last_closed_at?: string | null
  last_bar_at?: string | null; adjustment_verified?: boolean
  range_start?: string | null; range_end?: string | null; page_count?: number
  excluded_open_count?: number; consistency_note?: string
  input_count?: number
  source_note?: string; source_fingerprint?: string | null
  requested_start?: string | null; requested_end?: string | null
  collection_quality?: { warnings: string[] }
  pagination_stop?: 'requested_start_reached' | 'source_exhausted'
  quality?: { status: 'ok' | 'warning' | 'error'; errors: string[]; warnings: string[]
    missing_session_count: number; missing_sessions: string[]; calendar_unverified_years: number[]
    suspension_status: string }
}

export function assertMarketData(metadata: MarketDataMetadata | undefined, requested: string) {
  if (!metadata) throw new Error('行情缺少来源与复权信息，请刷新后重试')
  if (metadata.actual_adjust !== requested || metadata.requested_adjust !== requested) {
    throw new Error(`复权口径不一致：请求 ${requested}，实际 ${metadata.actual_adjust}；已停止分析`)
  }
  if (metadata.quality?.status === 'error') throw new Error(`行情质量检查失败：${metadata.quality.errors.join('；')}`)
}

export function adjustmentName(value: string) {
  return ({ QFQ:'前复权', HFQ:'后复权', NONE:'不复权', UNKNOWN:'复权未独立核验' } as Record<string,string>)[value] ?? value
}

export function dataSourceName(value: string) {
  return ({ CLIENT_INPUT:'浏览器上传', UNVERIFIED_INPUT:'调用方数据', MAC:'MAC 行情', TDX_STANDARD:'通达信行情' } as Record<string,string>)[value] ?? value
}
