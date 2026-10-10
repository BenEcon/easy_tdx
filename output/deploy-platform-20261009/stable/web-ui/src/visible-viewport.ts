import { onBeforeUnmount, onMounted } from 'vue'

/** Mobile keyboards shrink the visual viewport, not necessarily CSS dvh. */
export function useVisibleViewport() {
  let pending = 0
  function update() {
    const viewport = window.visualViewport
    document.documentElement.style.setProperty('--visible-height', `${viewport?.height ?? window.innerHeight}px`)
    document.documentElement.style.setProperty('--visible-top', `${viewport?.offsetTop ?? 0}px`)
  }
  function schedule() {
    cancelAnimationFrame(pending)
    pending = requestAnimationFrame(update)
  }
  onMounted(() => {
    update()
    window.addEventListener('resize', schedule)
    window.visualViewport?.addEventListener('resize', schedule)
    window.visualViewport?.addEventListener('scroll', schedule)
  })
  onBeforeUnmount(() => {
    cancelAnimationFrame(pending)
    window.removeEventListener('resize', schedule)
    window.visualViewport?.removeEventListener('resize', schedule)
    window.visualViewport?.removeEventListener('scroll', schedule)
    document.documentElement.style.removeProperty('--visible-height')
    document.documentElement.style.removeProperty('--visible-top')
  })
}
