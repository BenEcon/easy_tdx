import type { ECharts } from 'echarts/core'

/** Disable automatic hover activation; movement updates only after a chart click. */
export const clickTooltipOptions = {
  triggerOn: 'none',
  hideDelay: 0,
  enterable: false,
} as const

export function installClickChartTooltip(chart: ECharts, container: HTMLElement) {
  const document = container.ownerDocument
  const renderer = chart.getZr()
  let active = false
  function hide() {
    active = false
    clear()
  }
  function clear() {
    chart.dispatchAction({ type: 'updateAxisPointer', currTrigger: 'leave' })
    chart.dispatchAction({ type: 'hideTip' })
  }
  function select(event: { offsetX: number; offsetY: number }) {
    hide()
    active = true
    follow(event)
  }
  function follow(event: { offsetX: number; offsetY: number }) {
    if (!active) return
    // Coordinates also support blank space between candles and marker tooltips.
    // ECharts resolves the date and retains each existing formatter/style.
    chart.dispatchAction({ type: 'showTip', x: event.offsetX, y: event.offsetY })
  }
  function dismissOutside(event: Event) {
    if (!event.composedPath().includes(container)) hide()
  }
  function dismissWithEscape(event: KeyboardEvent) {
    if (event.key === 'Escape') hide()
  }
  renderer.on('click', select)
  renderer.on('mousemove', follow)
  // Zoom changes coordinates, not the user's activation choice.
  chart.on('datazoom', clear)
  document.addEventListener('click', dismissOutside, true)
  document.addEventListener('keydown', dismissWithEscape)
  return {
    hide,
    dispose() {
      active = false
      renderer.off('click', select)
      renderer.off('mousemove', follow)
      chart.off('datazoom', clear)
      document.removeEventListener('click', dismissOutside, true)
      document.removeEventListener('keydown', dismissWithEscape)
    },
  }
}
