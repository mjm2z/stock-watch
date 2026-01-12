import { NextRequest, NextResponse } from 'next/server'
import { getActiveProvider, getAvailableProviders } from '@/lib/market-data'

/**
 * Test endpoint to verify API keys are working
 * GET /api/test-api - Test the active provider
 * GET /api/test-api?provider=finnhub - Test specific provider
 * GET /api/test-api?provider=fmp - Test specific provider
 */
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams
  const requestedProvider = searchParams.get('provider')

  const available = getAvailableProviders()
  const activeProvider = getActiveProvider()

  const results: Record<string, unknown> = {
    activeProvider,
    availableProviders: available,
  }

  // Test Finnhub if requested or if it's the active provider
  if (requestedProvider === 'finnhub' || (!requestedProvider && activeProvider === 'finnhub') || requestedProvider === 'all') {
    results.finnhub = await testFinnhub()
  }

  // Test FMP if requested or if it's the active provider
  if (requestedProvider === 'fmp' || (!requestedProvider && activeProvider === 'fmp') || requestedProvider === 'all') {
    results.fmp = await testFmp()
  }

  const allSuccess = Object.values(results)
    .filter((v): v is { success: boolean } => typeof v === 'object' && v !== null && 'success' in v)
    .every(v => v.success)

  return NextResponse.json(results, { status: allSuccess ? 200 : 500 })
}

async function testFinnhub(): Promise<Record<string, unknown>> {
  const apiKey = process.env.FINNHUB_API_KEY

  if (!apiKey) {
    return {
      success: false,
      error: 'FINNHUB_API_KEY is not set',
      help: 'Get a free API key at https://finnhub.io/',
    }
  }

  try {
    // Test with a simple quote request for AAPL
    const response = await fetch(
      `https://finnhub.io/api/v1/quote?symbol=AAPL&token=${apiKey}`
    )

    if (!response.ok) {
      const text = await response.text()
      return {
        success: false,
        status: response.status,
        error: `Finnhub API returned ${response.status}`,
        response: text.substring(0, 200),
        keyPreview: `${apiKey.substring(0, 4)}...${apiKey.substring(apiKey.length - 4)}`,
      }
    }

    const data = await response.json()

    if (!data || data.c === 0) {
      return {
        success: false,
        error: 'API returned empty data',
        keyPreview: `${apiKey.substring(0, 4)}...${apiKey.substring(apiKey.length - 4)}`,
      }
    }

    return {
      success: true,
      message: 'Finnhub API key is working!',
      testData: {
        symbol: 'AAPL',
        price: data.c,
        change: data.d,
        changePercent: data.dp,
      },
      keyPreview: `${apiKey.substring(0, 4)}...${apiKey.substring(apiKey.length - 4)}`,
      rateLimit: '60 calls/minute',
    }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    }
  }
}

async function testFmp(): Promise<Record<string, unknown>> {
  const apiKey = process.env.FMP_API_KEY

  if (!apiKey) {
    return {
      success: false,
      error: 'FMP_API_KEY is not set',
      help: 'Get an API key at https://financialmodelingprep.com/developer',
      note: 'FMP free tier has limited access since Sept 2025. Paid plan recommended.',
    }
  }

  try {
    const response = await fetch(
      `https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=${apiKey}`
    )

    if (!response.ok) {
      const text = await response.text()
      return {
        success: false,
        status: response.status,
        error: `FMP API returned ${response.status}`,
        response: text.substring(0, 300),
        keyPreview: `${apiKey.substring(0, 4)}...${apiKey.substring(apiKey.length - 4)}`,
        help: response.status === 403
          ? 'FMP free tier no longer supports this endpoint. A paid plan is required.'
          : 'Check your API key',
      }
    }

    const data = await response.json()

    if (!data || data.length === 0) {
      return {
        success: false,
        error: 'API returned empty data',
      }
    }

    return {
      success: true,
      message: 'FMP API key is working!',
      testData: {
        symbol: data[0].symbol,
        price: data[0].price,
        name: data[0].name,
      },
      keyPreview: `${apiKey.substring(0, 4)}...${apiKey.substring(apiKey.length - 4)}`,
      rateLimit: '250 calls/day (paid plan)',
    }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    }
  }
}
