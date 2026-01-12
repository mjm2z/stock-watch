/**
 * Server-side in-memory cache with TTL support
 * Used for caching API responses to reduce external API calls
 */

interface CacheEntry<T> {
  data: T
  expiresAt: number
}

class MemoryCache {
  private cache: Map<string, CacheEntry<unknown>> = new Map()

  /**
   * Get a cached value if it exists and hasn't expired
   */
  get<T>(key: string): T | null {
    const entry = this.cache.get(key) as CacheEntry<T> | undefined

    if (!entry) {
      return null
    }

    if (Date.now() > entry.expiresAt) {
      this.cache.delete(key)
      return null
    }

    return entry.data
  }

  /**
   * Set a value in the cache with a TTL in milliseconds
   */
  set<T>(key: string, data: T, ttlMs: number): void {
    this.cache.set(key, {
      data,
      expiresAt: Date.now() + ttlMs,
    })
  }

  /**
   * Check if a key exists and is not expired
   */
  has(key: string): boolean {
    return this.get(key) !== null
  }

  /**
   * Delete a specific key from cache
   */
  delete(key: string): void {
    this.cache.delete(key)
  }

  /**
   * Clear all expired entries (call periodically to prevent memory leaks)
   */
  cleanup(): void {
    const now = Date.now()
    Array.from(this.cache.entries()).forEach(([key, entry]) => {
      if (now > entry.expiresAt) {
        this.cache.delete(key)
      }
    })
  }

  /**
   * Clear all cache entries
   */
  clear(): void {
    this.cache.clear()
  }

  /**
   * Get cache statistics
   */
  stats(): { size: number; keys: string[] } {
    return {
      size: this.cache.size,
      keys: Array.from(this.cache.keys()),
    }
  }
}

// Singleton instance for server-side caching
export const serverCache = new MemoryCache()

// Cache duration constants (in milliseconds)
export const CACHE_TTL = {
  SEARCH: 5 * 60 * 1000,         // 5 minutes
  QUOTE: 2 * 60 * 1000,          // 2 minutes
  FUNDAMENTALS: 60 * 60 * 1000,  // 1 hour
  HISTORICAL_INTRADAY: 15 * 60 * 1000, // 15 minutes
  HISTORICAL_DAILY: 24 * 60 * 60 * 1000, // 24 hours
  ANALYSIS: 6 * 60 * 60 * 1000,  // 6 hours
  MARKET_CONTEXT: 15 * 60 * 1000, // 15 minutes
} as const

/**
 * Rate limiter for API calls
 * Tracks daily usage and prevents exceeding limits
 */
interface RateLimitState {
  dailyCalls: number
  date: string // YYYY-MM-DD format
}

class RateLimiter {
  private state: RateLimitState = {
    dailyCalls: 0,
    date: this.getCurrentDate(),
  }

  private maxDailyCalls: number

  constructor(maxDailyCalls: number = 250) {
    this.maxDailyCalls = maxDailyCalls
  }

  private getCurrentDate(): string {
    return new Date().toISOString().split('T')[0]
  }

  /**
   * Check if a new call can be made
   */
  canMakeCall(): boolean {
    this.resetIfNewDay()
    return this.state.dailyCalls < this.maxDailyCalls
  }

  /**
   * Record a new API call
   */
  recordCall(): void {
    this.resetIfNewDay()
    this.state.dailyCalls++
  }

  /**
   * Get current usage stats
   */
  getUsage(): { used: number; limit: number; remaining: number; percentUsed: number } {
    this.resetIfNewDay()
    const remaining = Math.max(0, this.maxDailyCalls - this.state.dailyCalls)
    return {
      used: this.state.dailyCalls,
      limit: this.maxDailyCalls,
      remaining,
      percentUsed: (this.state.dailyCalls / this.maxDailyCalls) * 100,
    }
  }

  /**
   * Check if we're approaching the rate limit (80% threshold)
   */
  isApproachingLimit(): boolean {
    return this.getUsage().percentUsed >= 80
  }

  /**
   * Reset counter if it's a new day
   */
  private resetIfNewDay(): void {
    const today = this.getCurrentDate()
    if (this.state.date !== today) {
      this.state = {
        dailyCalls: 0,
        date: today,
      }
    }
  }
}

// Singleton rate limiter for FMP API (250 calls/day on free tier)
export const fmpRateLimiter = new RateLimiter(250)
