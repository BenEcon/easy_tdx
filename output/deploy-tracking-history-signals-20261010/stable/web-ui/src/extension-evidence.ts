import type { CentreAdmission } from './types'

export function admissionReason(reason: string): string {
  const labels: Record<string, string> = {
    seed_formation: '三段共同形成中枢',
    extension: '中枢延伸纳入',
    failed_departure_return: '离开后回到中枢，回试确认后纳入',
  }
  return labels[reason] ?? '接纳原因未提供'
}

export function admissionWitness(entry: CentreAdmission, source: number[]): string {
  const index = entry.admission_segment_index
  if (typeof index !== 'number' || !Number.isInteger(index) || index < 0) return '接纳依据线段未提供'
  return `接纳依据：线段 ${index + 1}${source.includes(index) ? '' : '（本分组外，仅作确认依据）'}`
}
