export interface StructureSettings { bi_type: 'new' | 'old' | 'simple'; zs_min_lines: number }
export const defaultStructureSettings: StructureSettings = { bi_type: 'new', zs_min_lines: 3 }
export const strokeRuleOptions = [
  { value: 'new', label: '新笔 · 至少 1 根独立 K 线' },
  { value: 'old', label: '老笔 · 至少 3 根独立 K 线' },
  { value: 'simple', label: '简单笔 · 不限制独立 K 线间距' },
]
export function readStructureSettings(value: unknown): StructureSettings {
  if (value === undefined) return { ...defaultStructureSettings }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('结构计算设置无效')
  const v = value as Record<string, unknown>
  if (!['new','old','simple'].includes(String(v.bi_type)) || !Number.isInteger(v.zs_min_lines)
    || Number(v.zs_min_lines) < 3 || Number(v.zs_min_lines) > 6
    || Object.keys(v).some(k => !['bi_type','zs_min_lines'].includes(k))) throw Error('结构计算设置无效，未替换为默认规则')
  return { bi_type: v.bi_type as StructureSettings['bi_type'], zs_min_lines: Number(v.zs_min_lines) }
}
export function structureSettingsLabel(value?: StructureSettings): string {
  const s = readStructureSettings(value)
  return `${{new:'新笔',old:'老笔',simple:'简单笔'}[s.bi_type]} · 基础中枢 ≥ ${s.zs_min_lines} 段`
}
