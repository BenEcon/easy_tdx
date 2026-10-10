import { prepareArchiveImport } from './archive-import.ts'
import type { ArchiveRecord } from './cloud-archives.ts'

export interface LocalMigrationPlan {
  sourceId: string; cloudId: string; name: string; description: string; warnings: string[]; bytes: number
}

/** Stable IDs are retry receipts, never access credentials. Keep v1 serialization frozen. */
export async function prepareLocalMigration(value: unknown, owner: string): Promise<{ plan: LocalMigrationPlan; body: string }> {
  if (!owner || !value || typeof value !== 'object' || !('owner' in value) || value.owner !== owner
    || !('id' in value) || typeof value.id !== 'string' || !value.id) throw Error('本地快照不属于当前账户，未上传')
  const prepared = prepareArchiveImport(value, '本地研究快照.json')
  const body = JSON.stringify(prepared.draft)
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(['tdx-local-migration-v1', owner, value.id, body])))
  const hex = Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('')
  // A namespaced content-based UUID (v8); backend still checks its full content digest.
  const cloudId = `${hex.slice(0,8)}-${hex.slice(8,12)}-8${hex.slice(13,16)}-${((parseInt(hex[16]!,16)&3)|8).toString(16)}${hex.slice(17,20)}-${hex.slice(20,32)}`
  return { body, plan: { sourceId: value.id, cloudId, name: prepared.draft.name, description: prepared.description,
    warnings: prepared.warnings.filter(warning => !warning.includes('独立副本')).map(warning => warning.replace('文件提供', '本地快照提供')),
    bytes: new TextEncoder().encode(body).length } }
}

/** Re-read one source at a time; never keep an entire batch's large payloads in memory. */
export async function uploadLocalMigration(plan: LocalMigrationPlan, owner: string, io: {
  read: (id: string, owner: string) => Promise<unknown>
  send: (id: string, body: string) => Promise<ArchiveRecord>
  valid: () => boolean
}): Promise<ArchiveRecord> {
  const check = () => { if (!io.valid()) throw Error('迁移已停止或账户已变化；已发出的请求可能已保存，重试会使用同一 ID') }
  check()
  const value = await io.read(plan.sourceId, owner)
  check()
  const prepared = await prepareLocalMigration(value, owner)
  check()
  if (prepared.plan.cloudId !== plan.cloudId) throw Error('本地原档在检查后发生变化，未上传；请重新检查并确认')
  const record = await io.send(plan.cloudId, prepared.body)
  check()
  if (record.id !== plan.cloudId || !['active','deleted'].includes(record.state)) throw Error('上传响应与原档不匹配，请刷新云目录核查后重试')
  return record
}
