import { NextRequest, NextResponse } from 'next/server'
import { getActiveProvider } from '@/lib/market-data'
import { searchStocks as finnhubSearch, getRateLimitUsage as getFinnhubUsage } from '@/lib/finnhub'
import { searchStocks as fmpSearch, getRateLimitUsage as getFmpUsage } from '@/lib/fmp'

export async function GET(request: NextRequest) {
  try {
    const searchParams = request.nextUrl.searchParams
    const query = searchParams.get('query')

    if (!query || query.trim().length === 0) {
      return NextResponse.json(
        { error: 'Query parameter is required' },
        { status: 400 }
      )
    }

    // Check if query is too short
    if (query.trim().length < 1) {
      return NextResponse.json(
        { error: 'Query must be at least 1 character' },
        { status: 400 }
      )
    }

    // Determine which provider to use
    const provider = getActiveProvider()

    let stocks
    let rateLimitUsage

    if (provider === 'finnhub') {
      stocks = await finnhubSearch(query)
      rateLimitUsage = getFinnhubUsage()
    } else {
      stocks = await fmpSearch(query)
      rateLimitUsage = getFmpUsage()
    }

    return NextResponse.json({
      data: stocks,
      meta: {
        count: stocks.length,
        query: query.trim(),
        provider,
        rateLimit: {
          used: rateLimitUsage.used,
          limit: rateLimitUsage.limit,
          remaining: rateLimitUsage.remaining,
        },
      },
    })
  } catch (error) {
    console.error('Stock search error:', error)

    // Handle specific error types
    if (error instanceof Error) {
      // Rate limit error
      if (error.message.includes('limit') || error.message.includes('Rate')) {
        return NextResponse.json(
          {
            error: 'API rate limit reached. Please wait a moment and try again.',
            code: 'RATE_LIMIT_EXCEEDED',
          },
          { status: 429 }
        )
      }

      // API key error
      if (error.message.includes('API_KEY') || error.message.includes('API key')) {
        return NextResponse.json(
          {
            error: 'API key not configured. Please add FINNHUB_API_KEY to your .env.local file.',
            code: 'CONFIG_ERROR',
          },
          { status: 500 }
        )
      }

      return NextResponse.json(
        {
          error: error.message,
          code: 'SEARCH_ERROR',
        },
        { status: 500 }
      )
    }

    return NextResponse.json(
      {
        error: 'An unexpected error occurred',
        code: 'UNKNOWN_ERROR',
      },
      { status: 500 }
    )
  }
}
