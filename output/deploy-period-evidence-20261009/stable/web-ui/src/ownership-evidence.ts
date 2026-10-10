import type { LayeredMovementOwnership, NestedOwnership, OwnershipLifecycleEvent, OwnershipVersion } from './types'
import { engineeringSource } from './engineering-trend-evidence.ts'

export function currentOwners(data?: LayeredMovementOwnership): OwnershipVersion[] {
  return data?.versions.filter(v => data.current_owner_ids.includes(v.id)) ?? []
}

export function ownershipHistory(data?: LayeredMovementOwnership) {
  return data?.history_format === 'summary_v1' && data.history_summaries
    ? data.history_summaries : data?.versions ?? []
}

export function internalSource(id: string): string {
  const parts = id.split('/')
  if (parts.length < 2) return engineeringSource(id)
  const root = /^owner:(\d+):(\d+):at:(\d+)$/.exec(parts.shift()!)
  const movement = /^(movement:(?:trend|consolidation):L([1-9]\d*):(\d+):(\d+))$/.exec(parts.pop()!)
  if (!root || !movement) return '未知来源'
  let low = Number(root[1]), high = Number(root[2]), level = 0
  for (const part of parts) {
    const nested = /^nested:M([1-9]\d*):(\d+):(\d+):at:(\d+)$/.exec(part)
    if (!nested || Number(nested[1]) <= level || Number(nested[2]) < low || Number(nested[3]) > high
      || Number(nested[2]) > Number(nested[3])) return '未知来源'
    level = Number(nested[1]); low = Number(nested[2]); high = Number(nested[3])
  }
  if (low > Number(movement[3]) || high < Number(movement[4])
    || Number(movement[3]) > Number(movement[4]) || Number(movement[2]) <= level) return '未知来源'
  return `内部 ${engineeringSource(movement[1])}`
}

export function ownerLabel(owner: OwnershipVersion, id?: string): string {
  if (!id || id === owner.id) return '基础归属区'
  const nested = owner.nested_owners?.find(d => d.id === id)
  if (!nested) return '归属待核验'
  const sources = nested.source_segment_indices
  return `M${nested.input_level} 输入层 · 线段 ${sources[0]! + 1}–${sources.at(-1)! + 1}`
}

export function internalStatus(owner: OwnershipVersion, id: string): string {
  return owner.frontier_ids.includes(id) ? '当前内部输入' : '已被父级包含'
}

export function lifecycleLabel(kind: string): string {
  return ({ formed: '归属形成', expanded: '范围扩展', merged: '归属合并' } as Record<string, string>)[kind] ?? '待核验事件'
}

function consecutiveSources(sources: number[]): boolean {
  return Array.isArray(sources) && sources.length > 0 && sources.every((source, index) =>
    Number.isSafeInteger(source) && source >= 0 && (!index || source === sources[index - 1]! + 1))
}

export function ownershipLifecycle(domain: NestedOwnership, total: number,
  owner?: OwnershipVersion): OwnershipLifecycleEvent[] | undefined {
  const events = domain.lifecycle_events
  if (!events?.length || !Number.isInteger(total) || total < 1 || !owner
    || !consecutiveSources(domain.source_segment_indices)
    || !Number.isInteger(domain.input_level) || domain.input_level < 1
    || !Number.isInteger(domain.known_index) || domain.known_index < 0 || domain.known_index >= total
    || !domain.source_unit_ids.length || new Set(domain.source_unit_ids).size !== domain.source_unit_ids.length
    || !Array.isArray(domain.member_admissions)) return undefined
  const parent = domain.parent_owner_id === owner.id ? owner
    : owner.nested_owners?.find(candidate => candidate.id === domain.parent_owner_id)
  if (!parent || !consecutiveSources(parent.source_segment_indices)
    || ('input_level' in parent && parent.input_level >= domain.input_level)
    || domain.source_segment_indices[0]! < parent.source_segment_indices[0]!
    || domain.source_segment_indices.at(-1)! > parent.source_segment_indices.at(-1)!) return undefined
  const records = owner.levels.flatMap(level => level.types.map(record => ({ record, level: level.level })))
  const byId = new Map(records.map(({ record, level }) => [record.id, { record, level }]))
  if (byId.size !== records.length) return undefined
  const units = domain.source_unit_ids.map(id => byId.get(id))
  if (units.some(unit => !unit || unit.level !== domain.input_level || unit.record.level !== domain.input_level
    || !consecutiveSources(unit.record.source_segment_indices)
    || !Number.isInteger(unit.record.known_index) || unit.record.known_index < 0
    || unit.record.current_owner_id !== domain.id)) return undefined
  const sources = units.flatMap(unit => unit!.record.source_segment_indices)
  if (sources.length !== domain.source_segment_indices.length
    || sources.some((source, index) => source !== domain.source_segment_indices[index])) return undefined
  const admissions = new Map(domain.member_admissions.map(member => [member.unit_id, member.admitted_index]))
  if (admissions.size !== domain.member_admissions.length || admissions.size !== units.length
    || domain.source_unit_ids.some(id => !admissions.has(id))) return undefined
  const active = new Map<string, OwnershipLifecycleEvent>(), seen = new Set<string>(), admitted = new Set<string>()
  const members = new Map<string, string[]>()
  let previousTime = -1
  for (const event of events) {
    const { first_source_segment_index: first, last_source_segment_index: last } = event
    if (!Number.isInteger(event.known_index) || event.known_index < previousTime || event.known_index >= total
      || event.known_index < 0 || seen.has(event.id) || !event.id
      || !Number.isInteger(first) || !Number.isInteger(last) || first > last
      || first < domain.source_segment_indices[0]! || last > domain.source_segment_indices.at(-1)!
      || !Number.isInteger(event.source_unit_count) || event.source_unit_count < 1
      || !Array.isArray(event.previous_owner_ids) || !Array.isArray(event.added_unit_ids)) return undefined
    const prior = event.previous_owner_ids.map(id => active.get(id))
    if (new Set(event.previous_owner_ids).size !== prior.length || prior.some(p => !p)
      || event.kind !== (prior.length > 1 ? 'merged' : prior.length ? 'expanded' : 'formed')
      || event.added_unit_ids.some(id => admitted.has(id) || !domain.source_unit_ids.includes(id))
      || new Set(event.added_unit_ids).size !== event.added_unit_ids.length
      || event.source_unit_count !== prior.reduce((sum, p) => sum + p!.source_unit_count, 0) + event.added_unit_ids.length
      || prior.some(p => p!.first_source_segment_index < first || p!.last_source_segment_index > last)) return undefined
    // Current placement may be later than the original admission after a merge.
    // Compare original availability to the event, not current_owner_known_index.
    if (event.added_unit_ids.some(id => byId.get(id)!.record.known_index > event.known_index
      || admissions.get(id) !== Math.max(domain.known_index, event.known_index))) return undefined
    const memberIds = [...event.previous_owner_ids.flatMap(id => members.get(id)!), ...event.added_unit_ids]
    const actualSources = memberIds.flatMap(id => byId.get(id)!.record.source_segment_indices).sort((a, b) => a - b)
    if (!consecutiveSources(actualSources) || actualSources[0] !== first || actualSources.at(-1) !== last
      || (event.kind === 'expanded' && !event.added_unit_ids.length)) return undefined
    for (const id of event.previous_owner_ids) { active.delete(id); members.delete(id) }
    if ([...active.values()].some(other => Math.max(first, other.first_source_segment_index)
      <= Math.min(last, other.last_source_segment_index))) return undefined
    active.set(event.id, event); seen.add(event.id)
    members.set(event.id, memberIds)
    event.added_unit_ids.forEach(id => admitted.add(id))
    previousTime = event.known_index
  }
  const final = active.get(domain.id)
  return active.size === 1 && final?.source_unit_count === domain.source_unit_ids.length
    && admitted.size === domain.source_unit_ids.length
    && final.first_source_segment_index === domain.source_segment_indices[0]
    && final.last_source_segment_index === domain.source_segment_indices.at(-1) ? events : undefined
}
