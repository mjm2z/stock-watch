import { NextRequest, NextResponse } from 'next/server'
import { getBatchQuotes } from '@/lib/finnhub'
import { serverCache, CACHE_TTL } from '@/lib/cache'

/**
 * POST /api/watchlist/prices
 * Fetch current prices for multiple tickers
 *
 * Body:
 * - tickers: string[] (required)
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { tickers } = body as { tickers: string[] }

    if (!tickers || !Array.isArray(tickers) || tickers.length === 0) {
      return NextResponse.json(
        { error: 'Tickers array is required' },
        { status: 400 }
      )
    }

    // Limit to 50 tickers max to prevent abuse
    const limitedTickers = tickers.slice(0, 50).map(t => t.toUpperCase())

    // Check cache first
    const cacheKey = `watchlist:prices:${limitedTickers.sort().join(',')}`
    const cached = serverCache.get<Record<string, { price: number; change: number; changePercent: number }>>(cacheKey)

    if (cached) {
      return NextResponse.json({
        prices: cached,
        cached: true,
      })
    }

    // Fetch quotes for all tickers
    const quotes = await getBatchQuotes(limitedTickers)

    // Transform to simple price map
    const prices: Record<string, { price: number; change: number; changePercent: number }> = {}
    for (const quote of quotes) {
      prices[quote.ticker] = {
        price: quote.price,
        change: quote.change,
        changePercent: quote.changePercent,
      }
    }

    // Cache for 2 minutes
    serverCache.set(cacheKey, prices, CACHE_TTL.QUOTE)

    return NextResponse.json({
      prices,
      cached: false,
      count: Object.keys(prices).length,
    })
  } catch (error) {
    console.error('Watchlist prices error:', error)

    if (error instanceof Error) {
      return NextResponse.json(
        { error: error.message, code: 'PRICES_ERROR' },
        { status: 500 }
      )
    }

    return NextResponse.json(
      { error: 'Failed to fetch prices', code: 'UNKNOWN_ERROR' },
      { status: 500 }
    )
  }
}
