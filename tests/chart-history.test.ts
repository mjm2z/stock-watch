import { BoundedCache } from '@/lib/bounded-cache'
import { DAY, extendWindow, initialWindow, mergeBars, windowResolution } from '@/lib/chart-window'
test('disposable caches enforce byte/count bounds, LRU and expiry', () => {
  jest.useFakeTimers()
  const cache = new BoundedCache<string>(30, 2)
  cache.set('a', 'first', 100)
  cache.set('b', 'second', 100)
  expect(cache.get('a')).toBe('first')
  cache.set('c', 'third', 100)
  expect(cache.get('b')).toBeUndefined()
  cache.set('oversized', 'x'.repeat(31))
  expect(cache.get('oversized')).toBeUndefined()
  jest.advanceTimersByTime(101)
  expect(cache.stats()).toEqual({ bytes: 0, entries: 0 })
  jest.useRealTimers()
})
test('history expansion stops at asset limits and chooses bounded resolutions', () => {
  const now = Date.parse('2026-10-01T00:00:00Z')
  const initial = initialWindow('stocks', '1D', { start: '', end: '' }, now)
  expect(windowResolution('stocks', initial, '1D')).toBe('5Min')
  const expanded = extendWindow(initial, { start: now - 100 * DAY, end: now + DAY }, 'stocks', now)
  expect(expanded.end).toBe(now)
  expect(windowResolution('stocks', expanded, '1D')).toBe('1Hour')
  const crypto = extendWindow(initial, { start: 0, end: now }, 'bitcoin', now)
  expect(crypto.start).toBe(now - 3660 * DAY)
  expect(windowResolution('bitcoin', crypto, '1M')).toBe('1Day')
})
test('history merging sorts and replaces duplicate timestamps rather than multiplying bars', () => {
  expect(
    mergeBars(
      [{ at: '2026-02-01', close: 2 }],
      [
        { at: '2026-01-01', close: 1 },
        { at: '2026-02-01', close: 3 },
      ]
    )
  ).toEqual([
    { at: '2026-01-01', close: 1 },
    { at: '2026-02-01', close: 3 },
  ])
})
