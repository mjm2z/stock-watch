'use client'
import { useLiveBitcoin } from '@/lib/live-bitcoin'
export function BitcoinLivePrice() {
  const snapshot = useLiveBitcoin()
  return (
    <section
      aria-label="Bitcoin live price from Coinbase"
      title="Coinbase observed price; historical chart and executable Alpaca quotes are separate."
      className="sw-live-badge"
    >
      <span className="text-xs font-semibold text-muted-foreground">BTC/USD</span>
      <p className="font-mono text-lg tabular-nums" aria-live="off">
        {snapshot?.price != null
          ? snapshot.price.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
          : '—'}
      </p>
      <span className={snapshot?.fresh ? 'sw-live-status' : 'sw-stale-status'}>
        <span aria-hidden="true">●</span>{' '}
        {snapshot?.fresh ? 'Live' : snapshot?.status || 'Connecting'}
      </span>
    </section>
  )
}
