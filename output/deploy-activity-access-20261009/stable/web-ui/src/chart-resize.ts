import { onBeforeUnmount, onMounted, type Ref } from 'vue'

/** Follow the content box, including drawer/panel and fullscreen layout changes. */
export function useChartResize(container: Ref<HTMLElement | undefined | null>, resize: () => void) {
  let observer: ResizeObserver | undefined
  let pending = 0
  const schedule = () => {
    cancelAnimationFrame(pending)
    pending = requestAnimationFrame(resize)
  }
  onMounted(() => {
    observer = new ResizeObserver(schedule)
    if (container.value) observer.observe(container.value)
    window.addEventListener('resize', schedule)
  })
  onBeforeUnmount(() => {
    observer?.disconnect()
    cancelAnimationFrame(pending)
    window.removeEventListener('resize', schedule)
  })
}
