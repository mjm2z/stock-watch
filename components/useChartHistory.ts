'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BoundedCache } from '@/lib/bounded-cache'
import {
  extendWindow,
  initialWindow,
  mergeBars,
  windowResolution,
  type HistoryWindow,
} from '@/lib/chart-window'
import type { ChartBar } from './MarketChart'
export type ChartHistory = {
  bars: ChartBar[]
  loading: boolean
  error?: string
  partial?: boolean
  resolution?: string
  status?: string
  gaps?: number
  stale?: boolean
  refreshing?: boolean
}
const cache = new BoundedCache<ChartHistory>(16 * 1024 * 1024, 32)
type Pending = { promise: Promise<ChartHistory>; controller: AbortController; users: number }
const pending = new Map<string, Pending>()
export function clearChartHistoryCache() {
  cache.clear()
}
async function request(url: string, signal: AbortSignal): Promise<ChartHistory> {
  const hit = cache.get(url)
  if (hit) return hit
  let entry = pending.get(url)
  if (entry?.controller.signal.aborted) entry = undefined
  if (!entry) {
    if (pending.size >= 10) throw Error('History is busy; retry shortly')
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 20000)
    const task = (async () => {
      const response = await fetch(url, { signal: controller.signal })
      const body = await response.json()
      if (!response.ok) throw Error(body.error || 'History unavailable')
      if (body.meta && body.meta.adjustment !== 'all')
        throw Error('Adjusted history is unavailable')
      if (['failed', 'canceled'].includes(body.status))
        throw Error(body.error || 'History collection failed')
      const waiting = body.status && body.status !== 'ready'
      const result: ChartHistory = {
        ...body,
        bars:
          body.bars ||
          (body.data || []).map((b: ChartBar & { date: string }) => ({ ...b, at: b.date })),
        loading: Boolean(waiting),
        resolution: body.meta?.resolution || body.resolution,
        partial: body.meta?.partial || body.partial,
      }
      if (!waiting) cache.set(url, result, 60000)
      return result
    })().finally(() => {
      clearTimeout(timeout)
      if (pending.get(url)?.controller === controller) pending.delete(url)
    })
    entry = { promise: task, controller, users: 0 }
    pending.set(url, entry)
  }
  const active = entry
  active.users++
  return new Promise<ChartHistory>((resolve, reject) => {
    let done = false
    const finish = (error?: unknown, value?: ChartHistory) => {
      if (done) return
      done = true
      signal.removeEventListener('abort', abort)
      active.users--
      if (!active.users) active.controller.abort()
      if (error) reject(error)
      else resolve(value!)
    }
    const abort = () => finish(new Error('History request canceled'))
    signal.addEventListener('abort', abort, { once: true })
    active.promise.then(
      (value) => finish(undefined, value),
      (error) => finish(error)
    )
    if (signal.aborted) abort()
  })
}

export function useChartHistory(
  asset: 'stocks' | 'bitcoin',
  symbols: string[],
  range: string,
  custom: { start: string; end: string }
) {
  const [clock, setClock] = useState(Date.now())
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 60000)
    return () => clearInterval(timer)
  }, [])
  const identity = JSON.stringify([asset, symbols, range, custom])
  const initial = useMemo(() => initialWindow(asset, range, custom, clock), [identity, clock]) // eslint-disable-line react-hooks/exhaustive-deps
  const [extension, setExtension] = useState<{ identity: string; window: HistoryWindow }>()
  const window = extension?.identity === identity ? extension.window : initial
  const resolution = windowResolution(asset, window, range)
  const [data, setData] = useState<Record<string, ChartHistory>>({})
  const [notice, setNotice] = useState('')
  const [navigated, setNavigated] = useState('')
  const [retry, setRetry] = useState(0)
  const [resetToken, setResetToken] = useState(0)
  const loaded = useRef<{
    identity: string
    window: HistoryWindow
    resolution: string
    data: Record<string, ChartHistory>
  }>()
  const limit = useRef<{ identity: string; start?: number; end?: number }>({ identity: '' })
  const baseline = useRef<{ identity: string; prices: Record<string, number> }>({
    identity: '',
    prices: {},
  })
  useEffect(() => {
    if (!symbols.length || !Number.isFinite(window.start) || !Number.isFinite(window.end)) {
      setData({})
      return
    }
    const controller = new AbortController()
    let canceled = false
    let timer: ReturnType<typeof setTimeout>
    const old = loaded.current
    const initialSession =
      asset === 'stocks' && range.toUpperCase() === '1D' && extension?.identity !== identity
    const same = old?.identity === identity && old.resolution === resolution && !initialSession
    const interval =
      same && window.start < old.window.start && window.end === old.window.end
        ? { start: window.start, end: old.window.start }
        : same && window.end > old.window.end && window.start === old.window.start
          ? { start: old.window.end, end: window.end }
          : window
    setNotice('')
    setData((previous) =>
      Object.fromEntries(
        symbols.map((s) => [
          s,
          { ...(old?.identity === identity ? previous[s] : { bars: [] }), loading: true },
        ])
      )
    )
    let retried = false
    async function load() {
      const entries = await Promise.all(
        symbols.map(async (symbol) => {
          try {
            const query = new URLSearchParams({
              range: initialSession ? '1D' : asset === 'stocks' ? 'CUSTOM' : 'custom',
              start: new Date(interval.start).toISOString(),
              end: new Date(interval.end).toISOString(),
              timeframe: resolution,
              adjustment: 'all',
            })
            if (asset === 'bitcoin' && retry > 0 && !retried) query.set('retry', '1')
            const url =
              asset === 'stocks'
                ? `/api/stock/${encodeURIComponent(symbol)}/history?${query}`
                : `/api/crypto/market/history?${query}`
            const next = await request(url, controller.signal)
            const bars = (
              same ? mergeBars(old.data[symbol]?.bars || [], next.bars) : next.bars
            ).filter((b) => Date.parse(b.at) >= window.start && Date.parse(b.at) < window.end)
            return [
              symbol,
              {
                ...next,
                bars,
                partial: Boolean(next.partial || (same && old.data[symbol]?.partial)),
              },
            ] as const
          } catch (error) {
            return [
              symbol,
              {
                bars: old?.identity === identity ? old.data[symbol]?.bars || [] : [],
                loading: false,
                error: error instanceof Error ? error.message : 'History unavailable',
              },
            ] as const
          }
        })
      )
      retried = true
      if (canceled) return
      const result = Object.fromEntries(entries)
      const waiting = entries.some(([, v]) => v.loading)
      setData((previous) =>
        Object.fromEntries(
          entries.map(([s, v]) => [s, v.loading ? { ...v, bars: previous[s]?.bars || [] } : v])
        )
      )
      if (waiting) {
        timer = setTimeout(load, 2000)
        return
      }
      if (!entries.some(([, v]) => v.error)) {
        const priorCount = old && Object.values(old.data).reduce((n, v) => n + v.bars.length, 0)
        const nextCount = entries.reduce((n, [, v]) => n + v.bars.length, 0)
        if (same && nextCount === priorCount) {
          limit.current = {
            identity,
            start: window.start < old.window.start ? old.window.start : undefined,
            end: window.end > old.window.end ? old.window.end : undefined,
          }
          setNotice('No additional history available')
        }
        const starts = entries.flatMap(([, v]) => (v.bars.length ? [Date.parse(v.bars[0].at)] : []))
        const covered =
          initialSession && starts.length ? { ...window, start: Math.min(...starts) } : window
        loaded.current = { identity, window: covered, resolution, data: result }
      }
    }
    void load()
    return () => {
      canceled = true
      controller.abort()
      clearTimeout(timer)
    }
  }, [identity, window.start, window.end, resolution, retry]) // eslint-disable-line react-hooks/exhaustive-deps
  const loading = Object.values(data).some((v) => v.loading)
  const onVisibleRange = useCallback(
    (visible: HistoryWindow) => {
      setNavigated(identity)
      if (range.toUpperCase() === 'CUSTOM') {
        setNotice('Custom date boundaries · choose another range to expand')
        return
      }
      if (loading || Object.values(data).some((v) => v.error)) return
      const current = loaded.current?.identity === identity ? loaded.current.window : window
      const next = extendWindow(current, visible, asset, Date.now())
      if (limit.current.identity === identity) {
        if (limit.current.start !== undefined) next.start = window.start
        if (limit.current.end !== undefined) next.end = window.end
      }
      if (next.start !== current.start || next.end !== current.end)
        setExtension({ identity, window: next })
      else if (visible.start < window.start) setNotice('No earlier history available')
    },
    [range, loading, data, window, asset, identity]
  )
  function reset() {
    loaded.current = undefined
    limit.current = { identity: '' }
    baseline.current = { identity: '', prices: {} }
    setExtension(undefined)
    setNavigated('')
    setNotice('')
    setRetry((n) => n + 1)
    setResetToken((n) => n + 1)
  }
  return {
    data,
    loading,
    notice,
    onVisibleRange,
    reset,
    resetToken,
    customView: navigated === identity,
    baseline,
    identity,
    retry: () => setRetry((n) => n + 1),
  }
}
