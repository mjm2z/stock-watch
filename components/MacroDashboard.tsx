'use client'
import { useEffect, useState } from 'react'
import { PageHeader } from './PageHeader'
type Point = { date: string; value: string | null }
type Series = {
  id: string
  label: string
  publisher: string
  source_url: string
  metadata: { title?: string; seasonal_adjustment?: string; last_updated?: string; notes?: string }
  latest: { period: string; value: string | null; units: string } | null
  history: Point[]
}
type Snapshot = {
  configured: boolean
  healthy: boolean
  status: string
  stale: boolean
  updated_at: number | null
  series: Series[]
}
function number(value: string | null | undefined) {
  return value == null
    ? 'Unavailable'
    : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
}
export function MacroDashboard() {
  const [state, setState] = useState<Snapshot | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const r = await fetch('/api/macro', { cache: 'no-store', signal: controller.signal })
        if (!r.ok) throw Error()
        setState(await r.json())
      } catch {
        if (!controller.signal.aborted)
          setState((s) =>
            s
              ? { ...s, healthy: false, status: 'service_unavailable' }
              : {
                  configured: false,
                  healthy: false,
                  status: 'service_unavailable',
                  stale: false,
                  updated_at: null,
                  series: [],
                }
          )
      }
    }
    void load()
    const interval = setInterval(load, 60000)
    return () => {
      controller.abort()
      clearInterval(interval)
    }
  }, [])
  const message = !state
    ? 'Loading economic context…'
    : state.status === 'unconfigured'
      ? 'FRED API key has not been configured.'
      : state.status === 'service_unavailable'
        ? 'Macro service is unavailable.'
        : state.status === 'invalid_configuration'
          ? 'FRED configuration needs attention.'
          : state.status === 'checking'
            ? 'Collecting economic context…'
            : state.healthy
              ? 'Latest collected economic context.'
              : 'Updates unavailable or stale. Retained observations remain labelled with their dates.'
  return (
    <main className="space-y-5">
      <PageHeader
        title="Economic context"
        description="Inflation, employment, interest rates and growth · Shared context for stocks and crypto"
      />
      <div className="sw-panel">
        <p role="status">{message}</p>
        {state?.updated_at && (
          <p className="sw-muted mt-2">
            Collected {new Date(state.updated_at * 1000).toLocaleString()} · Scheduled every six
            hours
          </p>
        )}
        <p className="sw-muted mt-2">
          Read-only context. These revised observations do not drive trading or point-in-time
          backtests.
        </p>
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        {state?.series.map((series) => (
          <section key={series.id} className="sw-panel min-w-0">
            <h2 className="text-lg font-semibold">{series.label}</h2>
            <p className="text-3xl font-semibold tabular-nums mt-3">
              {number(series.latest?.value)}
            </p>
            <p className="sw-muted">{series.latest?.units || 'Observation unavailable'}</p>
            <p className="mt-2 text-sm">
              Observation period: {series.latest?.period || 'Unavailable'}
            </p>
            <p className="sw-muted mt-2">
              {series.publisher} via FRED · {series.metadata.seasonal_adjustment}
            </p>
            <p className="sw-muted">
              Source updated: {series.metadata.last_updated || 'Unavailable'}
            </p>
            <a
              className="text-primary inline-block mt-3"
              href={series.source_url}
              target="_blank"
              rel="noreferrer"
            >
              View source series ↗
            </a>
            <details className="mt-4">
              <summary>Recent observations and source notes</summary>
              <div className="max-h-64 overflow-y-auto mt-3">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className="text-left">Period</th>
                      <th className="text-right">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {series.history
                      .slice()
                      .reverse()
                      .map((row) => (
                        <tr key={row.date}>
                          <td>{row.date}</td>
                          <td className="text-right tabular-nums">{number(row.value)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
                <p className="sw-muted mt-3 whitespace-pre-wrap">{series.metadata.notes}</p>
              </div>
            </details>
          </section>
        ))}
      </div>
      <footer className="sw-muted text-sm">
        This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank
        of St. Louis.{' '}
        <a
          className="text-primary"
          href="https://fred.stlouisfed.org/docs/api/terms_of_use.html"
          target="_blank"
          rel="noreferrer"
        >
          FRED API terms
        </a>
        . Using this integration is subject to those terms. Data remains outside AI summaries.
        ALFRED vintage/backtest integration is deferred.
      </footer>
    </main>
  )
}
