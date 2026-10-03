'use client'
import { useEffect, useRef, useState } from 'react'
import { useOperator } from './OperatorSession'
import { InteractiveChart, ChartBar } from './MarketChart'
type Row = Record<string, any>
const pretty = (n: any) =>
  typeof n === 'number' && Number.isFinite(n) ? (n * 100).toFixed(2) + '%' : 'Unavailable'
const curve = (points: Row[] = [], field = 'net_percent'): ChartBar[] =>
  points.map((p) => ({
    at: p.at,
    open: p[field],
    high: p[field],
    low: p[field],
    close: p[field],
    volume: 0,
  }))
export function ResearchLab({
  asset,
  document,
  name,
  previewOnly = false,
}: {
  asset: 'stocks' | 'bitcoin'
  document?: object
  name?: string
  previewOnly?: boolean
}) {
  const operator = useOperator()
  const [data, setData] = useState<Row>({
      previews: [],
      experiments: [],
      datasets: [],
      snapshots: [],
    }),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  const [dataset, setDataset] = useState(''),
    [start, setStart] = useState(''),
    [end, setEnd] = useState(''),
    [job, setJob] = useState(''),
    [submitted, setSubmitted] = useState('')
  const [selected, setSelected] = useState(''),
    [experiment, setExperiment] = useState('')
  const [plan, setPlan] = useState({
    hypothesis: '',
    mechanism: '',
    baseline: '',
    candidate: '',
    primaryOutcome: 'Net return after costs',
    riskConstraint: 'Maximum drawdown no worse than baseline',
    selectionRule:
      'Higher net return with no worse drawdown; fewer than 30 closed trades is inconclusive',
    reviewPoint: 'Review this paired replay before selecting another candidate',
    parent: '',
  })
  const [review, setReview] = useState({ conclusion: 'inconclusive', explanation: '' })
  const latest = useRef('')
  latest.current = JSON.stringify({ document, dataset, start, end })
  async function load(signal?: AbortSignal) {
    const r = await fetch('/api/systems/lab?asset=' + asset, { signal, cache: 'no-store' })
    const d = await r.json()
    if (!r.ok) throw Error(d.error)
    setData(d)
  }
  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal).catch((e) => {
      if (!controller.signal.aborted) setError(e.message)
    })
    const timer = setInterval(() => void load(controller.signal).catch(() => {}), 10000)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
    // Asset context owns this subscription.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset])
  async function send(action: string, body: Row) {
    setBusy(true)
    setError('')
    const documentAtRequest = latest.current
    try {
      const r = await fetch('/api/systems/lab', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset, action, requestId: crypto.randomUUID(), ...body }),
      })
      const result = await r.json()
      if (!r.ok) throw Error(result.error)
      if (action === 'preview' && latest.current === documentAtRequest) {
        setJob(result.id)
        setSubmitted(documentAtRequest)
      }
      if (action === 'experiment' || action === 'demo') setExperiment(result.id)
      await load()
      return result
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Research request failed')
    } finally {
      setBusy(false)
    }
  }
  const disabled = busy || !operator.authenticated
  const run: Row | undefined = data.previews.find(
    (p: Row) => p.id === (previewOnly ? job : selected)
  )
  const outdated = previewOnly && submitted !== JSON.stringify({ document, dataset, start, end })
  const exp: Row | undefined = data.experiments.find((e: Row) => e.id === experiment)
  const base =
    exp &&
    data.previews.find((r: Row) =>
      exp.attempts.some(
        (a: Row) => a.id === r.id && a.role === 'baseline' && a.status === 'succeeded'
      )
    )
  const candidate =
    exp &&
    data.previews.find((r: Row) =>
      exp.attempts.some(
        (a: Row) => a.id === r.id && a.role === 'candidate' && a.status === 'succeeded'
      )
    )
  const compatible =
    base &&
    candidate &&
    base.result.comparison_key === candidate.result.comparison_key &&
    base.result.engine_hash === candidate.result.engine_hash &&
    base.result.configuration.timeframe === candidate.result.configuration.timeframe
  function chooseDataset(id: string) {
    setDataset(id)
    const d = data.datasets.find((x: Row) => x.id === id)
    setStart((d?.manifest.actual_start || '').slice(0, 10))
    setEnd((d?.manifest.actual_end || '').slice(0, 10))
  }
  return (
    <section
      className="sw-panel space-y-4"
      aria-label={previewOnly ? 'Draft inspection' : 'Research experiments'}
    >
      <header>
        <h2 className="text-xl font-semibold">
          {previewOnly ? 'Inspect before publishing' : 'Experiments & draft previews'}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Edit → Inspect → Historical preview → Evidence review → Publish → Separately
          observe/authorize. Research-only snapshots cannot place orders or consume a funded slot.
        </p>
      </header>
      {error && <p role="status">{error}</p>}
      <div className="flex flex-wrap gap-3">
        <label className="sw-field">
          Retained dataset
          <select value={dataset} onChange={(e) => chooseDataset(e.target.value)}>
            <option value="">Choose verified retained data</option>
            {data.datasets.map((d: Row) => (
              <option key={d.id} value={d.id}>
                {d.manifest.demonstration ? 'DEMO · ' : ''}
                {d.manifest.timeframe || 'timeframe unknown'} ·{' '}
                {d.manifest.actual_start?.slice(0, 10)} – {d.manifest.actual_end?.slice(0, 10)} ·{' '}
                {d.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label className="sw-field">
          Scoring from
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="sw-field">
          Until (exclusive)
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
      </div>
      <p className="text-xs text-muted-foreground">
        Earlier retained bars provide warmup. Dataset timeframe must match the draft. Existing
        Backtesting can prepare data; a preview never downloads years of history while you edit.
      </p>
      {previewOnly ? (
        <div className="flex flex-wrap gap-3">
          <button
            className="sw-button"
            disabled={disabled || !dataset || !start || !end}
            onClick={() =>
              void send('preview', { document, name, dataset, start, end, inspectOnly: true })
            }
          >
            Inspect rules on retained bars
          </button>
          <button
            className="sw-button"
            disabled={disabled || !dataset || !start || !end}
            onClick={() => void send('preview', { document, name, dataset, start, end })}
          >
            Queue historical preview
          </button>
        </div>
      ) : (
        <>
          <label className="sw-field">
            Saved previews
            <select value={selected} onChange={(e) => setSelected(e.target.value)}>
              <option value="">Choose a result</option>
              {data.previews.map((p: Row) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {p.status} · {p.created_at}
                </option>
              ))}
            </select>
          </label>
          <details className="rounded border p-4">
            <summary className="font-semibold">Preregister a comparison</summary>
            <p className="my-3 text-sm">
              Create snapshots with draft inspection first. Plans freeze before these runs; prior
              inspection of the same asset/interval is disclosed. A completed job does not support a
              hypothesis by itself.
            </p>
            <form
              className="grid gap-3 sm:grid-cols-2"
              onSubmit={(e) => {
                e.preventDefault()
                void send('experiment', { ...plan, dataset, start, end })
              }}
            >
              {(
                [
                  'hypothesis',
                  'mechanism',
                  'primaryOutcome',
                  'riskConstraint',
                  'selectionRule',
                  'reviewPoint',
                ] as const
              ).map((key) => (
                <label className="sw-field" key={key}>
                  {key.replace(/([A-Z])/g, ' $1')}
                  <textarea
                    required
                    value={plan[key]}
                    maxLength={2000}
                    onChange={(e) => setPlan((p) => ({ ...p, [key]: e.target.value }))}
                  />
                </label>
              ))}
              {(['baseline', 'candidate'] as const).map((key) => (
                <label className="sw-field capitalize" key={key}>
                  {key}
                  <select
                    required
                    value={plan[key]}
                    onChange={(e) => setPlan((p) => ({ ...p, [key]: e.target.value }))}
                  >
                    <option value="">Choose immutable research snapshot</option>
                    {data.snapshots.map((s: Row) => (
                      <option key={s.id} value={s.id}>
                        {s.name} · {s.id.slice(0, 10)}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
              <label className="sw-field">
                Parent experiment (optional revision)
                <select
                  value={plan.parent}
                  onChange={(e) => setPlan((p) => ({ ...p, parent: e.target.value }))}
                >
                  <option value="">New experiment</option>
                  {data.experiments.map((e: Row) => (
                    <option key={e.id} value={e.id}>
                      {e.plan.hypothesis}
                    </option>
                  ))}
                </select>
              </label>
              <button className="sw-button" disabled={disabled || !dataset || !start || !end}>
                Freeze experiment plan
              </button>
            </form>
          </details>
          {asset === 'bitcoin' && (
            <button className="sw-button" disabled={disabled} onClick={() => void send('demo', {})}>
              Create demonstration: daily breakout 55/20 vs 55/10
            </button>
          )}
          <label className="sw-field">
            Experiment lineage
            <select value={experiment} onChange={(e) => setExperiment(e.target.value)}>
              <option value="">Select experiment</option>
              {data.experiments.map((e: Row) => (
                <option key={e.id} value={e.id}>
                  {e.plan.demonstration ? 'DEMO · ' : ''}
                  {e.plan.hypothesis}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      {run && (
        <section className="space-y-3 rounded border p-4">
          <h3 className="font-semibold">
            Preview / simulated · {run.status}
            {outdated ? ' · OUTDATED: draft changed' : ''}
          </h3>
          {run.error && <p role="alert">{run.error}</p>}
          {['queued', 'running'].includes(run.status) && (
            <button
              className="sw-button"
              disabled={disabled}
              onClick={() => void send('cancel', { id: run.id })}
            >
              Cancel research job
            </button>
          )}
          {run.result?.identity && (
            <>
              <p className="text-sm">
                {run.result.evidence_class} · {run.result.authority} · dataset{' '}
                {run.result.dataset?.slice(0, 12)} · ${run.result.capital} continuous capital ·{' '}
                {run.result.prior_interval_inspections} earlier interval inspections
                {run.result.reused_from ? ' · Cached evidence, original age retained' : ''}
              </p>
              <p className="text-sm">{run.result.inspection_note}</p>
              {run.result.artifact_sha256 && (
                <a
                  className="text-sm underline"
                  href={'/api/systems/lab/artifact?sha=' + run.result.artifact_sha256}
                >
                  Download complete hash-verified evidence
                </a>
              )}
              <details>
                <summary>Inputs, warmup, folds, data treatment and authority</summary>
                <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words text-xs">
                  {JSON.stringify(run.result.preflight, null, 2)}
                </pre>
              </details>
              {!!run.result.inspection?.length && (
                <details open>
                  <summary>Rule values: true / false / unavailable</summary>
                  <div className="grid gap-3">
                    {run.result.inspection.map((i: Row) => (
                      <div key={i.symbol} className="rounded border p-3">
                        <h4 className="font-semibold">
                          {i.symbol} · {i.decision || 'Inspection'}
                        </h4>
                        <p className="text-xs text-muted-foreground">
                          Completed bar {i.completed_bar} · {i.available_bars} warmup bars · Next
                          expected {i.next_bar_boundary || 'calendar unavailable'}
                        </p>
                        <p className="text-sm">{i.reason}</p>
                        {i.entry && <RuleState title="Entry" group={i.entry} />}
                        {i.exit && <RuleState title="Exit" group={i.exit} />}
                      </div>
                    ))}
                  </div>
                </details>
              )}
              {run.result.continuous && (
                <>
                  <Metrics result={run.result.continuous} />
                  <InteractiveChart
                    bars={curve(run.result.continuous.equity_curve)}
                    percent
                    label="Preview net return"
                  />
                  <details>
                    <summary>Hypothetical fills (first 200) and costs</summary>
                    <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words text-xs">
                      {JSON.stringify(run.result.continuous.fills, null, 2)}
                    </pre>
                  </details>
                </>
              )}
              <p className="text-xs text-muted-foreground">
                Display curves contain at most 600 points. Metrics use complete evidence. Previewing
                exposes this interval for future selection; it is not an untouched holdout.
              </p>
            </>
          )}
        </section>
      )}
      {exp && (
        <section className="space-y-3 rounded border p-4">
          <h3 className="font-semibold">
            {exp.plan.demonstration
              ? 'Demonstration fixture — not investment evidence'
              : 'Frozen experiment'}
          </h3>
          <p>{exp.plan.hypothesis}</p>
          <p className="text-sm">{exp.plan.selectionRule}</p>
          <p className="text-sm">
            Authority: research-only · Conclusion: {exp.reviews[0]?.conclusion || 'not reviewed'} ·
            Parent: {exp.parent_id || 'none'}
          </p>
          {exp.plan.real_data_plan && <p>{exp.plan.real_data_plan}</p>}
          <details>
            <summary>Frozen plan and configuration differences</summary>
            <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap break-words text-xs">
              {JSON.stringify(
                {
                  plan: exp.plan,
                  baseline: data.snapshots.find((s: Row) => s.id === exp.plan.baseline)?.config,
                  candidate: data.snapshots.find((s: Row) => s.id === exp.plan.candidate)?.config,
                },
                null,
                2
              )}
            </pre>
          </details>
          <button
            className="sw-button"
            disabled={
              disabled || exp.attempts.some((a: Row) => ['queued', 'running'].includes(a.status))
            }
            onClick={() => void send('run_experiment', { id: exp.id })}
          >
            Queue frozen pair / explicit retry
          </button>
          <ul className="text-sm">
            {exp.attempts.map((a: Row) => (
              <li key={a.id}>
                {a.role} · {a.status}
                {a.reused_from ? ' · reused cache (not independent evidence)' : ''}
                {a.error ? ' · ' + a.error : ''}{' '}
                <button className="underline" onClick={() => setSelected(a.id)}>
                  Inspect run
                </button>
                {['queued', 'running'].includes(a.status) && (
                  <button
                    className="ml-2 underline"
                    disabled={disabled}
                    onClick={() => void send('cancel', { id: a.id })}
                  >
                    Cancel
                  </button>
                )}
              </li>
            ))}
          </ul>
          {base &&
            candidate &&
            (compatible ? (
              <>
                <p className="text-sm">
                  Comparable dataset, engine, period, capital, timeframe and costs. No automatic
                  winner or authority change.
                </p>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h4>Baseline</h4>
                    <Metrics result={base.result.continuous} />
                  </div>
                  <div>
                    <h4>Candidate</h4>
                    <Metrics result={candidate.result.continuous} />
                  </div>
                </div>
                <InteractiveChart
                  bars={curve(base.result.continuous.equity_curve)}
                  percent
                  label="Baseline net return"
                  comparisons={[
                    { name: 'Candidate', bars: curve(candidate.result.continuous.equity_curve) },
                  ]}
                />
                <InteractiveChart
                  bars={curve(base.result.continuous.equity_curve, 'drawdown')}
                  percent
                  label="Baseline drawdown"
                  comparisons={[
                    {
                      name: 'Candidate drawdown',
                      bars: curve(candidate.result.continuous.equity_curve, 'drawdown'),
                    },
                  ]}
                />
              </>
            ) : (
              <p role="status">Incompatible evidence: comparison cannot produce a winner.</p>
            ))}
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              void send('review', { id: exp.id, ...review })
            }}
          >
            <label className="sw-field">
              Research conclusion
              <select
                value={review.conclusion}
                onChange={(e) => setReview((r) => ({ ...r, conclusion: e.target.value }))}
              >
                {[
                  'invalid inputs',
                  'not supported',
                  'inconclusive',
                  'promising historically',
                  'supported by additional forward evidence',
                ].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="sw-field">
              Evidence, limitations and next test
              <textarea
                required
                maxLength={2000}
                value={review.explanation}
                onChange={(e) => setReview((r) => ({ ...r, explanation: e.target.value }))}
              />
            </label>
            <button className="sw-button" disabled={disabled}>
              Record review (authority unchanged)
            </button>
          </form>
          <details>
            <summary>Review history</summary>
            <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-xs">
              {JSON.stringify(exp.reviews, null, 2)}
            </pre>
          </details>
        </section>
      )}
    </section>
  )
}
function Metrics({ result }: { result: Row }) {
  if (!result) return <p>Result unavailable</p>
  return (
    <dl className="grid grid-cols-2 gap-2 text-sm">
      {Object.entries({
        'Net return': pretty(result.net_return),
        'Maximum drawdown': pretty(result.maximum_drawdown),
        'Exposure (observation average)': pretty(result.average_exposure),
        'Closed trades': result.closed_trades,
        'Fees ($)': result.fees?.toFixed(2),
        'Turnover / capital': result.turnover?.toFixed(2),
        'Net expectancy ($/closed trade)':
          result.metrics?.average_trade?.toFixed(2) ?? 'Unavailable',
        'Average win / loss ($)': `${result.metrics?.average_win?.toFixed(2) ?? 'Unavailable'} / ${result.metrics?.average_loss?.toFixed(2) ?? 'Unavailable'}`,
      }).map(([k, v]) => (
        <div key={k}>
          <dt className="text-muted-foreground">{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function RuleState({ title, group }: { title: string; group: Row }) {
  const state = (v: unknown) => (v === true ? 'True' : v === false ? 'False' : 'Unavailable')
  const operand = (spec: Row, value: unknown) =>
    `${spec.kind}${spec.period ? '(' + spec.period + ')' : ''}: ${typeof value === 'number' ? value.toLocaleString() : 'unavailable'}`
  return (
    <div className="mt-3 text-sm">
      <h5 className="font-semibold">
        {title} · {group.op.toUpperCase()} · {state(group.state)}
      </h5>
      <ul className="ml-4 list-disc">
        {group.conditions?.map((c: Row, i: number) => (
          <li key={i}>
            {c.conditions ? (
              <RuleState title="Group" group={c} />
            ) : (
              <span>
                {operand(c.left, c.left_value)} {c.op.replaceAll('_', ' ')}{' '}
                {operand(c.right, c.right_value)} — {state(c.state)}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
