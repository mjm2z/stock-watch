import { render, screen, waitFor } from '@testing-library/react'
import { StockDataPreflight } from '@/components/StockDataPreflight'
const original = global.fetch
afterEach(() => {
  global.fetch = original
})
test('blocked data is explained and never enables a backtest', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      canPrepare: false,
      blockers: ['Raw daily bars are missing'],
      usableBars: 0,
      usableInstruments: 0,
      instruments: 503,
      missingSectors: 0,
      barsWithoutCalendar: 0,
      benchmarkBars: 0,
      coveredStart: null,
      coveredEnd: null,
      note: 'Input presence is not qualification.',
    }),
  })
  const ready = jest.fn()
  render(<StockDataPreflight start="2026-01-01" end="2026-01-06" onReady={ready} />)
  expect(await screen.findByText('Raw daily bars are missing')).toBeInTheDocument()
  expect(ready).not.toHaveBeenCalledWith(true)
  expect(screen.getByText('Input presence is not qualification.')).toBeInTheDocument()
})
test('failed or unavailable inspection cannot leave entry enabled', async () => {
  global.fetch = jest
    .fn()
    .mockResolvedValue({ ok: false, json: async () => ({ error: 'Database unavailable' }) })
  const ready = jest.fn()
  render(<StockDataPreflight start="2026-01-01" end="2026-01-06" onReady={ready} />)
  await waitFor(() => expect(screen.getByText('Database unavailable')).toBeInTheDocument())
  expect(ready).toHaveBeenCalledWith(false)
  expect(ready).not.toHaveBeenCalledWith(true)
})
