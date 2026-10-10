import type { ReleasedMovement, ReleasedRecursion } from './types'

const integer = (v: number) => Number.isSafeInteger(v) && v >= 0
const continuous = (xs: number[]) => Array.isArray(xs) && xs.length > 0
  && xs.every((x, i) => integer(x) && (!i || x === xs[i - 1]! + 1))
const same = (a: unknown[], b: unknown[]) => a.length === b.length && a.every((v, i) => v === b[i])
const contains = (a: number[], b: number[]) => a[0]! <= b[0]! && a.at(-1)! >= b.at(-1)!
const unique = (xs: unknown[]) => new Set(xs).size === xs.length
const overlaps = (a: number[], b: number[]) => a[0]! <= b.at(-1)! && b[0]! <= a.at(-1)!

function validate(data: ReleasedRecursion | undefined, total: number) {
  if (!data || data.rule !== 'whole_domain_parent_release_v1'
    || data.scope !== 'approved_whole_domain_release' || data.theory_equivalence_claim !== false
    || data.eligible_for_trading !== false || !integer(total)
    || !integer(data.accepted_segment_count) || !integer(data.rejected_suffix_count)) return undefined
  const known = (v: number) => integer(v) && v < total && v <= (data.as_of_index ?? -1)
  if (data.as_of_index !== null && !known(data.as_of_index)) return undefined
  if (data.as_of_index === null && (total || data.accepted_segment_count)) return undefined
  const rows = data.levels.flatMap(l => l.types)
  const records = new Map(rows.map(r => [r.id, r]))
  const domains = new Map(data.domains.map(d => [d.id, d]))
  if (records.size !== rows.length || domains.size !== data.domains.length
    || data.highest_completed_level !== data.levels.length) return undefined
  for (const d of data.domains) {
    if (!continuous(d.source_segment_indices) || !known(d.known_index)
      || !integer(d.input_level) || !integer(d.required_parent_level)
      || d.required_parent_level < d.input_level + 2
      || !known(d.context_known_index) || d.context_known_index > d.known_index
      || !d.claim_kinds.length || !unique(d.claim_kinds)
      || d.claim_kinds.some(k => k !== 'promotion' && k !== 'expansion')
      || !unique(d.source_unit_ids) || d.source_unit_ids.length !== d.member_admissions.length) return undefined
    const sources: number[] = []
    for (const [i, admission] of d.member_admissions.entries()) {
      if (!continuous(admission.source_segment_indices) || !known(admission.admitted_index)
        || admission.admitted_index > d.known_index) return undefined
      const id = d.source_unit_ids[i]!
      if (d.input_level === 0) {
        if (admission.source_segment_indices.length !== 1
          || id !== `segment:${admission.source_segment_indices[0]}`) return undefined
      } else {
        const child = records.get(id)
        if (!child || child.level !== d.input_level || child.known_index > admission.admitted_index
          || !same(child.source_segment_indices, admission.source_segment_indices)) return undefined
      }
      sources.push(...admission.source_segment_indices)
    }
    if (!same(sources, d.source_segment_indices)) return undefined
  }
  for (const [i, layer] of data.levels.entries()) {
    if (layer.level !== i + 1 || !layer.types.length) return undefined
    for (const r of layer.types) {
      if (r.level !== layer.level || !continuous(r.source_segment_indices)
        || !known(r.known_index) || !known(r.original_known_index)
        || r.original_known_index > r.known_index || !integer(r.start_index)
        || !integer(r.end_index) || r.start_index >= r.end_index || r.end_index > r.known_index
        || !Number.isFinite(r.start_value) || !Number.isFinite(r.end_value)
        || !['up', 'down'].includes(r.direction)
        || (r.direction === 'up' ? r.end_value <= r.start_value : r.end_value >= r.start_value)
        || !['trend', 'consolidation'].includes(r.kind ?? '')
        || r.rule !== data.rule || r.theory_equivalence_claim !== false
        || r.engineering_complete !== true || r.eligible_for_trading !== false
        || !unique(r.child_ids) || !r.child_ids.length
        || !unique(r.required_domain_ids) || r.required_domain_ids.some(id => !domains.has(id))) return undefined
      let sources: number[]
      if (r.level === 1) {
        if (!same(r.child_ids, r.source_segment_indices.map(s => `segment:${s}`))) return undefined
        sources = r.source_segment_indices
        if (r.opposite_id !== `segment:${sources.at(-1)! + 1}`) return undefined
      } else {
        const children = r.child_ids.map(id => records.get(id))
        const reverse = records.get(r.opposite_id)
        if (!reverse || reverse.level !== r.level - 1 || reverse.known_index > r.known_index
          || reverse.source_segment_indices[0] !== r.source_segment_indices.at(-1)! + 1
          || children.some(c => !c || c.level !== r.level - 1 || c.known_index > r.known_index)) return undefined
        const chain = [...children as ReleasedMovement[], reverse]
        if (chain[0]!.start_index !== r.start_index || chain[0]!.start_value !== r.start_value
          || chain[0]!.direction !== r.direction || reverse.start_index !== r.end_index
          || reverse.start_value !== r.end_value || reverse.direction === r.direction
          || chain.some((c, j) => j > 0 && (chain[j - 1]!.end_index !== c.start_index
            || chain[j - 1]!.end_value !== c.start_value || chain[j - 1]!.direction === c.direction))) return undefined
        sources = children.flatMap(c => c!.source_segment_indices)
      }
      if (!same(sources, r.source_segment_indices)) return undefined
      const p = r.current_placement
      if (!p || !known(p.known_index) || p.known_index < r.known_index
        || !unique(p.enclosing_domain_ids) || !unique(p.released_domain_ids)
        || [...p.enclosing_domain_ids, ...p.released_domain_ids, ...p.conflicts.map(c => c.domain_id)]
          .some(id => !domains.has(id))) return undefined
      if (p.released_domain_ids.some(id => {
        const d = domains.get(id)!
        return r.level < d.required_parent_level || !contains(r.source_segment_indices, d.source_segment_indices)
      })) return undefined
      if (r.eligible_for_external_recursion && (!r.on_frontier || !p.accepted
        || !p.eligible_for_external_recursion || p.conflicts.length || p.enclosing_domain_ids.length
        || r.required_domain_ids.length)) return undefined
    }
  }
  // Check ownership against actual ranges and propagate *all* current child /
  // witness obligations. This validates the supplied graph, not MACD or price
  // discovery; no frontend alternative to the backend completion algorithm.
  let active: ReleasedMovement[] = []
  for (const r of rows) {
    const p = r.current_placement
    const reverse = records.get(r.opposite_id)
    const witnessSources = reverse?.source_segment_indices ?? [r.source_segment_indices.at(-1)! + 1]
    const witnessLevel = reverse?.level ?? 0
    const enclosing: string[] = [], released: string[] = []
    const conflicts: { reason: string; domain_id: string }[] = []
    let minimumKnown = r.known_index
    for (const d of data.domains) {
      if (!overlaps(r.source_segment_indices, d.source_segment_indices)) continue
      if (contains(r.source_segment_indices, d.source_segment_indices) && r.level >= d.required_parent_level) {
        released.push(d.id)
        minimumKnown = Math.max(minimumKnown, d.known_index)
      } else if (contains(d.source_segment_indices, r.source_segment_indices)) {
        enclosing.push(d.id)
        minimumKnown = Math.max(minimumKnown, d.context_known_index, ...d.member_admissions
          .filter(a => overlaps(a.source_segment_indices, r.source_segment_indices)).map(a => a.admitted_index))
      } else conflicts.push({ reason: 'partial_domain_coverage', domain_id: d.id })
    }
    for (const d of data.domains) {
      if (!overlaps(witnessSources, d.source_segment_indices) || enclosing.includes(d.id)) continue
      if (contains(witnessSources, d.source_segment_indices) && witnessLevel >= d.required_parent_level) {
        minimumKnown = Math.max(minimumKnown, d.known_index)
      } else conflicts.push({ reason: 'foreign_internal_witness', domain_id: d.id })
    }
    const dependencies = r.level > 1 ? [...r.child_ids, r.opposite_id].map(id => records.get(id)!) : []
    const required = new Set([...enclosing, ...conflicts.map(c => c.domain_id),
      ...dependencies.flatMap(c => c.required_domain_ids)])
    const unresolved = data.domains.filter(d => required.has(d.id) && !(
      contains(r.source_segment_indices, d.source_segment_indices) && r.level >= d.required_parent_level)).map(d => d.id)
    minimumKnown = Math.max(minimumKnown, ...conflicts.map(c => domains.get(c.domain_id)!.known_index),
      ...dependencies.map(c => c.current_placement.known_index))
    const accepted = conflicts.length === 0
    const external = accepted && !enclosing.length && !unresolved.length
    if (!same(enclosing, p.enclosing_domain_ids) || !same(released, p.released_domain_ids)
      || conflicts.length !== p.conflicts.length || conflicts.some((c, i) =>
        c.reason !== p.conflicts[i]!.reason || c.domain_id !== p.conflicts[i]!.domain_id)
      || p.accepted !== accepted || p.reason !== (conflicts[0]?.reason ?? null)
      || p.eligible_for_external_recursion !== (accepted && !enclosing.length)
      || !same(unresolved, r.required_domain_ids) || p.known_index < minimumKnown) return undefined
    if (external || (accepted && unresolved.every(id => enclosing.includes(id)))) {
      if (active.some(old => overlaps(old.source_segment_indices, r.source_segment_indices)
        && !contains(r.source_segment_indices, old.source_segment_indices))) return undefined
      active = active.filter(old => !contains(r.source_segment_indices, old.source_segment_indices))
      active.push(r)
    }
    if (r.eligible_for_external_recursion !== (r.on_frontier && external)) return undefined
  }
  active.sort((a, b) => a.source_segment_indices[0]! - b.source_segment_indices[0]!)
  if (!same(active.map(r => r.id), data.frontier_ids)) return undefined
  for (const r of rows) {
    const representative = active.find(a => contains(a.source_segment_indices, r.source_segment_indices))?.id ?? null
    if (r.represented_by_id !== representative) return undefined
  }
  if (!same(rows.filter(r => r.represented_by_id === null).map(r => r.id), data.deferred_ids)) return undefined
  if (![data.frontier_ids, data.external_frontier_ids, data.internal_frontier_ids, data.deferred_ids].every(unique)
    || data.frontier_ids.some(id => !records.get(id)?.on_frontier)
    || rows.some(r => r.on_frontier !== data.frontier_ids.includes(r.id))
    || !same(data.external_frontier_ids, data.frontier_ids.filter(id => records.get(id)!.eligible_for_external_recursion))
    || !same(data.internal_frontier_ids, data.frontier_ids.filter(id => !records.get(id)!.eligible_for_external_recursion))
    || data.deferred_ids.some(id => !records.has(id) || records.get(id)!.represented_by_id !== null)) return undefined
  for (const d of data.domains) {
    const releaser = active.find(r => r.eligible_for_external_recursion
      && r.current_placement.released_domain_ids.includes(d.id))?.id ?? null
    if (d.released_by_id !== releaser) return undefined
    if (d.released_by_id) {
      const r = records.get(d.released_by_id)
      if (d.status !== 'released_by_parent' || !r?.eligible_for_external_recursion
        || !r.current_placement.released_domain_ids.includes(d.id)) return undefined
    } else if (d.status !== 'retained') return undefined
  }
  const cover = data.source_cover.flatMap(b => b.source_segment_indices)
  if (cover.length !== data.accepted_segment_count || (cover.length && !continuous(cover))) return undefined
  if ((rows.length || data.domains.length) && !cover.length) return undefined
  if ([...rows, ...data.domains].some(r => !contains(cover, r.source_segment_indices))
    || rows.some(r => r.level === 1 && r.source_segment_indices.at(-1)! + 1 > cover.at(-1)!)) return undefined
  const coveredRecords: string[] = []
  const unresolved: number[] = []
  for (const [i, block] of data.source_cover.entries()) {
    if (!continuous(block.source_segment_indices) || !integer(block.start_index)
      || block.start_index >= block.end_index || !known(block.end_index)
      || (i > 0 && data.source_cover[i - 1]!.end_index !== block.start_index)) return undefined
    if (block.movement_id === null) {
      if (block.level !== 0 || block.status !== 'unresolved') return undefined
      unresolved.push(...block.source_segment_indices)
    } else {
      const r = records.get(block.movement_id)
      if (!r?.on_frontier || r.level !== block.level || !same(r.source_segment_indices, block.source_segment_indices)
        || block.start_index !== r.start_index || block.end_index !== r.end_index
        || block.status !== (r.eligible_for_external_recursion ? 'external_completed' : 'internal_completed')) return undefined
      coveredRecords.push(r.id)
    }
  }
  if (!same(coveredRecords, data.frontier_ids) || !same(unresolved, data.unresolved_segment_indices)
    || data.highest_external_level !== Math.max(0, ...data.external_frontier_ids.map(id => records.get(id)!.level))) return undefined
  return { records, domains, frontier: data.frontier_ids.map(id => records.get(id)!),
    deferred: data.deferred_ids.map(id => records.get(id)!), cover: data.source_cover }
}

export function releaseEvidence(data: ReleasedRecursion | undefined, total: number) {
  try { return validate(data, total) } catch { return undefined }
}

export function releaseReason(reason: string | null) {
  return reason === 'partial_domain_coverage' ? '尚未完整覆盖归属区或层级不足'
    : reason === 'foreign_internal_witness' ? '反向确认仍受其他归属区约束'
      : reason ? '归属依据待核验' : '仍有区内归属或后代确认依赖'
}
