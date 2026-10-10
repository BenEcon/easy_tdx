export function canUseTracking(user: {role: string; active: boolean; tracking_allowed?: boolean} | null | undefined): boolean {
  return !!user?.active && (user.role === 'admin' || user.tracking_allowed === true)
}
