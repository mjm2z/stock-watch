import { NextRequest, NextResponse } from 'next/server'
import { analyzeStock, StockAnalysis } from '@/lib/claude'
import { getQuote, getFundamentals } from '@/lib/finnhub'
import { serverCache, CACHE_TTL } from '@/lib/cache'

interface AnalyzeRequest {
  ticker: string
  forceRefresh?: boolean
}

interface CachedAnalysis {
  analysis: StockAnalysis
  priceAtAnalysis: number
}

/**
 * Check if cached analysis should be invalidated
 * - Re-analyze if price moved > 5% since last analysis
 */
function shouldInvalidateCache(
  cached: CachedAnalysis,
  currentPrice: number
): boolean {
  const priceDiff = Math.abs(currentPrice - cached.priceAtAnalysis)
  const percentChange = (priceDiff / cached.priceAtAnalysis) * 100
  return percentChange > 5
}

/**
 * POST /api/analyze
 * Analyze a stock using Claude AI
 *
 * Body:
 * - ticker: string (required)
 * - forceRefresh: boolean (optional, bypass cache)
 */
export async function POST(request: NextRequest) {
  try {
    const body: AnalyzeRequest = await request.json()
    const { ticker, forceRefresh = false } = body

    if (!ticker) {
      return NextResponse.json(
        { error: 'Ticker is required' },
        { status: 400 }
      )
    }

    const upperTicker = ticker.toUpperCase()
    const cacheKey = `analysis:${upperTicker}`

    // Check API key first
    if (!process.env.ANTHROPIC_API_KEY) {
      return NextResponse.json(
        {
          error: 'Anthropic API key not configured',
          code: 'CONFIG_ERROR',
          help: 'Add ANTHROPIC_API_KEY to your .env.local file',
        },
        { status: 500 }
      )
    }

    // Fetch current quote first (needed for cache validation)
    let quote
    try {
      quote = await getQuote(upperTicker)
    } catch (error) {
      return NextResponse.json(
        {
          error: `Failed to fetch quote for ${upperTicker}`,
          code: 'QUOTE_ERROR',
          details: error instanceof Error ? error.message : 'Unknown error',
        },
        { status: 500 }
      )
    }

    // Check cache unless forceRefresh is true
    if (!forceRefresh) {
      const cached = serverCache.get<CachedAnalysis>(cacheKey)
      if (cached) {
        // Check if price has moved significantly
        if (!shouldInvalidateCache(cached, quote.price)) {
          return NextResponse.json({
            analysis: cached.analysis,
            cached: true,
            cacheAge: Date.now() - new Date(cached.analysis.timestamp).getTime(),
          })
        }
        // Price moved > 5%, invalidate cache
        console.log(`Invalidating cache for ${upperTicker}: price moved > 5%`)
        serverCache.delete(cacheKey)
      }
    }

    // Fetch fundamentals (optional, analysis will work without it)
    let fundamentals = null
    try {
      fundamentals = await getFundamentals(upperTicker)
    } catch (error) {
      console.warn(`Could not fetch fundamentals for ${upperTicker}:`, error)
      // Continue without fundamentals
    }

    // Run Claude analysis
    const analysis = await analyzeStock(upperTicker, quote, fundamentals)

    // Cache the analysis with the price at time of analysis
    serverCache.set(
      cacheKey,
      { analysis, priceAtAnalysis: quote.price },
      CACHE_TTL.ANALYSIS
    )

    return NextResponse.json({
      analysis,
      cached: false,
    })
  } catch (error) {
    console.error('Analysis error:', error)

    if (error instanceof Error) {
      // Handle specific error types
      if (error.message.includes('API key')) {
        return NextResponse.json(
          { error: error.message, code: 'AUTH_ERROR' },
          { status: 401 }
        )
      }
      if (error.message.includes('Rate limit')) {
        return NextResponse.json(
          { error: error.message, code: 'RATE_LIMIT' },
          { status: 429 }
        )
      }

      return NextResponse.json(
        { error: error.message, code: 'ANALYSIS_ERROR' },
        { status: 500 }
      )
    }

    return NextResponse.json(
      { error: 'Analysis failed', code: 'UNKNOWN_ERROR' },
      { status: 500 }
    )
  }
}
