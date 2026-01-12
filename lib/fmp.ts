import type { Stock, Quote, Fundamentals, PriceData } from '@/types'
import type { MarketDataProvider } from './market-data'
import { applyQualityFilters, DEFAULT_QUALITY_FILTERS } from './market-data'
import { serverCache, CACHE_TTL, fmpRateLimiter } from './cache'

/**
 * FMP API Response Types
 */
interface FMPSearchResult {
  symbol: string
  name: string
  currency: string
  stockExchange: string
  exchangeShortName: string
}

interface FMPQuote {
  symbol: string
  name: string
  price: number
  changesPercentage: number
  change: number
  dayLow: number
  dayHigh: number
  yearHigh: number
  yearLow: number
  marketCap: number
  priceAvg50: number
  priceAvg200: number
  exchange: string
  volume: number
  avgVolume: number
  open: number
  previousClose: number
  eps: number
  pe: number
  sharesOutstanding: number
  timestamp: number
}

interface FMPHistoricalPrice {
  date: string
  open: number
  high: number
  low: number
  close: number
  adjClose: number
  volume: number
  unadjustedVolume: number
  change: number
  changePercent: number
  vwap: number
  label: string
  changeOverTime: number
}

interface FMPProfile {
  symbol: string
  companyName: string
  currency: string
  exchange: string
  exchangeShortName: string
  price: number
  beta: number
  volAvg: number
  mktCap: number
  lastDiv: number
  range: string
  changes: number
  industry: string
  sector: string
  description: string
  ceo: string
  website: string
  phone: string
  address: string
  city: string
  state: string
  zip: string
  country: string
  dcfDiff: number
  dcf: number
  image: string
  ipoDate: string
  defaultImage: boolean
  isEtf: boolean
  isActivelyTrading: boolean
  isAdr: boolean
  isFund: boolean
}

/**
 * FMP API Error
 */
class FMPError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public isRateLimit: boolean = false
  ) {
    super(message)
    this.name = 'FMPError'
  }
}

/**
 * Get the FMP API key from environment
 */
function getApiKey(): string {
  const apiKey = process.env.FMP_API_KEY
  if (!apiKey) {
    throw new FMPError('FMP_API_KEY environment variable is not set')
  }
  return apiKey
}

/**
 * Make a request to the FMP API with rate limiting
 */
async function fmpFetch<T>(endpoint: string, params: Record<string, string> = {}): Promise<T> {
  // Check rate limit before making call
  if (!fmpRateLimiter.canMakeCall()) {
    throw new FMPError(
      'Daily API limit reached (250 calls). Try again tomorrow.',
      429,
      true
    )
  }

  const apiKey = getApiKey()
  const searchParams = new URLSearchParams({ ...params, apikey: apiKey })
  const url = `https://financialmodelingprep.com/api/v3/${endpoint}?${searchParams}`

  try {
    const response = await fetch(url, {
      next: { revalidate: 0 }, // Disable Next.js cache, we handle caching ourselves
    })

    // Record the API call
    fmpRateLimiter.recordCall()

    if (!response.ok) {
      // Log the full error details server-side for debugging
      console.error(`FMP API error: ${response.status} ${response.statusText} for endpoint: ${endpoint}`)

      if (response.status === 429) {
        throw new FMPError('Rate limit exceeded', 429, true)
      }
      if (response.status === 403) {
        throw new FMPError(
          `API access denied for endpoint "${endpoint}". Check your API key is valid and has access to this endpoint.`,
          403
        )
      }
      if (response.status === 401) {
        throw new FMPError('Invalid API key. Please check your FMP_API_KEY.', 401)
      }
      throw new FMPError(`FMP API error: ${response.statusText} (${endpoint})`, response.status)
    }

    const data = await response.json()

    // FMP returns an error message object for invalid requests
    if (data && typeof data === 'object' && 'Error Message' in data) {
      throw new FMPError(data['Error Message'])
    }

    return data as T
  } catch (error) {
    if (error instanceof FMPError) {
      throw error
    }
    throw new FMPError(
      error instanceof Error ? error.message : 'Unknown error occurred'
    )
  }
}

/**
 * Search for stocks using FMP API
 * Returns quality-filtered results
 */
export async function searchStocks(query: string): Promise<Stock[]> {
  if (!query || query.trim().length < 1) {
    return []
  }

  const cacheKey = `search:${query.toLowerCase().trim()}`

  // Check cache first
  const cached = serverCache.get<Stock[]>(cacheKey)
  if (cached) {
    return cached
  }

  // Search for stocks
  const searchResults = await fmpFetch<FMPSearchResult[]>('search', {
    query: query.trim(),
    limit: '50',
  })

  if (!searchResults || searchResults.length === 0) {
    return []
  }

  // Get quotes for all search results to have price/volume data
  const symbols = searchResults
    .filter(r => ['NYSE', 'NASDAQ', 'AMEX'].includes(r.exchangeShortName))
    .slice(0, 20) // Limit to 20 to reduce API calls
    .map(r => r.symbol)

  if (symbols.length === 0) {
    return []
  }

  // Batch fetch quotes
  const quotes = await fmpFetch<FMPQuote[]>(`quote/${symbols.join(',')}`)

  if (!quotes || quotes.length === 0) {
    return []
  }

  // Get profiles for sector info (batch)
  let profiles: FMPProfile[] = []
  try {
    profiles = await fmpFetch<FMPProfile[]>(`profile/${symbols.join(',')}`)
  } catch {
    // Profiles are optional, continue without them
  }

  const profileMap = new Map(profiles.map(p => [p.symbol, p]))

  // Map to Stock type
  const stocks: Stock[] = quotes.map(quote => {
    const profile = profileMap.get(quote.symbol)
    return {
      ticker: quote.symbol,
      name: quote.name || profile?.companyName || quote.symbol,
      price: quote.price,
      change: quote.change,
      changePercent: quote.changesPercentage,
      marketCap: quote.marketCap,
      sector: profile?.sector || 'Unknown',
      exchange: quote.exchange,
      volume: quote.volume,
      avgVolume: quote.avgVolume,
    }
  })

  // Apply quality filters
  const filteredStocks = applyQualityFilters(stocks, DEFAULT_QUALITY_FILTERS)

  // Cache the results
  serverCache.set(cacheKey, filteredStocks, CACHE_TTL.SEARCH)

  return filteredStocks
}

/**
 * Get a real-time quote for a single ticker
 */
export async function getQuote(ticker: string): Promise<Quote> {
  const cacheKey = `quote:${ticker.toUpperCase()}`

  const cached = serverCache.get<Quote>(cacheKey)
  if (cached) {
    return cached
  }

  const quotes = await fmpFetch<FMPQuote[]>(`quote/${ticker.toUpperCase()}`)

  if (!quotes || quotes.length === 0) {
    throw new FMPError(`No quote found for ${ticker}`)
  }

  const q = quotes[0]
  const quote: Quote = {
    ticker: q.symbol,
    price: q.price,
    open: q.open,
    high: q.dayHigh,
    low: q.dayLow,
    previousClose: q.previousClose,
    volume: q.volume,
    change: q.change,
    changePercent: q.changesPercentage,
    timestamp: new Date(q.timestamp * 1000).toISOString(),
  }

  serverCache.set(cacheKey, quote, CACHE_TTL.QUOTE)

  return quote
}

/**
 * Get quotes for multiple tickers at once
 */
export async function getBatchQuotes(tickers: string[]): Promise<Quote[]> {
  if (tickers.length === 0) {
    return []
  }

  const symbols = tickers.map(t => t.toUpperCase()).join(',')
  const quotes = await fmpFetch<FMPQuote[]>(`quote/${symbols}`)

  return quotes.map(q => ({
    ticker: q.symbol,
    price: q.price,
    open: q.open,
    high: q.dayHigh,
    low: q.dayLow,
    previousClose: q.previousClose,
    volume: q.volume,
    change: q.change,
    changePercent: q.changesPercentage,
    timestamp: new Date(q.timestamp * 1000).toISOString(),
  }))
}

/**
 * Get company fundamentals
 */
export async function getFundamentals(ticker: string): Promise<Fundamentals> {
  const cacheKey = `fundamentals:${ticker.toUpperCase()}`

  const cached = serverCache.get<Fundamentals>(cacheKey)
  if (cached) {
    return cached
  }

  const [profiles, quotes] = await Promise.all([
    fmpFetch<FMPProfile[]>(`profile/${ticker.toUpperCase()}`),
    fmpFetch<FMPQuote[]>(`quote/${ticker.toUpperCase()}`),
  ])

  if (!profiles || profiles.length === 0) {
    throw new FMPError(`No profile found for ${ticker}`)
  }

  const profile = profiles[0]
  const quote = quotes?.[0]

  const fundamentals: Fundamentals = {
    ticker: profile.symbol,
    name: profile.companyName,
    description: profile.description,
    sector: profile.sector,
    industry: profile.industry,
    marketCap: profile.mktCap,
    pe: quote?.pe || null,
    eps: quote?.eps || null,
    revenue: null, // Would need income statement API
    revenueGrowth: null,
    profitMargin: null,
    debtToEquity: null,
    dividendYield: profile.lastDiv ? (profile.lastDiv / profile.price) * 100 : null,
    beta: profile.beta,
    fiftyTwoWeekHigh: quote?.yearHigh || 0,
    fiftyTwoWeekLow: quote?.yearLow || 0,
    avgVolume: profile.volAvg,
    sharesOutstanding: quote?.sharesOutstanding || 0,
  }

  serverCache.set(cacheKey, fundamentals, CACHE_TTL.FUNDAMENTALS)

  return fundamentals
}

/**
 * Get historical price data for charting
 */
export async function getHistoricalPrices(
  ticker: string,
  range: string = '1M'
): Promise<PriceData[]> {
  const cacheKey = `history:${ticker.toUpperCase()}:${range}`

  const cached = serverCache.get<PriceData[]>(cacheKey)
  if (cached) {
    return cached
  }

  // Determine the endpoint and parameters based on range
  let endpoint: string
  const params: Record<string, string> = {}

  switch (range) {
    case '1D':
      endpoint = `historical-chart/5min/${ticker.toUpperCase()}`
      break
    case '1W':
      endpoint = `historical-chart/15min/${ticker.toUpperCase()}`
      break
    case '1M':
    case '3M':
    case '1Y':
    case '5Y':
      endpoint = `historical-price-full/${ticker.toUpperCase()}`
      // Calculate from date based on range
      const fromDate = new Date()
      switch (range) {
        case '1M':
          fromDate.setMonth(fromDate.getMonth() - 1)
          break
        case '3M':
          fromDate.setMonth(fromDate.getMonth() - 3)
          break
        case '1Y':
          fromDate.setFullYear(fromDate.getFullYear() - 1)
          break
        case '5Y':
          fromDate.setFullYear(fromDate.getFullYear() - 5)
          break
      }
      params.from = fromDate.toISOString().split('T')[0]
      params.to = new Date().toISOString().split('T')[0]
      break
    default:
      endpoint = `historical-price-full/${ticker.toUpperCase()}`
  }

  const data = await fmpFetch<FMPHistoricalPrice[] | { historical: FMPHistoricalPrice[] }>(
    endpoint,
    params
  )

  // Handle different response formats
  const historicalData = Array.isArray(data) ? data : data?.historical || []

  const prices: PriceData[] = historicalData.map(h => ({
    date: h.date,
    open: h.open,
    high: h.high,
    low: h.low,
    close: h.close,
    volume: h.volume,
  }))

  // Sort by date ascending
  prices.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())

  // Determine cache TTL based on range
  const ttl = range === '1D' || range === '1W'
    ? CACHE_TTL.HISTORICAL_INTRADAY
    : CACHE_TTL.HISTORICAL_DAILY

  serverCache.set(cacheKey, prices, ttl)

  return prices
}

/**
 * FMP Market Data Provider implementation
 */
export const fmpProvider: MarketDataProvider = {
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
  return fmpRateLimiter.getUsage()
}
