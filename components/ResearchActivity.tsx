'use client'
import Link from 'next/link'
import { useEffect, useState } from 'react'
export const pct = (v: unknown) =>
  typeof v === 'number' && Number.isFinite(v) ? `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%` : '—'
export const rate = (v: unknown) =>
  typeof v === 'number' && Number.isFinite(v) ? (v * 100).toFixed(2) + '%' : '—'
export const money = (v: unknown) =>
  typeof v === 'number' && Number.isFinite(v)
    ? `${v < 0 ? '−' : ''}$${Math.abs(v).toFixed(2)}`
    : '—'
export const outcome = (v: unknown) =>
  typeof v !== 'number' ? 'No result' : v > 0 ? 'Gain' : v < 0 ? 'Loss' : 'Flat'
export const color = (v: unknown) =>
  typeof v !== 'number'
    ? 'text-muted-foreground'
    : v > 0
      ? 'text-gain'
      : v < 0
        ? 'text-loss'
        : 'text-muted-foreground'
export function ResearchActivity({
  asset,
  mode,
  version,
}: {
  asset: string
  mode: 'systems' | 'backtesting'
  version?: string
}) {
  const [data, setData] = useState<any>({ rows: [], total: 0 }),
    [page, setPage] = useState(0),
    [status, setStatus] = useState(''),
    [error, setError] = useState('')
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    async function load() {
      try {
        const p = new URLSearchParams({
          asset,
          mode,
          page: String(page),
          status,
          ...(version ? { version } : {}),
        })
        const r = await fetch('/api/systems/activity?' + p, { signal: controller.signal })
        const d = await r.json()
        if (!r.ok) throw Error(d.error)
        if (active) {
          setData(d)
          setError('')
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : 'Activity unavailable')
      }
    }
    void load()
    const t = setInterval(load, 10000)
    return () => {
      active = false
      controller.abort()
      clearInterval(t)
    }
  }, [asset, mode, page, status, version])
  return (
    <section className="sw-panel space-y-4">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h2>{mode === 'backtesting' ? 'Backtest activity & results' : 'System activity'}</h2>
          <p className="sw-muted">Execution status and financial outcome are separate.</p>
        </div>
        <label className="sw-field">
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value)
              setPage(0)
            }}
          >
            {['', 'queued', 'running', 'succeeded', 'failed', 'canceled'].map((s) => (
              <option key={s} value={s}>
                {s || 'All statuses'}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <p role="alert" className="sw-notice">
          {error}
        </p>
      )}
      {!data.rows.length && !error && (
        <p className="sw-muted">
          No matching requests. Published systems and backtests will appear here.
        </p>
      )}
      {data.rows.map((r: any) => (
        <article key={r.id} className="border-t py-4 space-y-3">
          <div className="flex flex-wrap justify-between gap-3">
            <div>
              <Link
                className="font-medium underline"
                href={
                  r.version ? `/systems/${r.version}?asset=${asset}` : `/systems?asset=${asset}`
                }
              >
                {r.name}
              </Link>
              <p className="sw-muted mt-1">
                {r.kind.replaceAll('_', ' ')} · {r.status} · {r.stage}{' '}
                {r.version && `· ${r.version.slice(0, 8)}`}
              </p>
            </div>
            {r.kind === 'backtest' && (
              <Link className="sw-button" href={`/systems/runs/${r.id}?asset=${asset}`}>
                View run
              </Link>
            )}
          </div>
          <div className="grid grid-cols-2 xl:grid-cols-5 gap-4 text-sm">
            <div>
              <p className="sw-muted">Interval / timeframe</p>
              <p>{r.start ? `${r.start.slice(0, 10)} → ${r.end?.slice(0, 10)}` : '—'}</p>
              <p>
                {r.timeframe || '—'} · {r.costMultiplier}× modeled costs
              </p>
            </div>
            <div>
              <p className="sw-muted">Net return</p>
              <p className={color(r.summary?.netReturn)}>
                {pct(r.summary?.netReturn)} · {outcome(r.summary?.netReturn)}
              </p>
            </div>
            <div>
              <p className="sw-muted">Maximum drawdown</p>
              <p className="text-loss">{pct(r.summary?.drawdown)}</p>
            </div>
            <div>
              <p className="sw-muted">Closed-trade win rate</p>
              <p>{rate(r.summary?.winRate)}</p>
              <p className="sw-muted">{r.summary?.trades ?? '—'} closed trades</p>
            </div>
            <div>
              <p className="sw-muted">Timing</p>
              <p>{new Date(r.createdAt).toLocaleString()}</p>
              <p className="sw-muted">
                {r.startedAt
                  ? `${Math.max(0, Math.round(((r.finishedAt ? Date.parse(r.finishedAt) : Date.now()) - Date.parse(r.startedAt)) / 1000))}s elapsed`
                  : 'Waiting to start'}
              </p>
            </div>
          </div>
          {r.error && (
            <p role="status" className="sw-notice sw-error">
              {r.error}
            </p>
          )}
          {r.summary && (
            <details className="text-sm">
              <summary>Benchmarks & evidence</summary>
              <div className="mt-2 space-y-1">
                {Object.entries(r.summary.benchmarks || {}).map(([name, value]) => (
                  <p key={name}>
                    {name}: {pct(value)} · strategy difference{' '}
                    {typeof value === 'number' && typeof r.summary.netReturn === 'number'
                      ? `${((r.summary.netReturn - value) * 100).toFixed(2)} percentage points`
                      : '—'}
                  </p>
                ))}
                <p className="sw-muted">{r.summary.warnings?.join(' · ')}</p>
                <p className="sw-muted">
                  Holdout: {r.summary.holdout || 'Not recorded'} · Recorded dataset trials:{' '}
                  {r.summary.trialCount ?? 'Unknown'}
                </p>
              </div>
            </details>
          )}
        </article>
      ))}
      <div className="flex gap-3 items-center">
        <button className="sw-button" disabled={!page} onClick={() => setPage(page - 1)}>
          Previous
        </button>
        <span className="sw-muted">
          Page {page + 1} · {data.total} requests
        </span>
        <button
          className="sw-button"
          disabled={(page + 1) * 20 >= data.total}
          onClick={() => setPage(page + 1)}
        >
          Next
        </button>
      </div>
    </section>
  )
}
