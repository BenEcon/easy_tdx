/** Backend zero-based raw-bar index → prefix length; never infer from dates. */
export function confirmationPosition(index: number | null | undefined, total: number, before = false): number | null {
  if (index == null || !Number.isInteger(index) || !Number.isInteger(total) || index < 0 || index >= total) return null
  const length = index + (before ? 0 : 1)
  return length >= 1 ? length : null
}
