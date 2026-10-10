import { archiveTime as parseArchiveTime } from './archive-data-validation.ts'

export type ArchiveKind = 'chart' | 'study' | 'backtest' | 'portfolio' | 'factor' | 'tracking'
export interface ArchiveRecord {
  id: string; kind: ArchiveKind; name: string; note: string; revision: number
  state: 'active' | 'deleted' | 'purged'; digest: string; size_bytes: number
  created_at: string; updated_at: string; deleted_at: string | null
  provenance: 'client_archive_not_server_verified'; payload?: unknown
}
export interface ArchiveDirectory {
  revision: number; items: ArchiveRecord[]
  quota: { used_bytes: number; max_bytes: number; used_items: number; max_items: number; object_bytes: number; used_receipts: number; max_receipts: number }
}
export interface ArchiveDraft { kind: ArchiveKind; payload: unknown; name: string; note: string }
export class ArchiveRequestError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status=status }
}
const archiveObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const archiveInteger = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0
const archiveTime = (v: unknown): v is string => parseArchiveTime(v, true) !== null
function invalidArchive(): never { throw new ArchiveRequestError(502,'云存档响应格式不正确，未采用该结果；已读取的存档保留') }

export function validateArchiveRecord(value: unknown, requirePayload = false): ArchiveRecord {
  if (!archiveObject(value) || typeof value.id !== 'string' || !/^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(value.id)
    || (value.kind !== 'chart' && value.kind !== 'study' && value.kind !== 'backtest' && value.kind !== 'portfolio' && value.kind !== 'factor' && value.kind !== 'tracking')
    || (value.state !== 'active' && value.state !== 'deleted' && value.state !== 'purged')
    || typeof value.name !== 'string' || typeof value.note !== 'string'
    || !archiveInteger(value.revision) || value.revision < 1 || !archiveInteger(value.size_bytes)
    || typeof value.digest !== 'string' || !/^[\da-f]{64}$/.test(value.digest)
    || !archiveTime(value.created_at) || !archiveTime(value.updated_at)
    || (value.deleted_at !== null && !archiveTime(value.deleted_at))
    || value.provenance !== 'client_archive_not_server_verified'
    || (requirePayload && (value.state === 'purged' || !archiveObject(value.payload)))) return invalidArchive()
  return value as unknown as ArchiveRecord
}

export function validateArchiveDirectory(value: unknown): ArchiveDirectory {
  if (!archiveObject(value) || !archiveInteger(value.revision) || !Array.isArray(value.items) || !archiveObject(value.quota)) return invalidArchive()
  for (const key of ['used_bytes','max_bytes','used_items','max_items','object_bytes','used_receipts','max_receipts']) {
    if (!archiveInteger(value.quota[key])) return invalidArchive()
  }
  const ids = new Set<string>()
  for (const item of value.items) {
    const record = validateArchiveRecord(item)
    if (record.state === 'purged' || ids.has(record.id)) return invalidArchive()
    ids.add(record.id)
  }
  if (value.quota.used_items !== value.items.length) return invalidArchive()
  return value as unknown as ArchiveDirectory
}
export function archiveClient(owner: () => string | undefined, transport: typeof fetch = fetch) {
  return async function request<T>(path = '', init: RequestInit = {}): Promise<T> {
    const identity = owner()
    if (!identity) throw new ArchiveRequestError(401, '请先登录')
    const headers = new Headers(init.headers)
    headers.set('X-Research-Owner',identity)
    if (init.body) headers.set('Content-Type','application/json')
    const response = await transport(`/api/v1/research/archives${path}`, { ...init, headers, credentials:'same-origin', cache:'no-store' })
    const value: unknown = await response.json().catch(() => null)
    if (owner() !== identity) throw new ArchiveRequestError(409, '登录账户已变化，已丢弃旧账户响应')
    if (!response.ok) {
      const detail = value && typeof value === 'object' && 'detail' in value ? value.detail : null
      throw new ArchiveRequestError(response.status, typeof detail === 'string' ? detail : response.status === 404 ? '服务器尚未启用云存档，请保留本地快照' : `云存档请求失败（${response.status}）`)
    }
    const checked = path === '' ? validateArchiveDirectory(value) : validateArchiveRecord(value, !init.method || init.method.toUpperCase() === 'GET')
    return checked as T
  }
}
export function freezeArchiveDraft(draft: ArchiveDraft): ArchiveDraft {
  if (!draft.name.trim() || draft.name.length > 120 || draft.note.length > 4000) throw new Error('名称需为 1–120 字，备注最多 4000 字')
  const encoded = JSON.stringify(draft,(_key,value)=>{
    if(typeof value==='number'&&!Number.isFinite(value))throw new Error('存档含非有限数值，未将其静默转换为空值')
    return value
  })
  if (new TextEncoder().encode(encoded).length > 25 * 1024 * 1024) throw new Error('云存档超过 25MiB，请缩小历史范围；本地导出仍可保留')
  return JSON.parse(encoded) as ArchiveDraft
}
