import type { BlockedOwnershipCandidate, OwnershipVersion } from './types'

const reasons: Record<string, string> = {
  crosses_current_ownership_boundary: '来源跨越当前归属边界',
  opposite_witness_owned_by_another_domain: '反向确认结构属于其他归属区',
}

export function blockedOwnershipEvidence(owner: OwnershipVersion, candidate: BlockedOwnershipCandidate,
  total: number) {
  const original = candidate.original_known_index, asOf = owner.known_index
  const ids = candidate.source_unit_ids
  if (!Number.isInteger(total) || total < 1 || !Number.isInteger(original) || original < 0
    || !Number.isInteger(asOf) || original > asOf || asOf >= total
    || !Object.hasOwn(reasons, candidate.reason) || !Array.isArray(ids) || !ids.length
    || ids.some(id => typeof id !== 'string') || new Set(ids).size !== ids.length) return undefined
  const records = owner.levels.flatMap(layer => layer.types.map(record => ({ record, level: layer.level })))
  const lookup = new Map(records.map(item => [item.record.id, item]))
  if (lookup.size !== records.length) return undefined
  const units = ids.map(id => {
    const base = /^segment:(0|[1-9]\d*)$/.exec(id)
    if (base) return { sources: [Number(base[1])], level: 0 }
    const item = lookup.get(id)
    if (!item || item.level !== item.record.level || !Number.isInteger(item.level) || item.level < 1
      || !Number.isInteger(item.record.known_index) || item.record.known_index < 0
      || item.record.known_index > original) return undefined
    return { sources: item.record.source_segment_indices, level: item.level }
  })
  if (units.some(unit => !unit || unit.level !== units[0]!.level
    || !Array.isArray(unit.sources) || !unit.sources.length)) return undefined
  const sources = units.flatMap(unit => unit!.sources)
  const ownerSources = new Set(owner.source_segment_indices)
  if (sources.some((source, i) => !Number.isSafeInteger(source) || source < 0
    || !ownerSources.has(source) || (i > 0 && source !== sources[i - 1]! + 1))) return undefined
  return { sources, inputLevel: units[0]!.level, reason: reasons[candidate.reason]!, original, asOf }
}

function continuous(values: number[]) {
  return Array.isArray(values) && values.length > 0 && values.every((v, i) =>
    Number.isSafeInteger(v) && v >= 0 && (!i || v === values[i - 1]! + 1))
}
function same(left: number[], right: number[]) {
  return left.length === right.length && left.every((v, i) => v === right[i])
}
function contains(outer: number[], inner: number[]) {
  return outer[0]! <= inner[0]! && outer.at(-1)! >= inner.at(-1)!
}
function overlaps(left: number[], right: number[]) {
  return left[0]! <= right.at(-1)! && right[0]! <= left.at(-1)!
}

export function blockedOwnershipConflict(owner: OwnershipVersion, candidate: BlockedOwnershipCandidate,
  total: number) {
  const base = blockedOwnershipEvidence(owner, candidate, total), detail = candidate.ownership_conflict
  if (!base || !detail || detail.input_level !== base.inputLevel
    || !continuous(detail.source_segment_indices) || !same(detail.source_segment_indices, base.sources)
    || !Array.isArray(detail.source_domains)) return undefined
  const witness = detail.opposite
  if (!witness || !continuous(witness.source_segment_indices) || !Number.isInteger(witness.known_index)
    || witness.known_index < 0 || witness.known_index > base.original
    || overlaps(witness.source_segment_indices, base.sources)) return undefined
  const domains = detail.source_domains
  if (domains.some((domain, i) => !continuous(domain) || !overlaps(domain, base.sources)
    || (i > 0 && domains[i - 1]!.at(-1)! >= domain[0]!))) return undefined
  const witnessDomain = witness.owner_source_segment_indices
  if (witnessDomain !== null && (!continuous(witnessDomain)
    || !contains(witnessDomain, witness.source_segment_indices))) return undefined
  if (base.inputLevel === 0) {
    if (witness.source_segment_indices.length !== 1
      || witness.unit_id !== `segment:${witness.source_segment_indices[0]}`
      || domains.length !== 1 || !same(domains[0]!, owner.source_segment_indices)) return undefined
  } else {
    const records = owner.levels.find(layer => layer.level === base.inputLevel)?.types ?? []
    const actual = records.find(record => record.id === witness.unit_id)
    if (!actual || actual.level !== base.inputLevel || actual.known_index !== witness.known_index
      || !same(actual.source_segment_indices, witness.source_segment_indices)) return undefined
    // Resolve against this version's actual nested ranges, not a parsed ID.
    const nested = (owner.nested_owners ?? []).filter(domain => domain.input_level === base.inputLevel)
    const resolve = (range: number[]) => nested.find(domain => same(domain.source_segment_indices, range))
    if (domains.some(domain => !resolve(domain)) || (witnessDomain && !resolve(witnessDomain))) return undefined
    const actualDomains = nested.filter(domain => overlaps(domain.source_segment_indices, base.sources))
    if (actualDomains.length !== domains.length
      || actualDomains.some(domain => !domains.some(range => same(range, domain.source_segment_indices)))) return undefined
    const actualWitnessDomain = nested.find(domain => domain.id === actual.current_owner_id)
    if (actualWitnessDomain ? !witnessDomain || !same(witnessDomain, actualWitnessDomain.source_segment_indices)
      : witnessDomain !== null) return undefined
  }
  if (candidate.reason === 'crosses_current_ownership_boundary') {
    if (!domains.length || (domains.length === 1 && contains(domains[0]!, base.sources))) return undefined
  } else if (!witnessDomain || (domains.length === 1 && same(domains[0]!, witnessDomain))
    || domains.length > 1 || (domains.length === 1 && !contains(domains[0]!, base.sources))) return undefined
  if (witnessDomain && domains.some(domain => overlaps(domain, witnessDomain) && !same(domain, witnessDomain))) return undefined
  return detail
}
