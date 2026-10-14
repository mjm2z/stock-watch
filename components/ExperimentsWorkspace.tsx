'use client'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { useOperator } from './OperatorSession'

type Batch = {
  id: string
  revision: string
  status: string
  equity: string
  expires: string
  risk_reason: string | null
  plan: {
    versions: {
      family: string
      universe: string[]
      holding_minutes: number
      stop: string
      take: string
      trend_fast?: number
      breakout_period?: number
      rsi_entry?: number
    }[]
  }
}
type Instance = {
  id: string
  batch_id: string
  family: string
  budget: string
  cash: string
  state: string
  reason: string | null
  last_decision: string | null
}
type Data = {
  context: {
    id: string
    source: string
    symbol: string | null
    title: string
    url: string
    published: string
    observed: string
  }[]
  proposals: { id: string; family: string; variant: number; week: string }[]
  batches: Batch[]
  instances: Instance[]
  health: { component: string; at: string; error: string | null }[]
  commands: { id: string; action: string; status: string; result_json: string | null }[]
  research: { id: string; status: string; result_json: string | null; error: string | null }[]
}
type Decision = {
  id: string
  symbol: string
  cutoff: string
  outcome: string
  reason: string
  evidence: {
    conditions?: { left: number; op: string; right: number }[]
    bars: number[]
    news?: unknown[]
  }
}
type Detail = {
  gaps: { start: string; end: string; reason: string }[]
  decisions: Decision[]
  next: string | null
  positions: { symbol: string; quantity: string; cost: string; exit_due: string | null }[]
  orders: {
    id: string
    symbol: string
    side: string
    status: string
    filled_qty: string
    error: string | null
  }[]
}
const human = (value: string | null) => value?.replaceAll('_', ' ') || '—'
function rules(version: Batch['plan']['versions'][number]) {
  if (version.family === 'trend')
    return `Enter when EMA${version.trend_fast || 20} is above EMA50 and price is above EMA${version.trend_fast || 20}. Exit below EMA${version.trend_fast || 20}.`
  if (version.family === 'reversal')
    return `Enter when RSI14 crosses above ${version.rsi_entry || 35} and price is above EMA50. Exit at RSI55 or below EMA50.`
  if (version.family === 'control')
    return 'One daily entry at 10:05 ET, only within five minutes of that time. Hold at most 15 minutes.'
  return (
    `Enter above the previous ${version.breakout_period || 20} bars’ high. Exit below the previous 10 bars’ low.` +
    (version.family === 'news_breakout'
      ? ' Requires symbol-linked news published and first seen within one hour.'
      : '')
  )
}
const amount = (value: string) =>
  Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
const when = (value: string | null) => (value ? new Date(value).toLocaleString() : 'Not yet')

export function ExperimentsWorkspace({ asset }: { asset: 'stocks' | 'bitcoin' }) {
  const session = useOperator(),
    [data, setData] = useState<Data | null>(null),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false),
    [selected, setSelected] = useState(''),
    [detail, setDetail] = useState<Detail | null>(null)
  const endpoint = '/api/systems/experiments?asset=' + asset
  const refresh = useCallback(async () => {
    const response = await fetch(endpoint, { cache: 'no-store' }),
      body = await response.json()
    if (!response.ok) throw Error(body.error)
    setData(body)
  }, [endpoint])
  useEffect(() => {
    const update = () => void refresh().catch((e) => setError(e.message))
    update()
    const timer = setInterval(update, 10000)
    return () => clearInterval(timer)
  }, [refresh])
  async function inspect(id: string, before?: string) {
    try {
      const r = await fetch(
          endpoint + '&instance=' + id + (before ? '&before=' + encodeURIComponent(before) : ''),
          { cache: 'no-store' }
        ),
        body = await r.json()
      if (!r.ok) throw Error(body.error)
      setSelected(id)
      setDetail((old) =>
        before && old ? { ...body, decisions: [...old.decisions, ...body.decisions] } : body
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Inspection unavailable')
    }
  }
  async function command(action: string, extra: Record<string, string> = {}) {
    setBusy(true)
    setError('')
    try {
      const r = await fetch('/api/systems/experiments', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, asset, requestId: crypto.randomUUID(), ...extra }),
        }),
        body = await r.json()
      if (!r.ok) throw Error(body.error)
      setNotice('Request queued. Its result appears below.')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }
  const disabled = busy || !session.authenticated,
    batch = data?.batches.find((b) =>
      ['active', 'paused', 'expired', 'exiting'].includes(b.status)
    ),
    preview = data?.batches.find((b) => b.status === 'preview')
  return (
    <main className="space-y-6">
      <nav className="flex gap-4" aria-label="Systems views">
        <Link href={'/systems?asset=' + asset}>Systems library</Link>
        <span aria-current="page">Experiments</span>
        <Link
          href={'/systems?tab=experiments&asset=' + (asset === 'stocks' ? 'bitcoin' : 'stocks')}
        >
          {asset === 'stocks' ? 'Bitcoin' : 'Stocks'}
        </Link>
      </nav>
      <header>
        <h1 className="text-2xl font-semibold">
          {asset === 'stocks' ? 'Stock' : 'Bitcoin'} paper experiments
        </h1>
        <p>Small, unvalidated trials with fixed rules. Review each batch before it can trade.</p>
      </header>
      {error && (
        <p role="alert" className="sw-notice sw-error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="sw-notice">
          {notice}
        </p>
      )}
      {!session.authenticated && (
        <p className="sw-notice">Sign in with Operator access to approve or control experiments.</p>
      )}
      {batch ? (
        <section className="sw-card space-y-3">
          <h2>Current pool: {amount(batch.equity)}</h2>
          <p>
            Expires {when(batch.expires)}
            {batch.risk_reason ? ' · Entries paused: ' + human(batch.risk_reason) : ''}
          </p>
          <div className="flex flex-wrap gap-2">
            {['pause', 'resume', 'exit', 'exit_and_pause'].map((action) => (
              <button
                key={action}
                className="sw-button"
                disabled={disabled}
                onClick={() => void command(action, { batch_id: batch.id })}
              >
                {human(action)}
              </button>
            ))}
          </div>
          <button
            className="sw-button"
            disabled={disabled}
            onClick={() =>
              void command('replay', {
                batch_id: batch.id,
                start: new Date(Date.now() - 7 * 86400000).toISOString(),
                end: new Date().toISOString(),
              })
            }
          >
            Replay the last 7 days
          </button>
        </section>
      ) : (
        <section className="sw-card">
          <p>No active batch. Collection and research can continue while trading is disabled.</p>
          <button
            className="sw-button primary"
            disabled={disabled}
            onClick={() => void command('preview')}
          >
            Prepare batch preview
          </button>
        </section>
      )}
      {preview && !batch && (
        <section className="sw-card space-y-3">
          <h2>Review this batch</h2>
          <p>$1,000 pool · Four $200 strategies · $50 control · $150 unallocated</p>
          <p>
            Up to $50 per entry, including allowances. Daily $10 control. Entries pause at 2% daily
            loss or 10% drawdown.
          </p>
          <p>{preview.plan.versions[0].universe.join(', ')}</p>
          <ul className="space-y-2">
            {preview.plan.versions.map((v) => (
              <li key={v.family}>
                <strong>{human(v.family)}:</strong> {rules(v)} Maximum hold {v.holding_minutes}{' '}
                minutes; stop {Number(v.stop) * 100}%, take profit {Number(v.take) * 100}%.
              </li>
            ))}
          </ul>
          <p>
            At most four entries per strategy each Eastern day. Long positions only. Limit entries
            expire after 60 seconds. Exits may use a market order after cancellation is confirmed.
          </p>
          <p>
            Expires {when(preview.expires)}.{' '}
            {asset === 'stocks'
              ? 'Stock sale proceeds wait for settlement.'
              : 'Bitcoin holds last at most four hours.'}
          </p>
          <button
            className="sw-button primary"
            disabled={disabled}
            onClick={() =>
              void command('approve', { batch_id: preview.id, revision: preview.revision })
            }
          >
            Approve this paper batch
          </button>
          <details>
            <summary>Rules and execution settings</summary>
            <pre className="overflow-auto text-xs">{JSON.stringify(preview.plan, null, 2)}</pre>
          </details>
        </section>
      )}
      <section className="overflow-auto">
        <table className="w-full text-left">
          <thead>
            <tr>
              <th>Experiment</th>
              <th>Allocation</th>
              <th>Status</th>
              <th>Last decision</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data?.instances
              .filter((i) => !batch || i.batch_id === batch.id)
              .map((i) => (
                <tr key={i.id}>
                  <td>
                    <button className="underline" onClick={() => void inspect(i.id)}>
                      {human(i.family)}
                    </button>
                  </td>
                  <td>{amount(i.budget)}</td>
                  <td>
                    {human(i.state)}
                    <p className="text-sm opacity-75">{human(i.reason)}</p>
                  </td>
                  <td>{when(i.last_decision)}</td>
                  <td>
                    <button
                      className="sw-button"
                      disabled={disabled}
                      onClick={() =>
                        void command(i.state === 'paused' ? 'resume' : 'pause', {
                          instance_id: i.id,
                        })
                      }
                    >
                      {i.state === 'paused' ? 'Resume' : 'Pause'}
                    </button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
        <p className="text-sm mt-3">
          New signal decisions run 35 seconds after each completed five-minute bar. Closed sessions,
          missing evidence and risk limits can prevent entries.
        </p>
      </section>
      {detail && (
        <section className="sw-card space-y-3">
          <h2>Decision evidence</h2>
          {detail.gaps?.map((g) => (
            <p className="sw-notice" key={g.start}>
              Decision gap: {when(g.start)} to {when(g.end)}. {g.reason}
            </p>
          ))}
          <p>
            {detail.positions
              .filter((p) => Number(p.quantity) > 0)
              .map((p) => `${p.symbol}: ${p.quantity} shares/units, exit by ${when(p.exit_due)}`)
              .join(' · ') || 'No open positions.'}
          </p>
          <div className="flex gap-2">
            <button className="sw-button" onClick={() => void inspect(selected)}>
              Refresh details
            </button>
            <button
              className="sw-button"
              disabled={disabled}
              onClick={() => void command('exit_and_pause', { instance_id: selected })}
            >
              Exit and pause
            </button>
          </div>
          {detail.orders
            .filter((o) => o.error)
            .map((o) => (
              <p role="alert" key={o.id}>
                {o.symbol}: {o.error}
              </p>
            ))}
          {detail.decisions.map((d) => (
            <details key={d.id}>
              <summary>
                {d.symbol} · {when(d.cutoff)} · {human(d.outcome)} · {human(d.reason)}
              </summary>
              <p>
                {d.evidence.bars.length} recorded bars · {d.evidence.news?.length || 0} timely
                articles
              </p>
              <pre className="overflow-auto text-xs">
                {JSON.stringify(d.evidence.conditions || [], null, 2)}
              </pre>
              <a href={endpoint + '&decision=' + d.id} target="_blank" rel="noreferrer">
                Open full evidence
              </a>
            </details>
          ))}
          {detail.next && (
            <button className="sw-button" onClick={() => void inspect(selected, detail.next!)}>
              Earlier decisions
            </button>
          )}
        </section>
      )}
      <details className="sw-card">
        <summary>Research context</summary>
        <p>
          SEC filings and official Federal Reserve and BLS releases inform review. They do not
          generate directional trades.
        </p>
        {data?.context.map((c) => (
          <p key={c.id}>
            <a className="underline" href={c.url} target="_blank" rel="noreferrer">
              {c.title}
            </a>{' '}
            · {c.source}
            {c.symbol ? ' · ' + c.symbol : ''} · published {when(c.published)} · first seen{' '}
            {when(c.observed)}
          </p>
        ))}
      </details>
      <details className="sw-card">
        <summary>Research proposals</summary>
        <p>
          At most two predefined changes per family each week. A proposal only trades after a new
          batch is reviewed and approved.
        </p>
        {data?.proposals.slice(0, 8).map((p) => (
          <p key={p.id}>
            {human(p.family)} · variant {p.variant} · {p.week}{' '}
            <button
              className="sw-button"
              disabled={disabled || Boolean(batch)}
              onClick={() => void command('preview', { proposal_id: p.id })}
            >
              Preview a batch with this change
            </button>
          </p>
        ))}
      </details>
      <details className="sw-card">
        <summary>Recent requests and research</summary>
        {data?.commands.map((c) => (
          <p key={c.id}>
            {human(c.action)} · {c.status}
            {c.result_json && JSON.parse(c.result_json).error
              ? ' · ' + JSON.parse(c.result_json).error
              : ''}
          </p>
        ))}
        {data?.research.map((r) => (
          <details key={r.id}>
            <summary>
              Replay · {r.status}
              {r.error ? ' · ' + r.error : ''}
            </summary>
            {r.status === 'succeeded' && (
              <div className="flex gap-4">
                {['summary', 'evidence', 'replay'].map((kind) => (
                  <a
                    key={kind}
                    className="underline"
                    href={'/api/systems/experiments/artifact?job=' + r.id + '&kind=' + kind}
                  >
                    Download {kind}
                  </a>
                ))}
              </div>
            )}
            <pre className="overflow-auto text-xs">
              {JSON.stringify(JSON.parse(r.result_json || '{}'), null, 2)}
            </pre>
          </details>
        ))}
      </details>
      <details className="sw-card">
        <summary>Collection and execution health</summary>
        {data?.health.map((h) => (
          <p key={h.component}>
            {human(h.component)} · {h.error || 'OK'} · {when(h.at)}
          </p>
        ))}
      </details>
    </main>
  )
}
