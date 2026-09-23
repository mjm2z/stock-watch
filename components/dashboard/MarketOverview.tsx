'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import type { Quote } from '@/types'
import { formatCurrency, formatPercent } from '@/lib/utils'

const tickers = ['SPY', 'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL']
const dateFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  month: 'long',
  day: 'numeric',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
})

export function MarketOverview() {
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [retry, setRetry] = useState(0)
  const [provider, setProvider] = useState('Market data')
  const [checkedAt, setCheckedAt] = useState<number | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let inFlight = false
    async function refresh() {
      if (inFlight || document.hidden) return
      inFlight = true
      try {
        const response = await fetch('/api/watchlist/prices', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tickers }),
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.error || 'Market data unavailable')
        if (!controller.signal.aborted) {
          setQuotes(result.prices)
          setProvider(result.provider ?? 'Market data')
          setCheckedAt(Date.now())
          setError(null)
        }
      } catch (error) {
        if (!controller.signal.aborted)
          setError(error instanceof Error ? error.message : 'Market data unavailable')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
        inFlight = false
      }
    }
    void refresh()
    const timer = setInterval(() => {
      void refresh()
    }, 30000)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      controller.abort()
      clearInterval(timer)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [retry])
  return (
    <section aria-label="Market prices" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Market prices</h2>
        <p className="text-xs text-muted-foreground">
          {provider} · refreshes every 30 seconds · Eastern time
        </p>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-loss">
          Prices could not refresh: {error}. Any displayed prices are from the last successful
          update.{' '}
          <button onClick={() => setRetry((n) => n + 1)} className="min-h-11 underline">
            Retry
          </button>
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-6">
        {tickers.map((ticker) => {
          const quote = quotes[ticker]
          const old =
            quote?.timestamp && checkedAt && checkedAt - Date.parse(quote.timestamp) > 300000
          return (
            <Link
              key={ticker}
              href={`/stock/${ticker}`}
              className="rounded-xl border bg-card p-4 shadow-sm hover:border-primary"
            >
              <p className="font-medium">{ticker}</p>
              <p className="mt-2 text-2xl font-semibold">
                {quote ? formatCurrency(quote.price) : loading ? 'Loading…' : 'Unavailable'}
              </p>
              {quote ? (
                <p className={quote.changePercent >= 0 ? 'text-sm text-gain' : 'text-sm text-loss'}>
                  {formatPercent(quote.changePercent)}
                </p>
              ) : null}
              {quote?.timestamp ? (
                <p className="mt-2 text-xs text-muted-foreground">
                  {old ? 'Last available · ' : 'As of '}
                  {dateFormat.format(new Date(quote.timestamp))}
                </p>
              ) : null}
            </Link>
          )
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        IEX prices cover one exchange. Outside trading hours, the latest available trade remains
        visible.
      </p>
    </section>
  )
}
