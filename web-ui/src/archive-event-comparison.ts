import { archiveObject, archiveTime } from './archive-data-validation.ts'
import { compareArchiveValues, type ArchiveDifference } from './archive-recompute.ts'

type RecordValue = Record<string, unknown>
export type EventCollection = 'bcs' | 'mmds' | 'wave_diagnostics'
export type EventChange = 'added' | 'removed' | 'changed' | 'same' | 'unresolved'
export interface EventReference { path: string; value: unknown }
export interface EventComparisonRow {
  key: string; collection: EventCollection; label: string; date: string
  change: EventChange; facets: ('state' | 'timing' | 'evidence')[]; reason: string
  before: EventReference[]; after: EventReference[]; differences: ArchiveDifference[]
}
export interface ArchiveEventComparison {
  contract: 'archive-events-v1'; applicable: boolean; warnings: string[]
  rows: EventComparisonRow[]; counts: Record<EventChange, number>
  coverage: { collection: EventCollection; before: number | null; after: number | null; comparable: boolean }[]
}
export const eventChangeLabels: Record<EventChange, string> = {
  added: '新增记录', removed: '本次未再出现', changed: '内容变化', same: '一致', unresolved: '无法可靠配对',
}
export const eventCollectionLabels: Record<EventCollection, string> = {
  bcs: '背离／背驰', mmds: '结构买卖点', wave_diagnostics: '候选与拦截核验',
}
export const eventFacetLabels = { state: '状态', timing: '确认／失效时点', evidence: '依据／其他字段' }
const families: Record<string, string> = {
  macd: '局部双线', macd_wave: '标准波段', macd_wave_nonstandard: '非标准波段',
  macd_wave_special: '特殊波段', bi: '笔背驰', pz: '盘整背驰', qs: '趋势背驰',
  standard: '标准波段', nonstandard: '非标准波段', special: '特殊波段', double: '局部双线',
}
const signals: Record<string, string> = { '1buy': '一买', '2buy': '二买', '3buy': '三买', '1sell': '一卖', '2sell': '二卖', '3sell': '三卖' }
const collections: EventCollection[] = ['bcs', 'mmds', 'wave_diagnostics']
// Preserve date-only vs intraday precision and zone notation. Never use rounded
// epoch milliseconds (which can collapse two distinct sub-millisecond instants).
function dateKey(value: unknown): string | null {
  if (typeof value !== 'string' || archiveTime(value) === null) return null
  return value.replace('T', ' ').replace(/(\d\d:\d\d)(?!:)(?=Z|[+-]\d\d:\d\d$|$)/, '$1:00')
    .replace(/\.(\d*?)0+(?=Z|[+-]\d\d:\d\d$|$)/, (_all, digits: string) => digits ? `.${digits}` : '')
}
interface Identity { key: string | null; label: string; date: string; reason: string }
function identify(collection: EventCollection, value: unknown): Identity {
  const bad = (reason: string): Identity => ({ key: null, label: eventCollectionLabels[collection], date: '', reason })
  if (!archiveObject(value)) return bad('记录不是对象')
  const family = String(collection === 'wave_diagnostics' ? value.family : value.type)
  const label = (collection === 'mmds' ? signals[family] : families[family]) ?? family
  const dates = archiveObject(value.dates) ? value.dates : {}
  const intervals = archiveObject(value.intervals) ? value.intervals : {}
  const date = collection === 'mmds' ? value.date : collection === 'bcs' ? value.curr_date : family === 'special' ? dates.b_start : dates.c_start
  const fields: unknown[] = [family, dateKey(date)]
  let valid = !!fields[1]
  if (collection === 'mmds') {
    valid &&= Object.hasOwn(signals, family) && typeof value.source === 'string' && !!value.source
    fields.push(value.source)
  } else {
    valid &&= (collection === 'bcs' ? ['macd','macd_wave','macd_wave_nonstandard','macd_wave_special','bi','pz','qs'] : ['standard','nonstandard','special','double']).includes(family)
      && (value.direction === 'up' || value.direction === 'down')
    fields.push(value.direction)
    if (collection === 'bcs') {
      fields.push(dateKey(value.prev_date))
      if (family.startsWith('macd_wave')) {
        // Effective A may change when the axis trimming rule changes. Retain that
        // as evidence, while the original wave anchors identify the comparison.
        fields.push(dateKey(intervals.original_a_start ?? intervals.a_start), dateKey(intervals.b_start))
        if (family !== 'macd_wave_special') fields.push(dateKey(intervals.c_start))
      }
    }
  }
  valid &&= fields.every(field => field !== null && field !== undefined)
  return { key: valid ? JSON.stringify(fields) : null, label: `${label}${value.direction === 'down' ? ' · 底' : value.direction === 'up' ? ' · 顶' : ''}`,
    date: typeof date === 'string' ? date : '', reason: valid ? '' : '类型、方向、来源或日期锚点不完整；不使用数组下标推测身份' }
}

/** These lists are evidence sets, not ordered price/segment sequences. Keep all
 * duplicates and unknown properties; only ignore their presentation ordering. */
const unorderedEvidence = new Set(['checks', 'comparisons', 'related_events', 'events', 'rejections', 'gates'])
function canonical(value: unknown, key = ''): unknown {
  if (Array.isArray(value)) {
    const entries = value.map(item => canonical(item))
    return unorderedEvidence.has(key) ? entries.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))) : entries
  }
  if (!archiveObject(value)) return value
  return Object.fromEntries(Object.keys(value).sort().map(name => [name, canonical(value[name], name)]))
}
function differenceFacets(differences: ArchiveDifference[]): EventComparisonRow['facets'] {
  const found = new Set<EventComparisonRow['facets'][number]>()
  for (const row of differences) {
    const field = /^\$\["([^"]+)"\]/.exec(row.path)?.[1] ?? ''
    found.add(['status','bc'].includes(field) ? 'state' : /^(detected|preliminary|confirmed|invalidated)_(date|index)$/.test(field) ? 'timing' : 'evidence')
  }
  return (['state', 'timing', 'evidence'] as const).filter(facet => found.has(facet))
}
function chart(value: unknown): RecordValue | null {
  if (!archiveObject(value)) return null
  return archiveObject(value.result) ? value.result : value
}

/** Compare event records from the same saved chart input. This is not a live
 * signal stream, a matching algorithm for different windows, or trading advice. */
export function compareArchiveEvents(beforeValue: unknown, afterValue: unknown): ArchiveEventComparison {
  const report: ArchiveEventComparison = { contract: 'archive-events-v1', applicable: false, warnings: [], rows: [], coverage: [],
    counts: { added: 0, removed: 0, changed: 0, same: 0, unresolved: 0 } }
  const before = chart(beforeValue), after = chart(afterValue)
  if (!before || !after || typeof before.code !== 'string' || !before.code || before.code !== after.code
    || typeof before.frequency !== 'string' || !before.frequency || before.frequency !== after.frequency) {
    report.warnings.push('缺少相同标的与周期身份；此结果仅提供原始字段对照，不配对事件。')
    return report
  }
  report.applicable = true
  report.warnings.push('仅配对背离／背驰、结构买卖点及波段核验记录。递归结构和多周期研究仍查看原始字段；派生 M1 不重复计为独立事件。',
    '新增／未再出现仅指两版保存结果的记录差别，不代表新交易机会或失效；确认日期变化也不等于当时已知。')
  for (const collection of collections) {
    const a = before[collection], b = after[collection]
    const available = Array.isArray(a) && Array.isArray(b)
    report.coverage.push({ collection, before: Array.isArray(a) ? a.length : null, after: Array.isArray(b) ? b.length : null, comparable: available })
    if (!available) report.warnings.push(`${eventCollectionLabels[collection]}有一侧未保存有效列表；缺失不当作空列表，不推断新增或消失。`)
    const groups = new Map<string, { identity: Identity; before: EventReference[]; after: EventReference[] }>()
    let unknown = false
    for (const [side, values] of [['before', a], ['after', b]] as const) {
      if (!Array.isArray(values)) continue
      values.forEach((value, index) => {
        const identity = identify(collection, value)
        unknown ||= !identity.key
        const key = identity.key ?? `unresolved:${side}:${index}`
        let group = groups.get(key)
        if (!group) { group = { identity, before: [], after: [] }; groups.set(key, group) }
        group[side].push({ path: `$["${collection}"][${index}]`, value })
      })
    }
    for (const [key, group] of groups) {
      const left = group.before.length, right = group.after.length
      let change: EventChange, reason = '', differences: ArchiveDifference[] = []
      if (!available || !group.identity.key || left > 1 || right > 1 || (unknown && (!left || !right))) {
        change = 'unresolved'
        reason = !available ? '一侧列表缺失或无效，不能证明对应记录不存在' : !group.identity.key ? group.identity.reason
          : left > 1 || right > 1 ? '同一日期依据存在多条记录，不按排列顺序强行配对' : '同集合有身份不完整的记录，无法排除它是对应项'
      } else if (!left) change = 'added'
      else if (!right) change = 'removed'
      else {
        differences = compareArchiveValues(canonical(group.before[0]!.value), canonical(group.after[0]!.value))
        change = differences.length ? 'changed' : 'same'
      }
      report.rows.push({ key: `${collection}:${key}`, collection, label: group.identity.label, date: group.identity.date, change,
        facets: differenceFacets(differences), reason, before: group.before, after: group.after, differences })
      report.counts[change]++
    }
  }
  report.rows.sort((a,b) => a.collection.localeCompare(b.collection) || b.date.localeCompare(a.date) || a.key.localeCompare(b.key))
  return report
}
