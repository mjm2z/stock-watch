'use client'
import Link from 'next/link'
import { useOperator } from './OperatorSession'
import { SystemEquityChart } from '@/components/dashboard/SystemEquityChart'
import { FormEvent, useCallback, useEffect, useState } from 'react'

type Row = Record<string, unknown>
type Snapshot = {
  versions: Row[]
  datasets: Row[]
  runs: Row[]
  deployments: Row[]
  observations: Row[]
  commands: Row[]
}
const empty: Snapshot = {
  versions: [],
  datasets: [],
  runs: [],
  deployments: [],
  observations: [],
  commands: [],
}
const input = 'w-full rounded-md border bg-background p-2 text-sm'
const button = 'min-h-11 rounded-md border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50'
function obj(value: unknown): Row {
  try {
    return typeof value === 'string' ? JSON.parse(value) : ((value || {}) as Row)
  } catch {
    return {}
  }
}
function percent(value: unknown) {
  return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : 'Unavailable'
}
function label(row: Row) {
  return `${row.template} · ${String(row.id).slice(0, 8)}`
}

export function OperatorAccess({ onChange }: { onChange: (authenticated: boolean) => void }) {
  const session = useOperator()
  useEffect(() => { onChange(session.authenticated) }, [session.authenticated, onChange])
  return <p className="text-sm text-muted-foreground">{session.authenticated ? 'Operator session active' : session.configured ? 'Read-only · use Operator access in the header to make changes' : 'Read-only · operator access is not configured'}</p>
}

export function SystemsWorkspace({ asset }: { asset: 'stocks' | 'bitcoin' }) {
  const [data, setData] = useState<Snapshot>(empty)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [authorized, setAuthorized] = useState(false)
  const [busy, setBusy] = useState(false)
  const [template, setTemplate] = useState('trend')
  const [version, setVersion] = useState('')
  const [dataset, setDataset] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`/api/systems?asset=${asset}`, { cache: 'no-store' })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error)
      setData(result)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Systems unavailable.')
    }
  }, [asset])
  useEffect(() => {
    void refresh()
    const timer = setInterval(refresh, 15000)
    return () => clearInterval(timer)
  }, [refresh])
  async function mutate(body: Row) {
    setBusy(true)
    setNotice('')
    try {
      const response = await fetch('/api/systems', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error)
      setNotice('Saved. Queued work will run on the next worker tick.')
      await refresh()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Change failed.')
    } finally {
      setBusy(false)
    }
  }
  const comparison = data.runs.filter((r) => selected.includes(String(r.id)))
  return (
    <main className="container mx-auto space-y-6 p-4 sm:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">
            {asset === 'bitcoin' ? 'Bitcoin' : 'Stock'} systems
          </h1>
          <p className="mt-2 text-muted-foreground">
            Define rules, test with limited capital, observe forward signals, and review paper
            activation.
          </p>
        </div>
        <Link href="/backtests" className={button}>
          Historical stock backtests
        </Link>
      </div>
      <p className="rounded-lg border p-3 text-sm">
        {asset === 'bitcoin'
          ? '$300 separate paper allocation · Hourly signals · Positive net return · 10% portfolio drawdown exit and pause'
          : '$300 stock allocation · Daily signals · Net return above SPY with controlled drawdown · Current stock trading remains active'}
      </p>
      <OperatorAccess onChange={setAuthorized} />
      {error && (
        <p role="alert" className="rounded border border-amber-500 p-3">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded border p-3">
          {notice}
        </p>
      )}
      <section className="grid gap-6 lg:grid-cols-2">
        <form
          className="space-y-4 rounded-xl border p-5"
          onSubmit={(e) => {
            e.preventDefault()
            const f = new FormData(e.currentTarget)
            void mutate({
              action: 'create',
              asset,
              template,
              hypothesis: f.get('hypothesis'),
              fast: Number(f.get('fast') || 20),
              slow: Number(f.get('slow') || 100),
              entry: Number(f.get('entry') || 55),
              exit: Number(f.get('exit') || 20),
              allocation: Number(f.get('allocation')) / 100,
            })
          }}
        >
          <h2 className="text-lg font-semibold">1. Define a research hypothesis</h2>
          <label className="block text-sm">
            Rule template
            <select
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
              className={input}
            >
              <option value="trend">Moving-average crossover</option>
              <option value="breakout">Price breakout</option>
            </select>
          </label>
          <p className="text-sm text-muted-foreground">
            {template === 'trend'
              ? 'Enter on a fast-average crossover above the slow average; exit on the reverse crossover.'
              : 'Enter above the preceding high; exit below the preceding low. The current bar is excluded from thresholds.'}{' '}
            Rules use completed bars.
          </p>
          <div className="grid grid-cols-2 gap-3">
            {(template === 'trend'
              ? [
                  ['fast', 'Fast periods', 20],
                  ['slow', 'Slow periods', 100],
                ]
              : [
                  ['entry', 'Entry periods', 55],
                  ['exit', 'Exit periods', 20],
                ]
            ).map(([name, title, value]) => (
              <label key={name} className="text-sm">
                {title}
                <input
                  name={String(name)}
                  type="number"
                  min={5}
                  max={250}
                  defaultValue={value}
                  required
                  className={input}
                />
              </label>
            ))}
          </div>
          <label className="block text-sm">
            Maximum allocation (%)
            <input
              name="allocation"
              type="number"
              min={5}
              max={100}
              defaultValue={50}
              required
              className={input}
            />
          </label>
          <label className="block text-sm">
            Why might this work?
            <textarea
              name="hypothesis"
              required
              maxLength={2000}
              className={input}
              placeholder="State the hypothesis and what would invalidate it."
            />
          </label>
          <button disabled={!authorized || busy} className={button}>
            Save immutable version
          </button>
        </form>
        <form
          className="space-y-4 rounded-xl border p-5"
          onSubmit={(e) => {
            e.preventDefault()
            void mutate({ action: 'backtest', version, dataset })
          }}
        >
          <h2 className="text-lg font-semibold">2. Test and observe</h2>
          <label className="block text-sm">
            System version
            <select
              className={input}
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              required
            >
              <option value="">Choose a version</option>
              {data.versions.map((v) => (
                <option key={String(v.id)} value={String(v.id)}>
                  {label(v)}
                </option>
              ))}
            </select>
          </label>
          {version && (
            <p className="text-sm">
              {String(data.versions.find((v) => v.id === version)?.hypothesis || '')}
            </p>
          )}
          <label className="block text-sm">
            Immutable dataset
            <select
              className={input}
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              required
            >
              <option value="">Choose a dataset</option>
              {data.datasets.map((d) => (
                <option key={String(d.id)} value={String(d.id)}>
                  {String(obj(d.manifest_json).provider)} · {String(d.id).slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {dataset && (
            <details className="text-sm">
              <summary>Dataset provenance and coverage</summary>
              <pre className="overflow-auto whitespace-pre-wrap p-2">
                {JSON.stringify(
                  obj(data.datasets.find((d) => d.id === dataset)?.manifest_json),
                  null,
                  2
                )}
              </pre>
            </details>
          )}
          {!data.datasets.length && (
            <p className="text-sm text-muted-foreground">
              No datasets imported yet. Import a validated historical dataset with the systems
              worker before running a backtest.
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            $300 cash pool; fees and slippage included. Walk-forward defaults: 24 months training, 6
            validation, 3 testing. Latest 6 months remain sealed when coverage permits.
          </p>
          <div className="flex flex-wrap gap-2">
            <button disabled={!authorized || busy || !version || !dataset} className={button}>
              Queue backtest
            </button>
            <button
              type="button"
              disabled={!authorized || busy || !version}
              className={button}
              onClick={() => void mutate({ action: 'shadow', version })}
            >
              Start shadow observations
            </button>
          </div>
          <p className="text-sm text-muted-foreground">
            Shadow mode records forward rule decisions without submitting orders. A few days of
            results do not establish profitability.
          </p>
        </form>
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Backtest results</h2>
        <p className="text-sm text-muted-foreground">
          Headline returns below cover the pre-holdout research interval. Out-of-sample fold results
          are shown separately; they are the stronger test of effectiveness.
        </p>
        {!data.runs.length && (
          <p className="text-muted-foreground">
            No systems backtests yet. Existing stock results remain available under Historical stock
            backtests.
          </p>
        )}
        {data.runs.map((run) => {
          const result = obj(run.result_json)
          const base = obj(result.base)
          return (
            <article key={String(run.id)} className="space-y-3 rounded-xl border p-4">
              <div className="flex flex-wrap items-center gap-3">
                <h3 className="font-medium">Run {String(run.id).slice(0, 8)}</h3>
                <span>
                  {String(run.status)} · {Number(run.progress)}%
                </span>
                {run.status === 'succeeded' && (
                  <label className="text-sm">
                    <input
                      type="checkbox"
                      checked={selected.includes(String(run.id))}
                      onChange={(e) =>
                        setSelected(
                          e.target.checked
                            ? [...selected, String(run.id)].slice(-3)
                            : selected.filter((id) => id !== run.id)
                        )
                      }
                    />{' '}
                    Compare
                  </label>
                )}
                {['queued', 'running'].includes(String(run.status)) && (
                  <button
                    className={button}
                    disabled={!authorized || busy}
                    onClick={() => void mutate({ action: 'cancel', run: run.id })}
                  >
                    Cancel
                  </button>
                )}
              </div>
              {run.error ? <p role="alert">{String(run.error)}</p> : null}
              {run.status === 'succeeded' && (
                <>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <Metric title="Net return" value={percent(base.net_return)} />
                    <Metric title="Maximum drawdown" value={percent(base.maximum_drawdown)} />
                    <Metric title="Closed trades" value={String(base.closed_trades)} />
                    <Metric
                      title="Double-cost return"
                      value={percent(obj(result.double_cost).net_return)}
                    />
                  </div>
                  <p className="text-sm">
                    Out-of-sample return: {percent(obj(result.out_of_sample).net_return)} ·
                    Drawdown: {percent(obj(result.out_of_sample).maximum_drawdown)} · Closed trades:{' '}
                    {String(obj(result.out_of_sample).closed_trades ?? 'Unavailable')}
                  </p>
                  <p className="text-sm">
                    Evidence: {String(base.evidence)} · Holdout: {String(result.holdout_status)} ·{' '}
                    {Array.isArray(result.folds) ? result.folds.length : 0} walk-forward folds
                  </p>
                  {Array.isArray(base.warnings) &&
                    base.warnings.map((w, i) => (
                      <p className="text-sm text-amber-700 dark:text-amber-400" key={i}>
                        {String(w)}
                      </p>
                    ))}
                  <SystemEquityChart points={base.equity_curve} />
                  <details>
                    <summary className="cursor-pointer text-sm">
                      Execution, benchmark, and reproducibility details
                    </summary>
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">
                      {JSON.stringify(result, null, 2)}
                    </pre>
                  </details>
                </>
              )}
            </article>
          )
        })}
        {comparison.length > 1 && (
          <div className="overflow-x-auto rounded border">
            <table className="w-full text-left text-sm">
              <caption className="p-3 text-left">
                Compare selected runs · Results are only comparable over matching datasets and
                periods.
              </caption>
              <thead>
                <tr>
                  <th className="p-3">Run</th>
                  <th>Net return</th>
                  <th>Drawdown</th>
                  <th>Closed trades</th>
                </tr>
              </thead>
              <tbody>
                {comparison.map((r) => {
                  const b = obj(obj(r.result_json).base)
                  return (
                    <tr key={String(r.id)}>
                      <td className="p-3">{String(r.id).slice(0, 8)}</td>
                      <td>{percent(b.net_return)}</td>
                      <td>{percent(b.maximum_drawdown)}</td>
                      <td>{String(b.closed_trades)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">3. Forward observation and paper review</h2>
        {!data.deployments.length && (
          <p className="text-muted-foreground">
            Start a shadow deployment to collect forward observations.
          </p>
        )}
        {data.deployments.map((d) => (
          <article key={String(d.id)} className="space-y-3 rounded-xl border p-4">
            <h3 className="font-medium">
              {String(d.template)} · {String(d.mode)}
            </h3>
            <p className="break-all text-xs">Deployment: {String(d.id)}</p>
            <p className="text-sm">
              Started {String(d.started_at)} · Last decision{' '}
              {String(d.last_decision_at || 'Awaiting worker')}
            </p>
            <p className="text-sm text-muted-foreground">
              Activation requires a reviewed backtest, forward observations, and account preflight.
              Pausing a paper system requests an exit, which may fail or fill beyond the risk
              threshold.
            </p>
            <form
              className="flex flex-wrap gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                const f = new FormData(e.currentTarget)
                void mutate({
                  action: f.get('action'),
                  deployment: d.id,
                  confirmation: f.get('confirmation'),
                })
              }}
            >
              <input
                aria-label="Confirm deployment ID"
                name="confirmation"
                placeholder="Type full deployment ID"
                required
                className="min-w-0 flex-1 rounded border bg-background p-2 text-sm"
              />
              <select
                aria-label="Deployment action"
                name="action"
                className="rounded border bg-background p-2"
              >
                <option
                  value={
                    d.mode === 'shadow' ? 'activate' : d.mode === 'paused' ? 'resume' : 'pause'
                  }
                >
                  {d.mode === 'shadow'
                    ? 'Activate paper'
                    : d.mode === 'paused'
                      ? 'Resume paper'
                      : 'Exit and pause'}
                </option>
              </select>
              <button className={button} disabled={!authorized || busy}>
                Submit for worker checks
              </button>
            </form>
          </article>
        ))}
        {data.commands.map((c) => (
          <p key={String(c.id)} role="status" className="text-sm">
            {String(c.action)}: {String(c.status)}
            {c.error ? ` — ${String(c.error)}` : ''}
          </p>
        ))}
        <details>
          <summary className="cursor-pointer">Recent forward observations and errors</summary>
          {data.observations.map((o) => (
            <div key={String(o.id)} className="border-b py-3 text-sm">
              <span>
                {String(o.observed_at)} · {String(o.kind)}
              </span>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">
                {JSON.stringify(obj(o.payload_json), null, 2)}
              </pre>
            </div>
          ))}
        </details>
      </section>
    </main>
  )
}
function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{title}</p>
      <p className="text-xl font-semibold">{value}</p>
    </div>
  )
}
