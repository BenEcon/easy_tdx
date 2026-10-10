import type { AdjustMode, Category } from './types'

export interface LoadedResearchInput {
  code: string; market: string; category: Category
  startDate: string; endDate: string; adjust: AdjustMode
}

export function researchInputFields(input: LoadedResearchInput | null) {
  if (!input) return {}
  return { symbol: `${input.market}:${input.code}`, category: input.category,
    start_date: input.startDate, end_date: input.endDate, adjust: input.adjust }
}

/** Cancellation plus an identity guard: even non-abortable/late responses lose ownership. */
export function latestResearchRequest() {
  let current: AbortController | null = null
  function invalidate() { current?.abort(); current = null }
  return {
    invalidate,
    begin() {
      invalidate()
      const controller = new AbortController()
      current = controller
      return { signal: controller.signal, current: () => current === controller && !controller.signal.aborted }
    },
  }
}
