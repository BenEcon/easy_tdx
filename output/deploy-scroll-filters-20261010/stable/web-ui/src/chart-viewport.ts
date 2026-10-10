export interface ZoomWindow { start: number; end: number }

export function readZoom(value: unknown): ZoomWindow | null {
  if (!value || typeof value !== 'object') return null
  const {start, end} = value as Partial<ZoomWindow>
  return typeof start === 'number' && typeof end === 'number'
    && Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end <= 100 && start <= end
    ? {start, end} : null
}

/** Scope is one immutable bar snapshot; focus identity denotes an explicit jump. */
export class ChartViewportMemory {
  private scope: unknown
  private focus: unknown
  private beforeFocus: ZoomWindow | null = null

  update(scope: unknown, focus: unknown, live: unknown): ZoomWindow | null {
    const zoom = readZoom(live)
    let next: ZoomWindow | null = null
    if (scope !== this.scope) {
      this.beforeFocus = null
    } else if (focus !== this.focus) {
      if (focus) {
        if (!this.focus) this.beforeFocus = zoom
        // New focus uses its explicit index range instead of the current zoom.
      } else {
        next = this.beforeFocus
        this.beforeFocus = null
      }
    } else {
      next = zoom
    }
    this.scope = scope
    this.focus = focus
    return next
  }
}
