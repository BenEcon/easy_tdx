export type ResearchWorkspace = 'chart' | 'research' | 'audit'
export const researchWorkspaces = [
  {value:'chart' as const,label:'看图',description:'行情与周期对比'},
  {value:'research' as const,label:'研究',description:'多周期观察与快照'},
  {value:'audit' as const,label:'审核',description:'结构、信号与确认依据'},
]
export function workspaceFromKey(current: ResearchWorkspace, key: string): ResearchWorkspace | null {
  const index = researchWorkspaces.findIndex(item => item.value === current)
  if (key === 'Home') return 'chart'
  if (key === 'End') return 'audit'
  if (key !== 'ArrowLeft' && key !== 'ArrowRight') return null
  return researchWorkspaces[(index + (key === 'ArrowRight' ? 1 : 2)) % 3]!.value
}
export function visibleComparisonPeriod(mobile: boolean, mode: 'primary' | 'other' | 'compare', category: string, selected: string) {
  return !mobile || mode !== 'compare' || category === selected
}
export function canAutoStudy(active: boolean, automatic: boolean, busy: boolean, asOf: string, count: number, error: string) {
  return active && automatic && !busy && !!asOf && count > 0 && !error
}
