'use client'
import { useEffect, useRef, useState } from 'react'
type Snapshot = {
  price: number | null
  fresh: boolean
  status: string
  sourceAt: string | null
  receivedAt: number | null
  heartbeatAt: number
}
export function BitcoinLivePrice() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [direction, setDirection] = useState('—')
  const prior = useRef<number | null>(null)
  useEffect(() => {
    const events = new EventSource('/api/crypto/live?stream=1')
    events.onmessage = (event) => {
      try {
        const next: Snapshot = JSON.parse(event.data)
        if (next.price !== null && (!Number.isFinite(next.price) || next.price <= 0)) return
        if (next.price !== prior.current) {
          setDirection(
            prior.current === null || next.price === null
              ? '—'
              : next.price > prior.current
                ? '↑'
                : '↓'
          )
          prior.current = next.price
        }
        setSnapshot(next)
      } catch {
        /* retain last observation */
      }
    }
    events.onerror = () =>
      setSnapshot((old) => ({
        price: null,
        sourceAt: null,
        receivedAt: null,
        heartbeatAt: 0,
        ...old,
        fresh: false,
        status: 'Reconnecting',
      }))
    const freshness = setInterval(
      () =>
        setSnapshot((old) => {
          if (!old?.fresh) return old
          return Date.now() - Date.parse(old.sourceAt || '') > 5000 ||
            Date.now() - old.heartbeatAt > 3000
            ? { ...old, fresh: false, status: 'Stale' }
            : old
        }),
      250
    )
    return () => {
      events.close()
      clearInterval(freshness)
    }
  }, [])
  return (
    <section aria-label="Bitcoin live price" className="min-h-40 rounded-xl border p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Live Price</h2>
        <span className={snapshot?.fresh ? 'text-emerald-600' : 'text-amber-600'}>
          {snapshot?.status || 'Connecting'}
        </span>
      </div>
      <p className="my-2 font-mono text-3xl tabular-nums sm:text-4xl" aria-live="off">
        {snapshot?.price != null
          ? snapshot.price.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
          : '—'}
        <span aria-hidden="true" className="ml-3 inline-block w-8 text-xl">
          {direction}
        </span>
      </p>
      <p className="text-sm text-muted-foreground">
        BTC/USD · Coinbase · Last update{' '}
        {snapshot?.sourceAt ? new Date(snapshot.sourceAt).toLocaleTimeString() : 'unavailable'}
      </p>
      <p className="text-xs text-muted-foreground">
        Observed price. Alpaca executable quotes and historical candles are separate.
      </p>
    </section>
  )
}
