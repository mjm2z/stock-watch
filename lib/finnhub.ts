import type { Stock, Quote, Fundamentals, PriceData } from '@/types'
import type { MarketDataProvider } from './market-data'
import { applyQualityFilters, DEFAULT_QUALITY_FILTERS } from './market-data'
import { serverCache, CACHE_TTL } from './cache'

/**
 * Finnhub API Response Types
 */
interface FinnhubSearchResult {
  count: number
  result: Array<{
    description: string
    displaySymbol: string
    symbol: string
    type: string
  }>
}

interface FinnhubQuote {
  c: number  // Current price
  d: number  // Change
  dp: number // Percent change
  h: number  // High price of the day
  l: number  // Low price of the day
  o: number  // Open price of the day
  pc: number // Previous close price
  t: number  // Timestamp
}

interface FinnhubProfile {
  country: string
  currency: string
  exchange: string
  finnhubIndustry: string
  ipo: string
  logo: string
  marketCapitalization: number
  name: string
  phone: string
  shareOutstanding: number
  ticker: string
  weburl: string
}

interface FinnhubCandle {
  c: number[] // Close prices
  h: number[] // High prices
  l: number[] // Low prices
  o: number[] // Open prices
  s: string   // Status
  t: number[] // Timestamps
  v: number[] // Volume
}

/**
 * Finnhub API Error
 */
class FinnhubError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public isRateLimit: boolean = false
  ) {
    super(message)
    this.name = 'FinnhubError'
  }
}

/**
 * Rate limiter for Finnhub (60 calls/minute on free tier)
 */
class FinnhubRateLimiter {
  private calls: number[] = []
  private readonly maxCallsPerMinute = 60

  canMakeCall(): boolean {
    this.cleanup()
    return this.calls.length < this.maxCallsPerMinute
  }

  recordCall(): void {
    this.calls.push(Date.now())
  }

  private cleanup(): void {
    const oneMinuteAgo = Date.now() - 60000
    this.calls = this.calls.filter(t => t > oneMinuteAgo)
  }

  getUsage(): { used: number; limit: number; remaining: number } {
    this.cleanup()
    return {
      used: this.calls.length,
      limit: this.maxCallsPerMinute,
      remaining: this.maxCallsPerMinute - this.calls.length,
    }
  }
}

const rateLimiter = new FinnhubRateLimiter()

/**
 * Get the Finnhub API key from environment
 */
function getApiKey(): string {
  const apiKey = process.env.FINNHUB_API_KEY
  if (!apiKey) {
    throw new FinnhubError('FINNHUB_API_KEY environment variable is not set')
  }
  return apiKey
}

/**
 * Make a request to the Finnhub API with rate limiting
 */
async function finnhubFetch<T>(endpoint: string, params: Record<string, string> = {}): Promise<T> {
  if (!rateLimiter.canMakeCall()) {
    throw new FinnhubError(
      'Rate limit reached (60 calls/minute). Please wait a moment.',
      429,
      true
    )
  }

  const apiKey = getApiKey()
  const searchParams = new URLSearchParams({ ...params, token: apiKey })
  const url = `https://finnhub.io/api/v1/${endpoint}?${searchParams}`

  try {
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
      },
    })

    rateLimiter.recordCall()

    if (!response.ok) {
      console.error(`Finnhub API error: ${response.status} ${response.statusText} for endpoint: ${endpoint}`)

      // Try to parse error message from response
      let errorMessage = response.statusText
      try {
        const errorData = await response.json()
        if (errorData.error) {
          errorMessage = errorData.error
        }
      } catch {
        // Ignore JSON parse errors for error response
      }

      if (response.status === 429) {
        throw new FinnhubError('Rate limit exceeded. Please wait a moment.', 429, true)
      }
      if (response.status === 403) {
        // 403 can mean either invalid API key OR subscription required
        if (errorMessage.includes("don't have access")) {
          throw new FinnhubError(
            `This feature requires a Finnhub paid subscription (${endpoint})`,
            response.status
          )
        }
        throw new FinnhubError('Invalid API key. Please check your FINNHUB_API_KEY.', response.status)
      }
      if (response.status === 401) {
        throw new FinnhubError('Invalid API key. Please check your FINNHUB_API_KEY.', response.status)
      }
      throw new FinnhubError(`Finnhub API error: ${errorMessage} (${endpoint})`, response.status)
    }

    const text = await response.text()

    // Check if response is HTML (error page) instead of JSON
    if (text.startsWith('<!DOCTYPE') || text.startsWith('<html')) {
      console.error(`Finnhub returned HTML instead of JSON for endpoint: ${endpoint}`)
      throw new FinnhubError(`Finnhub API returned an error page for ${endpoint}`, 500)
    }

    try {
      const data = JSON.parse(text)
      return data as T
    } catch {
      console.error(`Failed to parse Finnhub response for ${endpoint}:`, text.substring(0, 200))
      throw new FinnhubError(`Invalid JSON response from Finnhub for ${endpoint}`, 500)
    }
  } catch (error) {
    if (error instanceof FinnhubError) {
      throw error
    }
    throw new FinnhubError(
      error instanceof Error ? error.message : 'Unknown error occurred'
    )
  }
}

/**
 * Search for stocks using Finnhub API
 * Returns quality-filtered results
 */
export async function searchStocks(query: string): Promise<Stock[]> {
  if (!query || query.trim().length < 1) {
    return []
  }

  const cacheKey = `finnhub:search:${query.toLowerCase().trim()}`

  const cached = serverCache.get<Stock[]>(cacheKey)
  if (cached) {
    return cached
  }

  // Search for symbols
  const searchResults = await finnhubFetch<FinnhubSearchResult>('search', {
    q: query.trim(),
  })

  if (!searchResults.result || searchResults.result.length === 0) {
    return []
  }

  // Filter to only common stocks on US exchanges
  const usStocks = searchResults.result
    .filter(r =>
      r.type === 'Common Stock' &&
      !r.symbol.includes('.') // Exclude foreign exchanges like AAPL.DE
    )
    .slice(0, 5) // Limit to 5 to reduce API calls (was 10)

  if (usStocks.length === 0) {
    return []
  }

  // Fetch quotes for each stock (skip profiles to reduce API calls)
  const stocks: Stock[] = []

  for (const result of usStocks) {
    try {
      // Only fetch quote, skip profile to save API calls
      const quote = await finnhubFetch<FinnhubQuote>('quote', { symbol: result.symbol })

      // Skip if no valid quote data
      if (!quote || quote.c === 0) {
        continue
      }

      stocks.push({
        ticker: result.symbol,
        name: result.description, // Use search result description
        price: quote.c,
        change: quote.d || 0,
        changePercent: quote.dp || 0,
        marketCap: 0, // Skip profile fetch to save API calls
        sector: 'Unknown',
        exchange: 'US',
        volume: 0,
        avgVolume: 0,
      })
    } catch (error) {
      // Skip stocks that fail to fetch
      console.error(`Failed to fetch data for ${result.symbol}:`, error)
    }
  }

  // Skip quality filters for Finnhub search results since we don't fetch profile data
  // We only have price from the quote - rely on the "Common Stock" filter instead
  // Filter to stocks with valid prices above $5
  const validStocks = stocks.filter(s => s.price >= 5)

  serverCache.set(cacheKey, validStocks, CACHE_TTL.SEARCH)

  return validStocks
}

/**
 * Get a real-time quote for a single ticker
 */
export async function getQuote(ticker: string): Promise<Quote> {
  const cacheKey = `finnhub:quote:${ticker.toUpperCase()}`

  const cached = serverCache.get<Quote>(cacheKey)
  if (cached) {
    return cached
  }

  const q = await finnhubFetch<FinnhubQuote>('quote', { symbol: ticker.toUpperCase() })

  if (!q || q.c === 0) {
    throw new FinnhubError(`No quote found for ${ticker}`)
  }

  const quote: Quote = {
    ticker: ticker.toUpperCase(),
    price: q.c,
    open: q.o,
    high: q.h,
    low: q.l,
    previousClose: q.pc,
    volume: 0, // Not provided in quote endpoint
    change: q.d,
    changePercent: q.dp,
    timestamp: new Date(q.t * 1000).toISOString(),
  }

  serverCache.set(cacheKey, quote, CACHE_TTL.QUOTE)

  return quote
}

/**
 * Get quotes for multiple tickers at once
 */
export async function getBatchQuotes(tickers: string[]): Promise<Quote[]> {
  // Finnhub doesn't have a batch quote endpoint, so we fetch individually
  const quotes: Quote[] = []

  for (const ticker of tickers) {
    try {
      const quote = await getQuote(ticker)
      quotes.push(quote)
    } catch (error) {
      console.error(`Failed to fetch quote for ${ticker}:`, error)
    }
  }

  return quotes
}

/**
 * Get company fundamentals
 * Note: stock/profile2 endpoint may have restrictions on free tier
 * This function handles profile failures gracefully
 */
export async function getFundamentals(ticker: string): Promise<Fundamentals> {
  const cacheKey = `finnhub:fundamentals:${ticker.toUpperCase()}`

  const cached = serverCache.get<Fundamentals>(cacheKey)
  if (cached) {
    return cached
  }

  // Fetch profile and quote separately to handle profile failures gracefully
  const [profileResult, quoteResult] = await Promise.allSettled([
    finnhubFetch<FinnhubProfile>('stock/profile2', { symbol: ticker.toUpperCase() }),
    finnhubFetch<FinnhubQuote>('quote', { symbol: ticker.toUpperCase() }),
  ])

  const profile = profileResult.status === 'fulfilled' ? profileResult.value : null
  const quote = quoteResult.status === 'fulfilled' ? quoteResult.value : null

  // If we have no data at all, throw an error
  if (!profile && !quote) {
    throw new FinnhubError(`No data found for ${ticker}`)
  }

  // Build fundamentals with available data
  const fundamentals: Fundamentals = {
    ticker: profile?.ticker || ticker.toUpperCase(),
    name: profile?.name || ticker.toUpperCase(),
    description: undefined,
    sector: profile?.finnhubIndustry || 'Unknown',
    industry: profile?.finnhubIndustry || 'Unknown',
    marketCap: profile?.marketCapitalization ? profile.marketCapitalization * 1_000_000 : 0,
    pe: null,
    eps: null,
    revenue: null,
    revenueGrowth: null,
    profitMargin: null,
    debtToEquity: null,
    dividendYield: null,
    beta: null,
    fiftyTwoWeekHigh: quote?.h || 0,
    fiftyTwoWeekLow: quote?.l || 0,
    avgVolume: 0,
    sharesOutstanding: profile?.shareOutstanding ? profile.shareOutstanding * 1_000_000 : 0,
  }

  // Only cache if we have meaningful data
  if (profile?.name) {
    serverCache.set(cacheKey, fundamentals, CACHE_TTL.FUNDAMENTALS)
  }

  return fundamentals
}

/**
 * Get historical price data for charting
 */
export async function getHistoricalPrices(
  ticker: string,
  range: string = '1M'
): Promise<PriceData[]> {
  const cacheKey = `finnhub:history:${ticker.toUpperCase()}:${range}`

  const cached = serverCache.get<PriceData[]>(cacheKey)
  if (cached) {
    return cached
  }

  // Calculate from/to timestamps based on range
  const now = Math.floor(Date.now() / 1000)
  let from: number
  let resolution: string

  switch (range) {
    case '1D':
      from = now - 24 * 60 * 60
      resolution = '5'
      break
    case '1W':
      from = now - 7 * 24 * 60 * 60
      resolution = '15'
      break
    case '1M':
      from = now - 30 * 24 * 60 * 60
      resolution = 'D'
      break
    case '3M':
      from = now - 90 * 24 * 60 * 60
      resolution = 'D'
      break
    case '1Y':
      from = now - 365 * 24 * 60 * 60
      resolution = 'D'
      break
    case '5Y':
      from = now - 5 * 365 * 24 * 60 * 60
      resolution = 'W'
      break
    default:
      from = now - 30 * 24 * 60 * 60
      resolution = 'D'
  }

  const candles = await finnhubFetch<FinnhubCandle>('stock/candle', {
    symbol: ticker.toUpperCase(),
    resolution,
    from: from.toString(),
    to: now.toString(),
  })

  if (!candles || candles.s !== 'ok' || !candles.t) {
    return []
  }

  const prices: PriceData[] = candles.t.map((timestamp, i) => ({
    date: new Date(timestamp * 1000).toISOString(),
    open: candles.o[i],
    high: candles.h[i],
    low: candles.l[i],
    close: candles.c[i],
    volume: candles.v[i],
  }))

  const ttl = range === '1D' || range === '1W'
    ? CACHE_TTL.HISTORICAL_INTRADAY
    : CACHE_TTL.HISTORICAL_DAILY

  serverCache.set(cacheKey, prices, ttl)

  return prices
}

/**
 * Finnhub Market Data Provider implementation
 */
export const finnhubProvider: MarketDataProvider = {
  searchStocks,
  getQuote,
  getBatchQuotes,
  getFundamentals,
  getHistoricalPrices,
}

/**
 * Get current rate limit usage
 */
export function getRateLimitUsage() {
  return rateLimiter.getUsage()
}
