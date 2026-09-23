// Server-side, read-only market data. Broker order endpoints are never used here.
import { serverCache } from '@/lib/cache'
import type { Quote, PriceData } from '@/types'

interface Bar { t: string; o: number; h: number; l: number; c: number; v: number }
interface Snapshot { latestTrade?: { p: number; t: string }; dailyBar?: Bar; prevDailyBar?: Bar }

export function hasAlpacaData(): boolean {
  return Boolean(process.env.ALPACA_API_KEY_ID && process.env.ALPACA_API_SECRET_KEY)
}

function symbol(value: string): string {
  const normalized = value.trim().toUpperCase()
  if (!/^[A-Z][A-Z0-9.-]{0,14}$/.test(normalized)) throw new Error('Invalid stock symbol')
  return normalized
}

async function dataFetch<T>(path: string, params: Record<string, string>): Promise<T> {
  if (!hasAlpacaData()) throw new Error('Alpaca market data is not configured')
  const response = await fetch(`https://data.alpaca.markets/v2/stocks/${path}?${new URLSearchParams(params)}`, {
    headers: {
      'APCA-API-KEY-ID': process.env.ALPACA_API_KEY_ID!,
      'APCA-API-SECRET-KEY': process.env.ALPACA_API_SECRET_KEY!,
    },
    signal: AbortSignal.timeout(15000),
    cache: 'no-store',
    redirect: 'error',
  })
  if (!response.ok) throw new Error(`Alpaca market data request failed (${response.status})`)
  return response.json() as Promise<T>
}

export function snapshotQuote(ticker: string, snapshot: Snapshot): Quote | null {
  const daily = snapshot.dailyBar
  const previous = snapshot.prevDailyBar
  const price = snapshot.latestTrade?.p ?? daily?.c
  const timestamp = snapshot.latestTrade?.t ?? daily?.t
  if (!daily || !previous || !price || !timestamp || previous.c <= 0 ||
      !Number.isFinite(Date.parse(timestamp)) ||
      ![price, daily.o, daily.h, daily.l, daily.v, previous.c].every(Number.isFinite)) return null
  const change = price - previous.c
  return { ticker, price, open: daily.o, high: daily.h, low: daily.l,
    previousClose: previous.c, volume: daily.v, change,
    changePercent: change / previous.c * 100, timestamp }
}

export async function getAlpacaQuotes(tickers: string[]): Promise<Quote[]> {
  const symbols = [...new Set(tickers.map(symbol))].sort()
  if (symbols.length === 0) return []
  if (symbols.length > 50) throw new Error('At most 50 stock symbols per request')
  const key = `alpaca:iex:quotes:${symbols.join(',')}`
  const cached = serverCache.get<Quote[]>(key)
  if (cached) return cached
  const snapshots = await dataFetch<Record<string, Snapshot>>('snapshots', { symbols: symbols.join(','), feed: 'iex' })
  const quotes = symbols.flatMap(ticker => {
    const quote = snapshots[ticker] ? snapshotQuote(ticker, snapshots[ticker]) : null
    return quote ? [quote] : []
  })
  if (quotes.length) serverCache.set(key, quotes, 15000)
  return quotes
}

export async function getAlpacaHistory(ticker: string, range: string): Promise<PriceData[]> {
  const settings: Record<string, [number, string]> = {
    '1D': [4, '5Min'], '1W': [7, '1Hour'], '1M': [32, '1Day'],
    '3M': [95, '1Day'], '1Y': [370, '1Day'], '5Y': [1830, '1Day'],
  }
  if (!settings[range]) throw new Error('Invalid history range')
  const tickerSymbol = symbol(ticker)
  const key = `alpaca:iex:history:${tickerSymbol}:${range}`
  const cached = serverCache.get<PriceData[]>(key)
  if (cached) return cached
  const [days, timeframe] = settings[range]
  const params: Record<string, string> = {
    timeframe, start: new Date(Date.now() - days * 86400000).toISOString(),
    end: new Date().toISOString(), adjustment: 'all', feed: 'iex', sort: 'asc', limit: '10000',
  }
  const bars: Bar[] = []
  const tokens = new Set<string>()
  for (;;) {
    const result = await dataFetch<{ bars: Bar[] | null; next_page_token?: string | null }>(`${tickerSymbol}/bars`, params)
    bars.push(...(result.bars ?? []))
    if (!result.next_page_token) break
    if (tokens.has(result.next_page_token) || tokens.size >= 10) throw new Error('Incomplete Alpaca history response')
    tokens.add(result.next_page_token)
    params.page_token = result.next_page_token
  }
  const marketDate = (timestamp: string) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date(timestamp))
  const latestDate = bars.length ? marketDate(bars[bars.length - 1].t) : null
  const prices = bars.filter(bar => range !== '1D' || marketDate(bar.t) === latestDate).map(bar => ({
    date: bar.t, open: bar.o, high: bar.h, low: bar.l, close: bar.c, volume: bar.v,
  }))
  if (prices.length) serverCache.set(key, prices, 60000)
  return prices
}
