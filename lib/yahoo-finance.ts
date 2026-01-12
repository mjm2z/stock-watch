import type { PriceData } from '@/types'
import { serverCache, CACHE_TTL } from './cache'

/**
 * Yahoo Finance API for historical price data
 * Free, no API key required
 */

interface YahooChartResult {
  chart: {
    result: Array<{
      meta: {
        currency: string
        symbol: string
        regularMarketPrice: number
      }
      timestamp: number[]
      indicators: {
        quote: Array<{
          open: number[]
          high: number[]
          low: number[]
          close: number[]
          volume: number[]
        }>
      }
    }>
    error: null | { code: string; description: string }
  }
}

type TimeRange = '1D' | '1W' | '1M' | '3M' | '1Y' | '5Y'

/**
 * Map our time ranges to Yahoo Finance parameters
 */
function getYahooParams(range: TimeRange): { range: string; interval: string } {
  switch (range) {
    case '1D':
      return { range: '1d', interval: '5m' }
    case '1W':
      return { range: '5d', interval: '15m' }
    case '1M':
      return { range: '1mo', interval: '1d' }
    case '3M':
      return { range: '3mo', interval: '1d' }
    case '1Y':
      return { range: '1y', interval: '1d' }
    case '5Y':
      return { range: '5y', interval: '1wk' }
    default:
      return { range: '1mo', interval: '1d' }
  }
}

/**
 * Fetch historical price data from Yahoo Finance
 */
export async function getHistoricalPrices(
  ticker: string,
  range: TimeRange = '1M'
): Promise<PriceData[]> {
  const cacheKey = `yahoo:history:${ticker.toUpperCase()}:${range}`

  const cached = serverCache.get<PriceData[]>(cacheKey)
  if (cached) {
    return cached
  }

  const { range: yahooRange, interval } = getYahooParams(range)
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${ticker.toUpperCase()}?range=${yahooRange}&interval=${interval}`

  try {
    const response = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      },
    })

    if (!response.ok) {
      console.error(`Yahoo Finance error: ${response.status} for ${ticker}`)
      return []
    }

    const data: YahooChartResult = await response.json()

    if (data.chart.error) {
      console.error(`Yahoo Finance error: ${data.chart.error.description}`)
      return []
    }

    const result = data.chart.result?.[0]
    if (!result || !result.timestamp || !result.indicators.quote?.[0]) {
      return []
    }

    const { timestamp } = result
    const quote = result.indicators.quote[0]

    const prices: PriceData[] = []
    for (let i = 0; i < timestamp.length; i++) {
      // Skip if any value is null
      if (
        quote.open[i] == null ||
        quote.high[i] == null ||
        quote.low[i] == null ||
        quote.close[i] == null
      ) {
        continue
      }

      prices.push({
        date: new Date(timestamp[i] * 1000).toISOString(),
        open: quote.open[i],
        high: quote.high[i],
        low: quote.low[i],
        close: quote.close[i],
        volume: quote.volume[i] || 0,
      })
    }

    // Cache based on range
    const ttl = range === '1D' || range === '1W'
      ? CACHE_TTL.HISTORICAL_INTRADAY
      : CACHE_TTL.HISTORICAL_DAILY

    serverCache.set(cacheKey, prices, ttl)

    return prices
  } catch (error) {
    console.error('Yahoo Finance fetch error:', error)
    return []
  }
}
