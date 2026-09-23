import { getAlpacaQuotes, getAlpacaHistory, snapshotQuote } from '@/lib/alpaca-market-data'
import { serverCache } from '@/lib/cache'

const bar = { t: '2026-09-17T04:00:00Z', o: 100, h: 110, l: 99, c: 106, v: 1234 }
const snapshot = { latestTrade: { p: 107, t: '2026-09-17T16:00:00Z' }, dailyBar: bar, prevDailyBar: { ...bar, c: 100 } }
const originalFetch = global.fetch
const originalKey = process.env.ALPACA_API_KEY_ID
const originalSecret = process.env.ALPACA_API_SECRET_KEY

beforeEach(() => {
  serverCache.clear()
  process.env.ALPACA_API_KEY_ID = 'test-key'
  process.env.ALPACA_API_SECRET_KEY = 'test-secret'
})
afterEach(() => {
  global.fetch = originalFetch
  if (originalKey === undefined) delete process.env.ALPACA_API_KEY_ID
  else process.env.ALPACA_API_KEY_ID = originalKey
  if (originalSecret === undefined) delete process.env.ALPACA_API_SECRET_KEY
  else process.env.ALPACA_API_SECRET_KEY = originalSecret
})

test('uses the exchange observation time and previous close, not request time', () => {
  expect(snapshotQuote('AAPL', snapshot)).toMatchObject({ price: 107, previousClose: 100, change: 7, changePercent: 7.000000000000001, timestamp: '2026-09-17T16:00:00Z' })
  expect(snapshotQuote('AAPL', {})).toBeNull()
  expect(snapshotQuote('AAPL', { ...snapshot, prevDailyBar: { ...bar, c: 0 } })).toBeNull()
})

test('uses only the data endpoint and IEX feed, caches a batch, and reports missing symbols by omission', async () => {
  const request = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ AAPL: snapshot }) })
  global.fetch = request
  const result = await getAlpacaQuotes(['aapl', 'MSFT'])
  expect(result.map(quote => quote.ticker)).toEqual(['AAPL'])
  expect(request.mock.calls[0][0]).toBe('https://data.alpaca.markets/v2/stocks/snapshots?symbols=AAPL%2CMSFT&feed=iex')
  expect(request.mock.calls[0][1].headers['APCA-API-KEY-ID']).toBe('test-key')
  await getAlpacaQuotes(['MSFT', 'AAPL'])
  expect(request).toHaveBeenCalledTimes(1)
  await expect(getAlpacaQuotes(['../../orders'])).rejects.toThrow('Invalid stock symbol')
})

test('does not cache provider failures or fabricate prices', async () => {
  const request = jest.fn().mockResolvedValueOnce({ ok: false, status: 403 })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ AAPL: snapshot }) })
  global.fetch = request
  await expect(getAlpacaQuotes(['AAPL'])).rejects.toThrow('(403)')
  expect(await getAlpacaQuotes(['AAPL'])).toHaveLength(1)
})

test('retains distinct intraday timestamps and follows pagination', async () => {
  global.fetch = jest.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ bars: [{ ...bar, t: '2026-09-16T15:00:00Z' }], next_page_token: 'next' }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ bars: [{ ...bar, t: '2026-09-17T15:00:00Z' }, { ...bar, t: '2026-09-17T15:05:00Z' }] }) })
  expect((await getAlpacaHistory('AAPL', '1D')).map(price => price.date)).toEqual(['2026-09-17T15:00:00Z', '2026-09-17T15:05:00Z'])
})
