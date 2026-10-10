/** Keep teleported menus inside the visible viewport, including the software keyboard. */
export function floatingMenuPosition(rect: { left: number; top: number; bottom: number; width: number }, viewport: { width: number; height: number; left?: number; top?: number }, desiredHeight: number) {
  const padding = 10, gap = 6
  const minLeft = (viewport.left ?? 0) + padding
  const minTop = (viewport.top ?? 0) + padding
  const right = (viewport.left ?? 0) + viewport.width - padding
  const bottom = (viewport.top ?? 0) + viewport.height - padding
  const width = Math.min(Math.max(rect.width, 176), Math.max(1, viewport.width - 2 * padding))
  const below = bottom - rect.bottom - gap
  const above = rect.top - minTop - gap
  const opensAbove = below < Math.min(desiredHeight, 180) && above > below
  const maxHeight = Math.max(1, Math.min(desiredHeight, Math.max(above, below), viewport.height - 2 * padding))
  const top = Math.max(minTop, Math.min(opensAbove ? rect.top - maxHeight - gap : rect.bottom + gap, bottom - maxHeight))
  return { left: Math.max(minLeft, Math.min(rect.left, right - width)), top, width, maxHeight, opensAbove }
}
