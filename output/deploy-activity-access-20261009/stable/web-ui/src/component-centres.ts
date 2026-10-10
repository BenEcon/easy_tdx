import type { ExpansionPart } from './types'

/** These are candidate components, not completed same-level movement types. */
export function componentCentres(part: ExpansionPart) {
  const chain = part.centre_chain
  if (!Array.isArray(chain) || !chain.length || !Array.isArray(part.source_segment_indices)
    || part.component_kind !== (chain.length > 1 ? 'trend_candidate' : 'consolidation_candidate')
    || part.natural_type_complete !== false) return null
  for (const [i, c] of chain.entries()) {
    const prior = chain[i - 1]
    if (![c.low, c.high, c.zd, c.zg].every(Number.isFinite) || c.low > c.zd || c.zd >= c.zg || c.zg > c.high
      || !Number.isInteger(c.formed_index) || c.formed_index < 0 || c.formed_index > part.known_index
      || !Array.isArray(c.seed_segment_indices) || c.seed_segment_indices.length !== 3
      || !c.seed_segment_indices.every((id, j) => Number.isInteger(id) && part.source_segment_indices.includes(id)
        && (!j || id === c.seed_segment_indices[j - 1]! + 1))) return null
    if (prior && (c.seed_segment_indices[0]! <= prior.seed_segment_indices.at(-1)!
      || c.formed_index < prior.formed_index
      || !(part.direction === 'up' ? c.low > prior.high : c.high < prior.low))) return null
  }
  return chain
}

export function componentSummary(part: ExpansionPart): string {
  if (part.component_kind === undefined && part.centre_chain === undefined) return '单中枢候选'
  const chain = componentCentres(part)
  if (!chain) return '子走势结构待核验'
  return chain.length > 1 ? `趋势候选 · ${chain.length} 个同向分离中枢` : '单中枢候选'
}
