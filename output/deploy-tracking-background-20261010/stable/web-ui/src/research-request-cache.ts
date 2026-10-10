/** Bounded, in-memory immutable snapshot cache. A changed payload/rule/scope is a different key. */
export class ResearchRequestCache<T> {
  private entries = new Map<string, Promise<T>>()
  private limit: number
  constructor(limit = 6) { this.limit = limit }
  get(key: string, load: () => Promise<T>): Promise<T> {
    const found = this.entries.get(key)
    if (found) return found
    const promise = load().catch(error => { if (this.entries.get(key) === promise) this.entries.delete(key); throw error })
    this.entries.set(key, promise)
    while (this.entries.size > this.limit) this.entries.delete(this.entries.keys().next().value!)
    return promise
  }
  clear() { this.entries.clear() }
}
