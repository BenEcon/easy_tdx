import { ref, watch } from 'vue'
import { useMobileViewport } from './mobile-viewport'

/** Mobile settings stay editable; newly completed results take visual priority. */
export function useMobileSettings(hasResult: () => boolean) {
  const mobile = useMobileViewport()
  const settingsOpen = ref(!hasResult())
  watch(hasResult, (ready, previouslyReady) => {
    if (mobile.value && ready && !previouslyReady) settingsOpen.value = false
  })
  return { mobile, settingsOpen }
}
