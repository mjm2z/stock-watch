import { NextRequest, NextResponse } from 'next/server'
import { getAlpacaHistory, hasAlpacaData } from '@/lib/alpaca-market-data'
import { getHistoricalPrices as yahooHistory } from '@/lib/yahoo-finance'

type ValidRange = '1D' | '1W' | '1M' | '3M' | '6M' | '10Y' | '30Y' | '1Y' | '5Y' | 'CUSTOM'

const VALID_RANGES: ValidRange[] = [
  '1D',
  '1W',
  '1M',
  '3M',
  '6M',
  '10Y',
  '30Y',
  '1Y',
  '5Y',
  'CUSTOM',
]

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
 * - range: '1D' | '1W' | '1M' | '3M' | '6M' | '10Y' | '30Y' | '1Y' | '5Y' (default: '1M')
 */
export async function GET(request: NextRequest, context: RouteContext) {
  try {
    const { ticker } = await context.params
    const searchParams = request.nextUrl.searchParams
    const range = (searchParams.get('range') || '1M').toUpperCase() as ValidRange

    if (!ticker) {
      return NextResponse.json({ error: 'Ticker is required' }, { status: 400 })
    }

    if (!VALID_RANGES.includes(range)) {
      return NextResponse.json(
        { error: `Invalid range. Must be one of: ${VALID_RANGES.join(', ')}` },
        { status: 400 }
      )
    }

    const adjustment = searchParams.get('adjustment') === 'raw' ? 'raw' : 'all'
    const useAlpaca = hasAlpacaData()
    if (adjustment === 'raw' && !useAlpaca)
      return NextResponse.json(
        {
          error:
            'Raw Alpaca history is unavailable. Choose analytical mode; broker overlays remain disabled.',
        },
        { status: 503 }
      )
    const options = {
      start: searchParams.get('start') || undefined,
      end: searchParams.get('end') || undefined,
      timeframe: searchParams.get('timeframe') || undefined,
    }
    if (!useAlpaca && (['CUSTOM', '6M', '10Y', '30Y'].includes(range) || options.timeframe))
      return NextResponse.json(
        { error: 'Custom resolution/dates require configured Alpaca data' },
        { status: 503 }
      )
    const prices = useAlpaca
      ? await getAlpacaHistory(ticker, range, adjustment, options)
      : await yahooHistory(ticker.toUpperCase(), range as '1D' | '1W' | '1M' | '3M' | '1Y' | '5Y')

    const days = (
      {
        '1D': 4,
        '1W': 7,
        '1M': 32,
        '3M': 95,
        '6M': 184,
        '1Y': 370,
        '5Y': 1830,
        '10Y': 3653,
        '30Y': 10958,
      } as Record<string, number>
    )[range]
    const requestedStart = options.start || new Date(Date.now() - days * 86400000).toISOString()
    return NextResponse.json({
      data: prices,
      meta: {
        requestedStart,
        requestedEnd: options.end || new Date().toISOString(),
        partial: Boolean(
          prices.length && Date.parse(prices[0].date) - Date.parse(requestedStart) > 7 * 86400000
        ),
        coverageStatus: prices.length ? 'available' : 'empty',
        ticker: ticker.toUpperCase(),
        range,
        count: prices.length,
        provider: useAlpaca ? 'alpaca-iex' : 'yahoo',
        resolution:
          options.timeframe ||
          ({ '1D': '5Min', '1W': '1Hour' } as Record<string, string>)[range] ||
          '1Day',
        adjustment: useAlpaca ? adjustment : 'provider-defined',
        asOf: new Date().toISOString(),
        from: prices[0]?.date,
        to: prices[prices.length - 1]?.date,
      },
    })
  } catch (error) {
    console.error('Historical data error:', error)

    if (error instanceof Error) {
      return NextResponse.json({ error: error.message, code: 'HISTORY_ERROR' }, { status: 500 })
    }

    return NextResponse.json(
      { error: 'Failed to fetch historical data', code: 'UNKNOWN_ERROR' },
      { status: 500 }
    )
  }
}
