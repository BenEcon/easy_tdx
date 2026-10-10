import type { BarSnapshot } from './api'
import type { Bar, Category, ChanlunResult } from './types'
import type { ResearchPreferences } from './research-preferences'
import type { ResearchTarget } from './chanlun-target'
import type { FrozenChartIndicators } from './frozen-chart-indicators'

export interface ResearchSnapshot {
  radarSource?: import('./radar-archive').RadarArchiveSource
  schema: 1; id: string; owner: string; name: string; note: string; savedAt: string
  target: ResearchTarget; title: string; cutoff: string; frontendVersion: string; ruleVersions: number[]
  preferences: ResearchPreferences; layers: { bis: boolean; zss: boolean; xds: boolean; mmds: boolean; bcs: boolean; consolidations?: boolean; nextPen?: boolean }; history: boolean
  charts: Array<{ category: Category; bars: Bar[]; result: ChanlunResult; metadata: BarSnapshot['metadata']; frozenIndicators?: FrozenChartIndicators }>
}
export type SnapshotSummary = Pick<ResearchSnapshot, 'id' | 'name' | 'savedAt'> & { charts: Array<{ category: Category }> }
export interface LocalSnapshotSource { id: string; name: string; savedAt: string }
export const snapshotSummary = (item: ResearchSnapshot): SnapshotSummary => ({ id: item.id, name: item.name, savedAt: item.savedAt, charts: item.charts.map(chart => ({ category: chart.category })) })
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('tdx-research-snapshots', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('snapshots', { keyPath: 'id' }).createIndex('owner', 'owner')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('本地快照存储不可用，请检查浏览器隐私设置'))
  })
}
export async function listResearchSnapshots(owner: string): Promise<SnapshotSummary[]> {
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const summaries: SnapshotSummary[] = []
      const req = db.transaction('snapshots').objectStore('snapshots').index('owner').openCursor(owner)
      req.onsuccess = () => {
        const cursor = req.result
        if (cursor) { summaries.push(snapshotSummary(cursor.value)); cursor.continue() }
        else resolve(summaries.sort((a, b) => b.savedAt.localeCompare(a.savedAt)))
      }
      req.onerror = () => reject(req.error)
    })
  } finally { db.close() }
}
export async function readResearchSnapshot(id: string, owner: string): Promise<ResearchSnapshot> {
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const req = db.transaction('snapshots').objectStore('snapshots').get(id)
      req.onsuccess = () => req.result?.owner === owner ? resolve(req.result) : reject(new Error('快照不存在或不属于当前账户'))
      req.onerror = () => reject(req.error)
    })
  } finally { db.close() }
}
/** Metadata only; one malformed legacy chart must not hide the other local archives. */
export async function listLocalSnapshotSources(owner: string): Promise<LocalSnapshotSource[]> {
  if (!owner) throw new Error('请先登录')
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const rows: LocalSnapshotSource[] = []
      const req = db.transaction('snapshots').objectStore('snapshots').index('owner').openCursor(owner)
      req.onsuccess = () => {
        const cursor = req.result
        if (!cursor) { resolve(rows); return }
        const value = cursor.value
        rows.push({ id: String(cursor.primaryKey), name: typeof value.name === 'string' ? value.name : '未命名本地快照', savedAt: typeof value.savedAt === 'string' ? value.savedAt : '' })
        cursor.continue()
      }
      req.onerror = () => reject(req.error)
    })
  } finally { db.close() }
}
export async function saveResearchSnapshot(snapshot: ResearchSnapshot) {
  const encoded = JSON.stringify(snapshot)
  if (new Blob([encoded]).size > 25 * 1024 * 1024) throw new Error('快照超过 25MB，请缩小历史窗口后保存')
  const db = await database()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('snapshots', 'readwrite')
      tx.objectStore('snapshots').put(JSON.parse(encoded))
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(new Error('快照保存失败：本地存储空间可能不足'))
      tx.onabort = () => reject(new Error('快照保存已中止'))
    })
  } finally { db.close() }
}
export async function deleteResearchSnapshot(id: string, owner: string) {
  const db = await database()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('snapshots', 'readwrite'), store = tx.objectStore('snapshots')
      const req = store.get(id)
      req.onsuccess = () => { if (req.result?.owner === owner) store.delete(id) }
      tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error)
    })
  } finally { db.close() }
}
