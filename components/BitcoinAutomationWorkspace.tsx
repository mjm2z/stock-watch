'use client'
import Link from 'next/link'
import { FormEvent, useCallback, useEffect, useState } from 'react'
import { OperatorAccess } from './SystemsWorkspace'

type Row = Record<string, unknown>
type Snapshot = {
  versions: Row[]
  evaluations: Row[]
  orders: Row[]
  commands: Row[]
  health: Row[]
  forward: Row[]
  fees: Row[]
  account: Row | null
}
const empty: Snapshot = {
  versions: [],
  evaluations: [],
  orders: [],
  commands: [],
  health: [],
  forward: [],
  fees: [],
  account: null,
}
const field = 'w-full rounded-md border bg-background p-2 text-sm'
const button = 'min-h-11 rounded-md border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50'
const frames = ['1Min', '5Min', '15Min', '1Hour', '4Hour', '1Day', '1Week', '1Month']
const frameLabels = [
  '1 minute',
  '5 minutes',
  '15 minutes',
  '1 hour',
  '4 hours',
  '1 day',
  '1 week',
  '1 month',
]
function obj(v: unknown): Row {
  try {
    return typeof v === 'string' ? JSON.parse(v) : ((v || {}) as Row)
  } catch {
    return {}
  }
}
function pct(v: unknown) {
  return typeof v === 'number' ? `${(v * 100).toFixed(2)}%` : 'Not available'
}
function date(v: unknown) {
  return v ? new Date(String(v)).toLocaleString() : 'Not yet scheduled'
}
function money(v: unknown) {
  return v == null ? 'Unfunded' : `$${Number(v).toFixed(2)}`
}
function name(row: Row) {
  const c = obj(row.config_json)
  return `${row.template} · ${frameLabels[frames.indexOf(String(c.timeframe))] || c.timeframe} · ${String(row.id).slice(0, 8)}`
}

export function BitcoinAutomationWorkspace() {
  const [data, setData] = useState<Snapshot>(empty)
  const [operator, setOperator] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [approval, setApproval] = useState('')
  const [confirm, setConfirm] = useState('')
  const access = useCallback((value: boolean) => setOperator(value), [])
  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/systems/bitcoin', { cache: 'no-store' })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error)
      setData(result)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load Bitcoin automation.')
    }
  }, [])
  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), 15000)
    return () => clearInterval(timer)
  }, [load])
  async function write(body: Row) {
    setBusy(true)
    setMessage('')
    try {
      const response = await fetch('/api/systems/bitcoin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error)
      setMessage(
        body.action === 'fund' || body.action === 'reactivate'
          ? 'Account command queued. Check its result below.'
          : 'Saved. Collection and qualification run on the worker schedule.'
      )
      setApproval('')
      setConfirm('')
      await load()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Could not save this change.')
    } finally {
      setBusy(false)
    }
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const values = Object.fromEntries(new FormData(event.currentTarget))
    await write({ action: 'create', ...values, allocation: Number(values.allocation) / 100 })
  }
  const locked = !operator || busy
  return (
    <main className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <header className="space-y-2">
        <p className="text-sm text-muted-foreground">
          <Link href="/bitcoin">Bitcoin</Link> / Systems
        </p>
        <h1 className="text-2xl font-semibold">Bitcoin systems</h1>
        <p className="max-w-3xl text-muted-foreground">
          Research rules across 100 scenarios, observe them forward, and allow qualified versions to
          trade a separate $300 paper account. Each system owns its cash and Bitcoin.
        </p>
        <div className="flex flex-wrap gap-4 text-sm underline">
          <Link href="/systems?asset=bitcoin&legacy=1">Earlier research and deployments</Link>
          <Link href="/systems?asset=stocks">Stock systems</Link>
          <Link href="/bitcoin?view=blockchain">Blockchain monitor</Link>
        </div>
      </header>
      <OperatorAccess onChange={access} />
      {error && (
        <p role="alert" className="rounded-md border border-destructive p-3">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="rounded-md border p-3">
          {message}
        </p>
      )}
      <section className="grid gap-4 sm:grid-cols-3" aria-label="Automation overview">
        <div className="rounded-lg border p-4">
          <p className="text-sm text-muted-foreground">Paper budget</p>
          <p className="text-xl font-semibold">$300 total · up to 5 systems</p>
          <p className="text-sm">Equal allocations; idle cash stays with its system.</p>
        </div>
        <div className="rounded-lg border p-4">
          <p className="text-sm text-muted-foreground">Account</p>
          <p className="text-xl font-semibold">
            {data.account?.risk_paused ? 'Risk paused' : data.account ? 'Funded' : 'Not funded'}
          </p>
          <p className="text-sm">10% account and system drawdown limit.</p>
        </div>
        <div className="rounded-lg border p-4">
          <p className="text-sm text-muted-foreground">Evidence required</p>
          <p className="text-xl font-semibold">100 scenarios + 30 forward days</p>
          <p className="text-sm">Insufficient evidence keeps entries blocked.</p>
        </div>
      </section>
      <details className="rounded-lg border p-4">
        <summary className="cursor-pointer font-medium">Create an immutable system version</summary>
        <form onSubmit={create} className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-sm">
            Rule template
            <select name="template" className={field}>
              <option value="trend">Trend crossover</option>
              <option value="breakout">Breakout</option>
            </select>
          </label>
          <label className="text-sm">
            Decision timeframe
            <select name="timeframe" defaultValue="1Hour" className={field}>
              {frames.map((f, i) => (
                <option key={f} value={f}>
                  {frameLabels[i]}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Maximum holding duration
            <input
              name="holding_count"
              type="number"
              min="1"
              defaultValue="7"
              required
              className={field}
            />
          </label>
          <label className="text-sm">
            Holding unit
            <select name="holding_unit" defaultValue="days" className={field}>
              {['minutes', 'hours', 'days', 'weeks', 'months'].map((u) => (
                <option key={u}>{u}</option>
              ))}
            </select>
          </label>
          {[
            ['fast', 'Fast average', 20],
            ['slow', 'Slow average', 100],
            ['entry', 'Breakout entry', 55],
            ['exit', 'Breakout exit', 20],
          ].map(([key, label, value]) => (
            <label key={key} className="text-sm">
              {label} (bars)
              <input
                name={String(key)}
                type="number"
                min="5"
                max="250"
                defaultValue={value}
                required
                className={field}
              />
            </label>
          ))}
          <label className="text-sm">
            Position size (% of its budget)
            <input
              name="allocation"
              type="number"
              min="5"
              max="50"
              defaultValue="50"
              required
              className={field}
            />
          </label>
          <label className="text-sm sm:col-span-2">
            Research hypothesis
            <textarea
              name="hypothesis"
              maxLength={2000}
              required
              className={field}
              placeholder="Why should this rule work after costs, and what would invalidate it?"
            />
          </label>
          <div className="self-end">
            <button className={button} disabled={locked}>
              Create version
            </button>
          </div>
          <p className="text-sm text-muted-foreground sm:col-span-2 lg:col-span-4">
            Holding duration is independent of the decision timeframe, from one minute to 12 months.
            Weeks begin Monday UTC; months follow the calendar. Earlier rule or risk exits take
            priority. The exit worker targets 10-second checks; outages can delay fills.
          </p>
        </form>
      </details>
      <section className="space-y-3" aria-labelledby="versions-heading">
        <h2 id="versions-heading" className="text-lg font-semibold">
          System versions
        </h2>
        {!data.versions.length && (
          <p className="rounded-lg border p-4 text-muted-foreground">
            No automation versions yet. Create a version, then start collection. Existing hourly
            versions are copied by the migration installer without approving them.
          </p>
        )}
        {data.versions.map((v) => {
          const id = String(v.id),
            config = obj(v.config_json)
          const evaluation = data.evaluations.find((e) => e.version_id === id)
          const forward = data.forward.find((f) => f.version_id === id)
          const expired =
            !!v.evidence_expires_at &&
            new Date(String(v.evidence_expires_at)).getTime() <= Date.now()
          const status = !v.active
            ? v.enrolled_at
              ? 'Retired'
              : 'Not started'
            : v.risk_paused
              ? 'Risk paused'
              : v.paused
                ? 'Entries paused'
                : expired && v.status === 'qualified'
                  ? 'Suspended'
                  : evaluation?.status === 'running' || evaluation?.status === 'queued'
                    ? 'Evaluating'
                    : String(v.status || 'Collecting')
          return (
            <article key={id} className="space-y-3 rounded-lg border p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h3 className="font-semibold">{name(v)}</h3>
                  <p className="text-sm text-muted-foreground">
                    Hold up to {String(config.holding_count)} {String(config.holding_unit)} ·
                    position size {pct(config.allocation)} · budget {money(v.budget)}
                  </p>
                </div>
                <span className="rounded-full bg-muted px-3 py-1 text-sm capitalize">{status}</span>
              </div>
              <p className="text-sm">
                {v.reason
                  ? String(v.reason)
                  : 'Start collection to build historical and forward evidence.'}
              </p>
              {!!v.evidence_expires_at && (
                <p className="text-xs text-muted-foreground">
                  Last completed evidence: cutoff {date(v.evidence_cutoff)} · expires{' '}
                  {date(v.evidence_expires_at)}
                  {expired ? ' · expired; entries blocked' : ''}
                </p>
              )}
              <dl className="grid gap-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-muted-foreground">Forward days observed</dt>
                  <dd>{String(forward?.days || 0)} / 30 minimum</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Next research review</dt>
                  <dd>{date(v.next_review_at)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Holding deadline</dt>
                  <dd>{v.exit_due_at ? date(v.exit_due_at) : 'No open position'}</dd>
                </div>
              </dl>
              {evaluation && (
                <div className="space-y-1">
                  <p className="text-sm">
                    Evaluation: {String(evaluation.progress)}/100 scenarios ·{' '}
                    {String(evaluation.cached)} cached · {String(evaluation.status)}
                  </p>
                  <progress
                    aria-label={`${name(v)} evaluation progress`}
                    className="w-full"
                    max={100}
                    value={Number(evaluation.progress)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Evidence cutoff {date(evaluation.cutoff)} · expires{' '}
                    {date(evaluation.expires_at)}
                  </p>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {!v.active && (
                  <button
                    className={button}
                    disabled={locked}
                    onClick={() => void write({ action: 'enroll', version: id })}
                  >
                    Start research collection
                  </button>
                )}
                {!!v.active && (
                  <button
                    className={button}
                    disabled={locked}
                    onClick={() =>
                      void write({ action: v.paused ? 'resume' : 'pause', version: id })
                    }
                  >
                    {v.paused ? 'Resume eligible entries' : 'Pause new entries'}
                  </button>
                )}
                {!!v.approved_at && !!v.active && (
                  <label className="flex min-h-11 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selected.includes(id)}
                      disabled={locked || (!selected.includes(id) && selected.length >= 5)}
                      onChange={(e) =>
                        setSelected(
                          e.target.checked ? [...selected, id] : selected.filter((x) => x !== id)
                        )
                      }
                    />
                    Include in funding plan
                  </label>
                )}
                {!!v.active && v.budget == null && (
                  <button
                    className={button}
                    disabled={locked}
                    onClick={() => void write({ action: 'retire', version: id })}
                  >
                    Retire research
                  </button>
                )}
              </div>
              {!!v.active && !v.approved_at && (
                <details>
                  <summary className="cursor-pointer text-sm">
                    Approve automatic paper entries for this version
                  </summary>
                  <p className="my-2 break-all text-sm">
                    Once funded, this version can enter automatically whenever its evidence
                    qualifies. Exits continue when entries are suspended. Type the version ID:{' '}
                    <code>{id}</code>
                  </p>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <input
                      aria-label={`Confirm approval ${id.slice(0, 8)}`}
                      value={approval}
                      onChange={(e) => setApproval(e.target.value)}
                      className={field}
                      autoComplete="off"
                    />
                    <button
                      className={button}
                      disabled={locked || approval !== id}
                      onClick={() =>
                        void write({ action: 'approve', version: id, confirmation: approval })
                      }
                    >
                      Approve version
                    </button>
                  </div>
                </details>
              )}
              <details>
                <summary className="cursor-pointer text-sm text-muted-foreground">
                  Version details
                </summary>
                <p className="mt-2 text-sm">{String(v.hypothesis)}</p>
                <p className="break-all text-xs">{id}</p>
                <p className="text-sm">
                  Conservative cash: {money(v.cash)} · owned BTC: {String(v.quantity || '0')} · last
                  decision: {date(v.last_decision_at)}
                </p>
              </details>
            </article>
          )
        })}
      </section>
      <section className="space-y-3 rounded-lg border p-4">
        <h2 className="text-lg font-semibold">Funding plan</h2>
        <p className="text-sm">
          {selected.length
            ? `${selected.length} selected · up to ${money(300 / selected.length)} each`
            : 'Select approved systems above.'}{' '}
          Funding changes require a flat, reconciled account with settled orders. Fees and losses
          can reduce available cash.
        </p>
        <label className="block text-sm">
          Type FUND BITCOIN PAPER to apply this allocation, or REACTIVATE BITCOIN PAPER to request a
          risk review.
          <input
            className={`${field} mt-1`}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="off"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            className={button}
            disabled={locked || !selected.length || confirm !== 'FUND BITCOIN PAPER'}
            onClick={() =>
              void write({ action: 'fund', versions: selected, confirmation: confirm })
            }
          >
            Apply funding plan
          </button>
          <button
            className={button}
            disabled={locked || confirm !== 'REACTIVATE BITCOIN PAPER'}
            onClick={() => void write({ action: 'reactivate', confirmation: confirm })}
          >
            Request risk reactivation
          </button>
        </div>
        {data.commands.map((c) => (
          <p className="text-sm" key={String(c.id)}>
            {String(c.action)}: {String(c.status)}
            {c.error ? ` — ${c.error}` : ''}
          </p>
        ))}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Evaluation results</h2>
        <p className="text-sm text-muted-foreground">
          20 chronological windows × 5 execution-cost profiles. At least 30 unique completed trades,
          five independent windows, positive cost-stressed results, and controlled drawdown are
          required. Historical win rates are not future success probabilities.
        </p>
        {!data.evaluations.length && (
          <p className="text-sm">The research worker schedules the first suite after enrollment.</p>
        )}
        {data.evaluations.map((e) => {
          const r = obj(e.result_json),
            profiles = obj(r.profiles)
          return (
            <details key={String(e.id)} id={`evaluation-${e.id}`} className="rounded-lg border p-4">
              <summary className="cursor-pointer text-sm">
                {String(e.version_id).slice(0, 8)} · {String(e.status)} · {String(e.progress)}/100 ·{' '}
                {date(e.created_at)}
              </summary>
              {!!e.error && (
                <p role="alert" className="mt-2 text-sm">
                  {String(e.error)}
                </p>
              )}
              {e.result_json ? (
                <div className="mt-3 space-y-3">
                  <dl className="grid gap-3 text-sm sm:grid-cols-3">
                    {[
                      ['Median base return', pct(r.median_base_return)],
                      ['Profitable base windows', pct(r.profitable_windows)],
                      ['Scenario pass rate', pct(r.scenario_pass_rate)],
                      ['Trade win rate', pct(r.trade_win_rate)],
                      ['Unique trades', String(r.unique_trades)],
                      ['Independent windows', String(r.independent_windows)],
                      ['Mean exposure', pct(r.mean_exposure)],
                      ['Mean turnover', `${Number(r.mean_turnover).toFixed(2)}×`],
                      ['Mean base costs', money(r.mean_costs)],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <dt className="text-muted-foreground">{label}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                  {Array.isArray(r.trade_win_interval) && (
                    <p className="text-sm">
                      Observed trade win-rate interval (95%): {pct(r.trade_win_interval[0])}–
                      {pct(r.trade_win_interval[1])}. Overlapping trades can remain dependent.
                    </p>
                  )}
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead>
                        <tr>
                          <th className="p-2">Cost profile</th>
                          <th className="p-2">Mean net return</th>
                          <th className="p-2">Maximum drawdown</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(profiles).map(([key, value]) => (
                          <tr key={key} className="border-t">
                            <td className="p-2">{key.replaceAll('_', ' ')}</td>
                            <td className="p-2">{pct(obj(value).mean_net_return)}</td>
                            <td className="p-2">{pct(obj(value).maximum_drawdown)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="text-sm">
                    {Array.isArray(r.reasons)
                      ? r.reasons.join('; ') || 'Research and forward gates passed.'
                      : ''}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {Array.isArray(r.limitations) ? r.limitations.join(' ') : ''}
                  </p>
                </div>
              ) : (
                <p className="mt-2 text-sm">Results appear when all scenarios finish.</p>
              )}
            </details>
          )
        })}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Paper orders and entry evidence</h2>
        {!data.orders.length && <p className="text-sm">No automated orders yet.</p>}
        {data.orders.map((o) => (
          <div key={String(o.id)} className="rounded-lg border p-3 text-sm">
            <p>
              {String(o.side)} · {String(o.version_id).slice(0, 8)} · {String(o.status)} · filled{' '}
              {String(o.filled_qty)} BTC
            </p>
            <p>
              {String(o.reason)} · {date(o.created_at)}
            </p>
            {!!o.evaluation_id && (
              <a className="underline" href={`#evaluation-${o.evaluation_id}`}>
                Entry qualification {String(o.evaluation_id).slice(0, 8)}
              </a>
            )}
          </div>
        ))}
      </section>
      <details className="rounded-lg border p-4">
        <summary className="cursor-pointer font-medium">
          Worker health and fee reconciliation
        </summary>
        <p className="my-2 text-sm">
          Collection and exit checks target 10 seconds. Intraday research refreshes daily; daily-bar
          research weekly; weekly and monthly research monthly. Ledger balances reserve estimated
          fees; broker activities are recorded separately. Unattributed fees block new entries for
          review.
        </p>
        {!data.health.length && (
          <p className="text-sm">
            No worker observations yet. Install and enable Bitcoin collection and automation
            services on the application host.
          </p>
        )}
        {data.health.map((h) => (
          <p className="mt-2 break-words text-sm" key={String(h.key)}>
            {String(h.key)} · {date(h.at)} · {h.error ? String(h.error) : 'Healthy at last check'}
          </p>
        ))}
        {data.fees.map((f) => (
          <p key={String(f.id)} className="mt-2 text-sm">
            Fee {String(f.id).slice(0, 12)} · {String(f.status)} · {date(f.captured_at)}
          </p>
        ))}
      </details>
    </main>
  )
}
