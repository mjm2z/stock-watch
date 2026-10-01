import { act, renderHook, waitFor } from '@testing-library/react'
import { clearChartHistoryCache, useChartHistory } from '@/components/useChartHistory'
import { DAY } from '@/lib/chart-window'
const now = Date.parse('2026-10-01T12:00:00Z')
const bar = (days: number) => ({
  date: new Date(now - days * DAY).toISOString(),
  open: 100,
  high: 110,
  low: 90,
  close: 100,
  volume: 10,
})
const reply = (data: ReturnType<typeof bar>[]) => ({
  ok: true,
  json: async () => ({ data, meta: { adjustment: 'all', resolution: '1Day' } }),
})
beforeEach(() => {
  clearChartHistoryCache()
  jest.spyOn(Date, 'now').mockReturnValue(now)
})
afterEach(() => jest.restoreAllMocks())
test('extension keeps existing bars during loading, merges older bars and stops retrying exhausted history', async () => {
  let complete!: (value: unknown) => void
  global.fetch = jest
    .fn()
    .mockResolvedValueOnce(reply([bar(20), bar(1)]))
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          complete = resolve
        })
    )
    .mockResolvedValue(reply([]))
  const { result } = renderHook(() =>
    useChartHistory('stocks', ['SPY'], '1M', { start: '', end: '' })
  )
  await waitFor(() => expect(result.current.data.SPY?.bars.length).toBe(2))
  act(() => result.current.onVisibleRange({ start: now - 60 * DAY, end: now - DAY }))
  await waitFor(() => expect(result.current.loading).toBe(true))
  expect(result.current.data.SPY.bars).toHaveLength(2)
  await act(async () => complete(reply([bar(50)])))
  await waitFor(() => expect(result.current.data.SPY.bars.length).toBe(3))
  expect(result.current.data.SPY.bars[0].at).toBe(bar(50).date)
  const url = new URL((global.fetch as jest.Mock).mock.calls[1][0], 'http://localhost')
  expect(Date.parse(url.searchParams.get('end')!)).toBe(now - 32 * DAY)
  act(() => result.current.onVisibleRange({ start: now - 120 * DAY, end: now - DAY }))
  await waitFor(() => expect(result.current.notice).toMatch(/No additional/))
  const calls = (global.fetch as jest.Mock).mock.calls.length
  act(() => result.current.onVisibleRange({ start: now - 240 * DAY, end: now - DAY }))
  expect(global.fetch).toHaveBeenCalledTimes(calls)
})
test('explicit custom interval does not expand and unmount aborts an outstanding fetch', async () => {
  let signal!: AbortSignal
  global.fetch = jest.fn().mockImplementation((_url, options) => {
    signal = options.signal
    return new Promise(() => {})
  })
  const { result, unmount } = renderHook(() =>
    useChartHistory('stocks', ['SPY'], 'CUSTOM', { start: '2026-09-01', end: '2026-09-30' })
  )
  act(() => result.current.onVisibleRange({ start: now - 300 * DAY, end: now }))
  expect(result.current.notice).toMatch(/Custom date boundaries/)
  unmount()
  expect(signal.aborted).toBe(true)
})
