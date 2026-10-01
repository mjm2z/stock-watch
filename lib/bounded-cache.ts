/** Byte-bounded LRU for disposable JSON responses, never execution evidence. */
export class BoundedCache<T> {
  private entries = new Map<string, { value: T; bytes: number; expires: number }>()
  private bytes = 0
  constructor(
    private maxBytes: number,
    private maxEntries = 128
  ) {}
  get(key: string): T | undefined {
    this.prune()
    const item = this.entries.get(key)
    if (!item) return
    this.entries.delete(key)
    this.entries.set(key, item)
    return item.value
  }
  set(key: string, value: T, ttl = 60_000) {
    this.prune()
    this.delete(key)
    const bytes = new TextEncoder().encode(JSON.stringify(value)).byteLength
    if (bytes > this.maxBytes) return
    this.entries.set(key, { value, bytes, expires: Date.now() + ttl })
    this.bytes += bytes
    while (this.bytes > this.maxBytes || this.entries.size > this.maxEntries)
      this.delete(this.entries.keys().next().value!)
  }
  private delete(key: string) {
    this.bytes -= this.entries.get(key)?.bytes || 0
    this.entries.delete(key)
  }
  private prune() {
    for (const [key, item] of this.entries) if (item.expires <= Date.now()) this.delete(key)
  }
  clear() {
    this.entries.clear()
    this.bytes = 0
  }
  stats() {
    this.prune()
    return { bytes: this.bytes, entries: this.entries.size }
  }
}
