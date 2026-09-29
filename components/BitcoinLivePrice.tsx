'use client'
import { useLiveBitcoin } from '@/lib/live-bitcoin'
export function BitcoinLivePrice() {
  const snapshot = useLiveBitcoin()
  const direction = snapshot?.direction || '—'
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
