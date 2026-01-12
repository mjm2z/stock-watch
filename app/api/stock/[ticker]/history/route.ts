import { NextRequest, NextResponse } from 'next/server'
import { getHistoricalPrices as yahooHistory } from '@/lib/yahoo-finance'

type ValidRange = '1D' | '1W' | '1M' | '3M' | '1Y' | '5Y'

const VALID_RANGES: ValidRange[] = ['1D', '1W', '1M', '3M', '1Y', '5Y']

interface RouteContext {
  params: Promise<{
    ticker: string
  }>
}

/**
 * GET /api/stock/[ticker]/history
 * Fetch historical price data for charting
 * Uses Yahoo Finance (free, no API key required)
 *
 * Query params:
 * - range: '1D' | '1W' | '1M' | '3M' | '1Y' | '5Y' (default: '1M')
 */
export async function GET(request: NextRequest, context: RouteContext) {
  try {
    const { ticker } = await context.params
    const searchParams = request.nextUrl.searchParams
    const range = (searchParams.get('range') || '1M').toUpperCase() as ValidRange

    if (!ticker) {
      return NextResponse.json(
        { error: 'Ticker is required' },
        { status: 400 }
      )
    }

    if (!VALID_RANGES.includes(range)) {
      return NextResponse.json(
        { error: `Invalid range. Must be one of: ${VALID_RANGES.join(', ')}` },
        { status: 400 }
      )
    }

    // Use Yahoo Finance for historical data (free, no API key required)
    const prices = await yahooHistory(ticker.toUpperCase(), range)

    if (!prices || prices.length === 0) {
      return NextResponse.json(
        { error: `No historical data found for ${ticker}` },
        { status: 404 }
      )
    }

    return NextResponse.json({
      data: prices,
      meta: {
        ticker: ticker.toUpperCase(),
        range,
        count: prices.length,
        provider: 'yahoo',
        from: prices[0]?.date,
        to: prices[prices.length - 1]?.date,
      },
    })
  } catch (error) {
    console.error('Historical data error:', error)

    if (error instanceof Error) {
      return NextResponse.json(
        { error: error.message, code: 'HISTORY_ERROR' },
        { status: 500 }
      )
    }

    return NextResponse.json(
      { error: 'Failed to fetch historical data', code: 'UNKNOWN_ERROR' },
      { status: 500 }
    )
  }
}
