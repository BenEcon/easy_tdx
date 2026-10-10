/** Deliberate query intent, scoped ONLY to synchronous API dispatch.
 * Never hold a global flag until a Promise finishes: that would label concurrent
 * polling or name completion as user actions. After an await, wrap the next
 * deliberate API dispatch explicitly with queryAction(manual)(() => api(...)).
 * This is activity telemetry, not proof of a human and never authorization.
 */
let manualDispatch = false

export function queryAction(manual = false) {
  return function dispatch<T>(operation: () => T): T {
    const previous = manualDispatch
    manualDispatch = manual === true
    try { return operation() } finally { manualDispatch = previous }
  }
}

export function queryIntentHeaders(): Record<string, string> {
  return { 'X-Query-Origin': manualDispatch ? 'user' : 'system' }
}
