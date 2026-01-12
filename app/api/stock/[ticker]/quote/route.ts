import { NextRequest, NextResponse } from 'next/server'
import { getActiveProvider } from '@/lib/market-data'
import { getQuote as finnhubQuote, getFundamentals as finnhubFundamentals } from '@/lib/finnhub'
import { getQuote as fmpQuote, getFundamentals as fmpFundamentals } from '@/lib/fmp'

interface RouteContext {
  params: Promise<{
    ticker: string
  }>
}

/**
 * GET /api/stock/[ticker]/quote
 * Fetch current quote and basic fundamentals for a stock
 */
export async function GET(_request: NextRequest, context: RouteContext) {
  try {
    const { ticker } = await context.params

    if (!ticker) {
      return NextResponse.json(
        { error: 'Ticker is required' },
        { status: 400 }
      )
    }

    const provider = getActiveProvider()
    const upperTicker = ticker.toUpperCase()

    let quote
    let fundamentals

    if (provider === 'finnhub') {
      // Fetch quote and fundamentals in parallel
      const [quoteResult, fundamentalsResult] = await Promise.allSettled([
        finnhubQuote(upperTicker),
        finnhubFundamentals(upperTicker),
      ])

      if (quoteResult.status === 'rejected') {
        throw new Error(quoteResult.reason?.message || 'Failed to fetch quote')
      }

      quote = quoteResult.value
      fundamentals = fundamentalsResult.status === 'fulfilled' ? fundamentalsResult.value : null
    } else {
      const [quoteResult, fundamentalsResult] = await Promise.allSettled([
        fmpQuote(upperTicker),
        fmpFundamentals(upperTicker),
      ])

      if (quoteResult.status === 'rejected') {
        throw new Error(quoteResult.reason?.message || 'Failed to fetch quote')
      }

      quote = quoteResult.value
      fundamentals = fundamentalsResult.status === 'fulfilled' ? fundamentalsResult.value : null
    }

    return NextResponse.json({
      quote,
      fundamentals,
      meta: {
        ticker: upperTicker,
        provider,
        timestamp: new Date().toISOString(),
      },
    })
  } catch (error) {
    console.error('Quote error:', error)

    if (error instanceof Error) {
      return NextResponse.json(
        { error: error.message, code: 'QUOTE_ERROR' },
        { status: 500 }
      )
    }

    return NextResponse.json(
      { error: 'Failed to fetch quote', code: 'UNKNOWN_ERROR' },
      { status: 500 }
    )
  }
}
