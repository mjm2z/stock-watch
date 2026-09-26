'use client'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useOperator } from './OperatorSession'
export function ResearchControl({ asset }: { asset: string }) {
  const session = useOperator(),
    [data, setData] = useState<any>(),
    [error, setError] = useState(''),
    [notice, setNotice] = useState('')
  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/systems/control?asset=' + asset),
        d = await r.json()
      if (!r.ok) throw Error(d.error)
      setData(d)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unavailable')
    }
  }, [asset])
  useEffect(() => {
    void load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])
  async function command(body: any) {
    try {
      const r = await fetch('/api/systems/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }),
        d = await r.json()
      if (!r.ok) throw Error(d.error)
      setNotice('Saved. Policy changes require fresh authorization; owned exits remain managed.')
      await load()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Change failed')
    }
  }
  if (error) return <p className="sw-notice">{error}</p>
  if (!data) return <p className="sw-muted">Loading research controls…</p>
  const p = data.policy
  return (
    <section className="sw-panel space-y-4">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h2>Research & automation</h2>
          <p className="sw-muted">
            Nightly at 03:00 Eastern · 30-minute budget · Source-linked proposals
          </p>
        </div>
        <button
          className="sw-button"
          disabled={!session.authenticated}
          onClick={() => command({ action: 'policy', discoveryEnabled: !p.discovery_enabled })}
        >
          {p.discovery_enabled ? 'Pause discovery' : 'Resume discovery'}
        </button>
      </div>
      {asset === 'bitcoin' && (
        <div className="rounded border p-4 space-y-3">
          <h3 className="font-medium">
            Experimental Bitcoin paper trading · {p.enabled ? 'Policy enabled' : 'Entries paused'}
          </h3>
          <p className="text-sm">
            100 valid scenarios · At least {Math.round(p.threshold * 100)}% passing · 30 unique
            trades · 5 independent windows · ≤10% drawdown. Historical qualification does not
            require 30 days of forward observations.
          </p>
          <p className="sw-muted">
            ${p.pool} total cap · ${p.sleeve} per system · ${p.entry_cap} maximum entry including
            reserves · Orders wait for valid signals, fresh data and reconciled capital.
          </p>
          <div className="flex flex-wrap gap-3">
            <button
              disabled={!session.authenticated}
              className="sw-button"
              onClick={() => command({ action: 'policy', enabled: !p.enabled })}
            >
              {p.enabled ? 'Pause automatic entries' : 'Resume automatic entries'}
            </button>
            <label className="flex gap-2 items-center text-sm">
              Scenario threshold
              <select
                disabled={!session.authenticated}
                className="rounded border bg-background p-2"
                value={Math.round(p.threshold * 100)}
                onChange={(e) =>
                  command({ action: 'policy', threshold: Number(e.target.value) / 100 })
                }
              >
                {[80, 85, 90, 95, 100].map((n) => (
                  <option key={n} value={n}>
                    {n}%
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="sw-muted">
            {data.authorizations.length} authorized system(s) · {data.allocations.length} allocated
            system(s). Policy enabled does not mean an order is active.
          </p>
          {data.health
            .filter((h: any) => h.error)
            .map((h: any) => (
              <p className="sw-notice" key={h.key}>
                {h.key}: {h.error}
              </p>
            ))}
        </div>
      )}
      {notice && (
        <p role="status" className="sw-notice">
          {notice}
        </p>
      )}
      <details open>
        <summary className="font-medium cursor-pointer">Recent evaluations</summary>
        <div className="space-y-3 mt-3">
          {!data.trials.length && (
            <p className="sw-muted">
              The first nightly batch has not run yet. Existing historical studies remain available
              below.
            </p>
          )}
          {data.trials.map((t: any) => (
            <article className="border-t pt-3" key={t.id}>
              <div className="flex flex-wrap justify-between gap-2">
                <Link className="underline" href={`/systems/${t.version_id}?asset=${asset}`}>
                  {t.hypothesis}
                </Link>
                <span className="sw-badge">
                  {t.status} · {t.completed}/100
                </span>
              </div>
              <p className="sw-muted mt-1">
                {t.stage} · {t.result?.passing_scenarios ?? '—'} passing scenarios ·{' '}
                {t.result?.unique_trades ?? '—'} unique trades ·{' '}
                {t.result?.independent_windows ?? '—'} independent windows
              </p>
              <p className="text-sm mt-1">
                {t.error ||
                  t.result?.reasons?.join(' · ') ||
                  (t.result?.passed
                    ? 'Historical gate passed. Paper entries still require current data, capital and a valid signal.'
                    : 'No conclusion until evaluation completes.')}
              </p>
              <a className="sw-button mt-2" href={'/api/systems/evaluations/' + t.id}>
                Download scenario evidence
              </a>
              {t.expires_at && (
                <p className="sw-muted">
                  Evidence expires {new Date(t.expires_at).toLocaleString()} · Experimental
                  historical evidence
                </p>
              )}
            </article>
          ))}
        </div>
      </details>
      <details>
        <summary className="font-medium cursor-pointer">Morning digest & decisions</summary>
        <div className="mt-3 space-y-3">
          {data.events.map((e: any) => (
            <article key={e.id} className="border-t pt-2 text-sm">
              <p>
                {e.kind.replaceAll('_', ' ')} · {new Date(e.at).toLocaleString()}
              </p>
              <p className="sw-muted">
                {e.payload.reason || e.payload.reasons?.join(' · ') || JSON.stringify(e.payload)}
              </p>
            </article>
          ))}
        </div>
      </details>
      <details>
        <summary className="font-medium cursor-pointer">
          Web proposal inbox · {data.proposals.length}
        </summary>
        <p className="sw-muted mt-2">
          Research leads, not executable strategies. Publish reviewed rules before linking a
          proposal. External content never authorizes orders.
        </p>
        {data.proposals.map((q: any) => (
          <article key={q.id} className="border-t py-3 space-y-2 text-sm">
            <a href={q.url} rel="noopener noreferrer" target="_blank" className="underline">
              {q.title}
            </a>
            <p className="sw-muted">
              {q.published_at?.slice(0, 10)} · {q.state} · retrieved {q.retrieved_at?.slice(0, 10)}
            </p>
            <p>{q.excerpt}</p>
            <div className="flex gap-2 flex-wrap">
              <Link className="sw-button" href={`/systems?asset=${asset}&create=1`}>
                Create reviewed rules
              </Link>
              <button
                className="sw-button"
                disabled={!session.authenticated}
                onClick={() =>
                  command({
                    action: 'proposal',
                    id: q.id,
                    state: q.state === 'dismissed' ? 'inbox' : 'dismissed',
                  })
                }
              >
                {q.state === 'dismissed' ? 'Restore' : 'Dismiss'}
              </button>
            </div>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                const f = new FormData(e.currentTarget)
                void command({
                  action: 'proposal',
                  id: q.id,
                  state: 'reviewed',
                  version: f.get('version'),
                })
              }}
            >
              <input
                aria-label="Published version for proposal"
                name="version"
                placeholder="Published system version ID"
                className="min-w-0 flex-1 rounded border bg-background p-2"
                required
              />
              <button className="sw-button" disabled={!session.authenticated}>
                Link reviewed version
              </button>
            </form>
          </article>
        ))}
      </details>
    </section>
  )
}
