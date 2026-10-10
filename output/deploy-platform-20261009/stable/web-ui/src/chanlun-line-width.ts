export type StructureLine = 'bi' | 'xd'
export type ChanlunLineWidths = Record<StructureLine, number>

export const DEFAULT_LINE_WIDTHS: Readonly<ChanlunLineWidths> = Object.freeze({ bi: 1.35, xd: 1.8 })
export const MIN_LINE_WIDTH = 0.5
export const MAX_LINE_WIDTH = 6
export const LINE_WIDTH_STEP = 0.05

export function structureLineWidth(kind: StructureLine, value?: number): number {
  return Number.isFinite(value)
    ? Math.round(Math.max(MIN_LINE_WIDTH, Math.min(MAX_LINE_WIDTH, value!)) * 100) / 100
    : DEFAULT_LINE_WIDTHS[kind]
}

export function emphasizedLineWidth(kind: StructureLine, value?: number): number {
  return Math.round((structureLineWidth(kind, value) + (kind === 'bi' ? 0.65 : 0.8)) * 100) / 100
}
