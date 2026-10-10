import { factorAliasVisible, factorSearchKey } from './factor-research.ts'

export type CatalogEntry = Record<string, unknown>
export const factorLibraries = [
  { value: 'easy_tdx_builtin', label: '基础因子' },
  { value: 'qlib_alpha158', label: 'Alpha158 · 完整窗口' },
  { value: 'gtja191', label: 'GTJA191 · 因子库' },
  { value: 'alpha101', label: 'Alpha101 · 本地验证' },
  { value: 'all', label: '全部因子库' },
]

/** Catalog data is public, but its default calculation belongs to the mount-time
 * context. A late catalog must not replace a manual run or submit after leaving. */
export async function initializeFactorCatalog(options: {
  load: () => Promise<CatalogEntry[]>
  active: () => boolean
  initialContext: () => boolean
  publish: (rows: CatalogEntry[]) => void
  fail: (error: unknown) => void
  run: () => Promise<void>
}) {
  let rows: CatalogEntry[]
  try { rows = await options.load() } catch (error) {
    if (options.active()) options.fail(error)
    return
  }
  if (!options.active()) return
  options.publish(rows)
  if (options.initialContext()) await options.run()
}

export function factorAvailabilityReason(row:CatalogEntry,adjust:string,category='DAY',evaluation=false):string {
  if(row[evaluation?'evaluation_available':'available']===false)return String(row[evaluation?'evaluation_unavailable_reason':'unavailable_reason']||'当前不可用')
  if(Array.isArray(row.supported_categories)&&!row.supported_categories.includes(category))return '不支持当前周期；不会自动转换。'
  if(Array.isArray(row.supported_adjustments)&&!row.supported_adjustments.includes(adjust))return String(row.adjustment_unavailable_reason||'不支持当前复权方式')
  return ''
}

export function browseFactors(rows: CatalogEntry[], library: string, query: string, selected: string[] = []) {
  const term = factorSearchKey(query)
  return rows.filter(row =>
    (library === 'all' || row.library === library) &&
    factorAliasVisible(row, query, selected) &&
    (!term || [row.name, row.display_name, row.description, row.family]
      .some(value => factorSearchKey(String(value ?? '')).includes(term))),
  )
}

// Alias visibility belongs to browseFactors, after the user query is known.
export function eligibleEvaluationFactors(rows:CatalogEntry[]):CatalogEntry[] {
  return rows.filter(row=>row.evaluation_available===true)
}
