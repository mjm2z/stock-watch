import type { Stock, Quote, Fundamentals, PriceData } from '@/types'

/**
 * Market Data Provider Interface
 *
 * This abstraction allows swapping data providers (FMP, Alpha Vantage, etc.)
 * without changing the rest of the application.
 */
export interface MarketDataProvider {
  /**
   * Search for stocks by query string
   * Results are automatically filtered by quality criteria
   */
  searchStocks(query: string): Promise<Stock[]>

  /**
   * Get real-time quote for a single ticker
   */
  getQuote(ticker: string): Promise<Quote>

  /**
   * Get multiple quotes at once (for watchlist/portfolio)
   */
  getBatchQuotes(tickers: string[]): Promise<Quote[]>

  /**
   * Get company fundamentals
   */
  getFundamentals(ticker: string): Promise<Fundamentals>

  /**
   * Get historical price data for charting
   * @param range - '1D', '1W', '1M', '3M', '1Y', '5Y'
   */
  getHistoricalPrices(ticker: string, range: string): Promise<PriceData[]>
}

/**
 * Quality filters applied to stock search results
 */
export interface QualityFilters {
  minMarketCap: number      // Default: 500M
  minPrice: number          // Default: $5
  minVolume: number         // Default: 500K
  allowedExchanges: string[] // Default: NYSE, NASDAQ, AMEX
}

export const DEFAULT_QUALITY_FILTERS: QualityFilters = {
  minMarketCap: 500_000_000,
  minPrice: 5,
  minVolume: 500_000,
  allowedExchanges: ['NYSE', 'NASDAQ', 'AMEX'],
}

/**
 * Apply quality filters to a list of stocks
 */
export function applyQualityFilters(
  stocks: Stock[],
  filters: QualityFilters = DEFAULT_QUALITY_FILTERS
): Stock[] {
  return stocks.filter(stock =>
    stock.marketCap >= filters.minMarketCap &&
    stock.price >= filters.minPrice &&
    (stock.avgVolume ?? stock.volume ?? 0) >= filters.minVolume &&
    filters.allowedExchanges.includes(stock.exchange)
  )
}

/**
 * Cache configuration for different data types
 */
export const CACHE_DURATIONS = {
  search: 5 * 60 * 1000,        // 5 minutes
  quote: 2 * 60 * 1000,         // 2 minutes
  fundamentals: 60 * 60 * 1000,  // 1 hour
  historicalIntraday: 15 * 60 * 1000, // 15 minutes
  historicalDaily: 24 * 60 * 60 * 1000, // 24 hours
  analysis: 6 * 60 * 60 * 1000, // 6 hours
  marketContext: 15 * 60 * 1000, // 15 minutes
} as const

/**
 * Rate limit tracking for FMP API (250 calls/day on free tier)
 */
export interface RateLimitState {
  dailyCalls: number
  lastResetDate: string
  maxDailyCalls: number
}

export const DEFAULT_RATE_LIMIT: RateLimitState = {
  dailyCalls: 0,
  lastResetDate: new Date().toISOString().split('T')[0],
  maxDailyCalls: 250,
}

/**
 * Check if we're approaching rate limit
 */
export function isApproachingRateLimit(state: RateLimitState): boolean {
  return state.dailyCalls >= state.maxDailyCalls * 0.8 // 80% threshold
}

/**
 * Check if rate limit is exceeded
 */
export function isRateLimitExceeded(state: RateLimitState): boolean {
  return state.dailyCalls >= state.maxDailyCalls
}
