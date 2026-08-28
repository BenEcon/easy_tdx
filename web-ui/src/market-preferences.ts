import { computed, ref, watch } from 'vue'

import { updatePreferences, useAuth } from './auth'

export type AdjustMode = 'NONE' | 'QFQ' | 'HFQ'

export const ADJUST_OPTIONS: Array<{ value: AdjustMode; label: string; description: string }> = [
  { value: 'QFQ', label: '前复权', description: '保持当前价格连续，适合技术分析' },
  { value: 'HFQ', label: '后复权', description: '保留累计分红送转收益' },
  { value: 'NONE', label: '不复权', description: '查看原始交易价格' },
]

const adjustState = ref<AdjustMode>('QFQ')
let initialized = false

function normalizeAdjust(value: unknown): AdjustMode {
  return value === 'NONE' || value === 'HFQ' || value === 'QFQ' ? value : 'QFQ'
}

export function useMarketPreferences() {
  const { currentUser } = useAuth()
  if (!initialized) {
    watch(
      currentUser,
      (user) => {
        adjustState.value = normalizeAdjust(user?.preferences?.adjust_mode)
      },
      { immediate: true },
    )
    initialized = true
  }

  const adjustMode = computed<AdjustMode>({
    get: () => adjustState.value,
    set: (value) => {
      const normalized = normalizeAdjust(value)
      adjustState.value = normalized
      if (currentUser.value) {
        void updatePreferences({ adjust_mode: normalized }).catch(() => undefined)
      }
    },
  })

  return { adjustMode, adjustOptions: ADJUST_OPTIONS }
}
