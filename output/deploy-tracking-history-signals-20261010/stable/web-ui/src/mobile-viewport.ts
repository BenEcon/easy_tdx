import { onBeforeUnmount, onMounted, ref } from 'vue'

export function useMobileViewport() {
  const query = window.matchMedia('(max-width: 760px), (max-width: 980px) and (max-height: 500px)')
  const mobile = ref(query.matches)
  const update = () => { mobile.value = query.matches }
  onMounted(() => query.addEventListener('change', update))
  onBeforeUnmount(() => query.removeEventListener('change', update))
  return mobile
}
