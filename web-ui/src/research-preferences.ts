import { effectScope, ref, watch } from 'vue'
import { useAuth, updatePreferences } from './auth'
import { createMovingAverageSettings } from './moving-averages'
import { DEFAULT_LINE_WIDTHS, structureLineWidth } from './chanlun-line-width'
import { TECHNICAL_INDICATORS, getIndicatorDefinition } from './technical-indicators'

export const defaultResearchPreferences = () => ({
  ma: createMovingAverageSettings(), widths: { ...DEFAULT_LINE_WIDTHS }, transparency: 80,
  indicators: [{ type: 'volume', params: {} as Record<string, number> }, { type: 'macd', params: { SHORT: 12, LONG: 26, M: 9 } }],
  secondary: 'MIN_30', layout: 'stacked', linkCursor: true, linkZoom: false, mobileSheet: true, objectHover: false,
})
export type ResearchPreferences = ReturnType<typeof defaultResearchPreferences>
export function normalizeResearchPreferences(raw: unknown): ResearchPreferences {
  const defaults = defaultResearchPreferences()
  if (!raw || typeof raw !== 'object') return defaults
  const value = raw as Partial<ResearchPreferences>
  return {
    ...defaults,
    ma: Array.isArray(value.ma) && value.ma.length ? value.ma.slice(0, 12).map((item, i) => ({
      period: Math.max(1, Math.min(800, Math.round(Number(item?.period) || defaults.ma[i % 7]!.period))), enabled: item?.enabled === true,
    })) : defaults.ma,
    widths: { bi: structureLineWidth('bi', value.widths?.bi), xd: structureLineWidth('xd', value.widths?.xd) },
    transparency: Number.isFinite(value.transparency) ? Math.max(0, Math.min(100, value.transparency!)) : 80,
    indicators: Array.isArray(value.indicators) ? value.indicators.slice(0, 8).filter(item => TECHNICAL_INDICATORS.some(def => def.value === item?.type)).map(item => ({
      type: item.type, params: item.type === 'macd' ? { ...getIndicatorDefinition('macd').defaultParams }
        : Object.fromEntries(Object.entries(item.params ?? {}).filter(([key, val]) => /^[A-Z][A-Z0-9_]*$/.test(key) && Number.isFinite(val) && val > 0 && val <= 10000)),
    })) : defaults.indicators,
    secondary: ['MONTH', 'WEEK', 'DAY', 'MIN_60', 'MIN_30', 'MIN_15', 'MIN_5', 'MIN_1'].includes(value.secondary ?? '') ? value.secondary! : defaults.secondary,
    layout: value.layout === 'side' ? 'side' : 'stacked', linkCursor: value.linkCursor !== false,
    linkZoom: value.linkZoom === true, mobileSheet: value.mobileSheet !== false, objectHover: value.objectHover === true,
  }
}
const settings = ref(defaultResearchPreferences())
const saveStatus = ref('')
let initialized = false
let timer: ReturnType<typeof setTimeout> | undefined
let revision = 0
export function useResearchPreferences() {
  const { currentUser } = useAuth()
  if (!initialized) {
    initialized = true
    // This store outlives the first chart route that consumes it.
    effectScope(true).run(() => watch(() => currentUser.value?.id, () => {
      clearTimeout(timer); revision++
      settings.value = normalizeResearchPreferences(currentUser.value?.preferences?.chanlun_workspace)
      saveStatus.value = ''
    }, { immediate: true }))
  }
  function patch(patch: Partial<ResearchPreferences>) {
    const next = normalizeResearchPreferences({ ...settings.value, ...patch })
    if (JSON.stringify(next) === JSON.stringify(settings.value)) return
    settings.value = next
    clearTimeout(timer)
    const owner = currentUser.value?.id, version = ++revision
    if (!owner) { saveStatus.value = '未登录：设置仅本次有效'; return }
    saveStatus.value = '偏好待保存…'
    timer = setTimeout(async () => {
      if (owner !== currentUser.value?.id) return
      try { await updatePreferences({ chanlun_workspace: next }); if (version === revision) saveStatus.value = '偏好已保存到账户' }
      catch { if (version === revision) saveStatus.value = '偏好保存失败，请点击重试' }
    }, 450)
  }
  async function retry() {
    clearTimeout(timer)
    const owner = currentUser.value?.id, version = ++revision
    if (!owner) { saveStatus.value = '未登录：设置仅本次有效'; return }
    try { await updatePreferences({ chanlun_workspace: settings.value }); if (version === revision && owner === currentUser.value?.id) saveStatus.value = '偏好已保存到账户' }
    catch { if (version === revision && owner === currentUser.value?.id) saveStatus.value = '偏好保存失败，请点击重试' }
  }
  function reset() { patch(defaultResearchPreferences()) }
  return { settings, saveStatus, patch, reset, retry }
}
