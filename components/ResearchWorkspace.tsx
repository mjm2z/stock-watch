'use client'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import { PageHeader } from './PageHeader'
import { useOperator } from './OperatorSession'
import { SystemEquityChart } from './dashboard/SystemEquityChart'
type Operand = { kind: string; period?: number; value?: number }
type Condition = { op: string; left: Operand; right: Operand }
type Group = { op: 'all' | 'any'; conditions: (Condition | Group)[] }
type Document = {
  asset: 'stocks' | 'bitcoin'
  template: 'visual'
  protocol: 'visual-rules-v1'
  timeframe: string
  allocation: number
  holding_count: number
  holding_unit: string
  stop_loss: number
  take_profit: number
  entry_rules: Group
  exit_rules: Group
}
type Version = {
  archived: number
  draft_id?: string
  parent_version?: string
  id: string
  template: string
  hypothesis: string
  config: Document
  created_at: string
}
type Draft = {
  id: string
  name: string
  asset: string
  document: Document
  published_version?: string
  archived: number
}
type Job = {
  id: string
  kind: string
  status: string
  progress: number
  error?: string
  created_at: string
}
type Run = {
  id: string
  version_id: string
  status: string
  progress: number
  error?: string
  result: Record<string, unknown>
}
type State = {
  datasets: {
    id: string
    manifest: { actual_start?: string; actual_end?: string; fidelity?: string }
  }[]
  versions: Version[]
  drafts: Draft[]
  jobs: Job[]
  runs: Run[]
  deployments: { id: string; version_id: string; mode: string }[]
  qualifications: { version_id: string; status: string; reason: string }[]
  allocations: { version_id: string; started_at?: string; budget: string }[]
  enrollments: { version_id: string; paused: number }[]
}
const initial: State = {
  datasets: [],
  versions: [],
  drafts: [],
  jobs: [],
  runs: [],
  deployments: [],
  qualifications: [],
  allocations: [],
  enrollments: [],
}
const condition = (): Condition => ({
  op: 'crosses_above',
  left: { kind: 'sma', period: 20 },
  right: { kind: 'sma', period: 100 },
})
const defaults = (asset: 'stocks' | 'bitcoin'): Document => ({
  asset,
  template: 'visual',
  protocol: 'visual-rules-v1',
  timeframe: asset === 'stocks' ? '1Day' : '1Hour',
  allocation: 0.1,
  holding_count: 1,
  holding_unit: 'days',
  stop_loss: 0.05,
  take_profit: 0.1,
  entry_rules: { op: 'all', conditions: [condition()] },
  exit_rules: { op: 'any', conditions: [{ ...condition(), op: 'crosses_below' }] },
})
const frames = ['1Min', '5Min', '15Min', '1Hour', '4Hour', '1Day', '1Week', '1Month']
const kinds = [
  'close',
  'open',
  'high',
  'low',
  'volume',
  'sma',
  'ema',
  'rsi',
  'average_volume',
  'prior_high',
  'prior_low',
  'number',
]
const labels: Record<string, string> = {
  sma: 'Simple moving average',
  ema: 'Exponential moving average',
  rsi: 'RSI',
  average_volume: 'Average volume',
  prior_high: 'Prior highest price',
  prior_low: 'Prior lowest price',
  number: 'Fixed value',
  gt: 'is above',
  gte: 'is at least',
  lt: 'is below',
  lte: 'is at most',
  crosses_above: 'crosses above',
  crosses_below: 'crosses below',
}
function OperandEditor({
  value,
  onChange,
  label,
}: {
  value: Operand
  onChange: (o: Operand) => void
  label: string
}) {
  const period = ['sma', 'ema', 'rsi', 'average_volume', 'prior_high', 'prior_low'].includes(
    value.kind
  )
  return (
    <div className="flex flex-wrap gap-2 flex-1">
      <select
        aria-label={label}
        className="rounded border bg-background p-2 max-w-full"
        value={value.kind}
        onChange={(e) =>
          onChange({
            kind: e.target.value,
            ...(e.target.value === 'number'
              ? { value: 50 }
              : ['sma', 'ema', 'rsi', 'average_volume', 'prior_high', 'prior_low'].includes(
                    e.target.value
                  )
                ? { period: 20 }
                : {}),
          })
        }
      >
        {kinds.map((k) => (
          <option key={k} value={k}>
            {labels[k] || k}
          </option>
        ))}
      </select>
      {(period || value.kind === 'number') && (
        <input
          aria-label={label + (period ? ' periods' : ' value')}
          className="rounded border bg-background p-2 w-20"
          type="number"
          min={period ? 2 : undefined}
          max={period ? 250 : undefined}
          value={period ? value.period : value.value}
          onChange={(e) =>
            onChange({ ...value, [period ? 'period' : 'value']: Number(e.target.value) })
          }
        />
      )}
    </div>
  )
}
function Rules({
  value,
  onChange,
  depth = 0,
}: {
  value: Group
  onChange: (g: Group) => void
  depth?: number
}) {
  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex gap-3 items-center">
        <span className="text-sm">Match</span>
        <select
          aria-label="Rule group match"
          value={value.op}
          onChange={(e) => onChange({ ...value, op: e.target.value as Group['op'] })}
          className="rounded border bg-background p-2"
        >
          <option value="all">ALL conditions</option>
          <option value="any">ANY condition</option>
        </select>
      </div>
      {value.conditions.map((c, i) => (
        <div key={i} className="flex gap-2 items-start">
          <div className="flex-1 min-w-0">
            {'conditions' in c ? (
              <Rules
                depth={depth + 1}
                value={c}
                onChange={(next) =>
                  onChange({
                    ...value,
                    conditions: value.conditions.map((v, j) => (j === i ? next : v)),
                  })
                }
              />
            ) : (
              <div className="flex flex-wrap gap-2">
                <OperandEditor
                  label={'Condition ' + (i + 1) + ' left'}
                  value={c.left}
                  onChange={(o) =>
                    onChange({
                      ...value,
                      conditions: value.conditions.map((v, j) => (j === i ? { ...c, left: o } : v)),
                    })
                  }
                />
                <select
                  aria-label={'Condition ' + (i + 1) + ' comparison'}
                  className="rounded border bg-background p-2"
                  value={c.op}
                  onChange={(e) =>
                    onChange({
                      ...value,
                      conditions: value.conditions.map((v, j) =>
                        j === i ? { ...c, op: e.target.value } : v
                      ),
                    })
                  }
                >
                  {['gt', 'gte', 'lt', 'lte', 'crosses_above', 'crosses_below'].map((o) => (
                    <option key={o} value={o}>
                      {labels[o]}
                    </option>
                  ))}
                </select>
                <OperandEditor
                  label={'Condition ' + (i + 1) + ' right'}
                  value={c.right}
                  onChange={(o) =>
                    onChange({
                      ...value,
                      conditions: value.conditions.map((v, j) =>
                        j === i ? { ...c, right: o } : v
                      ),
                    })
                  }
                />
              </div>
            )}
          </div>
          <button
            className="sw-button"
            aria-label={'Remove condition ' + (i + 1)}
            disabled={value.conditions.length === 1}
            onClick={() =>
              onChange({ ...value, conditions: value.conditions.filter((_, j) => j !== i) })
            }
          >
            ×
          </button>
        </div>
      ))}
      <div className="flex gap-2">
        <button
          className="sw-button"
          disabled={value.conditions.length >= 8}
          onClick={() => onChange({ ...value, conditions: [...value.conditions, condition()] })}
        >
          + Condition
        </button>
        {depth === 0 && (
          <button
            className="sw-button"
            disabled={value.conditions.length >= 8}
            onClick={() =>
              onChange({
                ...value,
                conditions: [...value.conditions, { op: 'any', conditions: [condition()] }],
              })
            }
          >
            + Group
          </button>
        )}
      </div>
    </div>
  )
}
function describe(g: Group): string {
  return g.conditions
    .map((c) =>
      'conditions' in c
        ? '(' + describe(c) + ')'
        : `${labels[c.left.kind] || c.left.kind}${c.left.period ? ' (' + c.left.period + ')' : c.left.kind === 'number' ? ' ' + c.left.value : ''} ${labels[c.op]} ${labels[c.right.kind] || c.right.kind}${c.right.period ? ' (' + c.right.period + ')' : c.right.kind === 'number' ? ' ' + c.right.value : ''}`
    )
    .join(g.op === 'all' ? ' AND ' : ' OR ')
}
function value(v: unknown) {
  return typeof v === 'number' && Number.isFinite(v) ? (v * 100).toFixed(2) + '%' : 'Not available'
}
export function ResearchWorkspace({
  asset,
  mode = 'systems',
}: {
  asset: 'stocks' | 'bitcoin'
  mode?: 'systems' | 'backtesting'
}) {
  const params = useSearchParams()
  const session = useOperator(),
    [data, setData] = useState<State>(initial),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false),
    [filter, setFilter] = useState('All'),
    [selected, setSelected] = useState(params.get('version') || ''),
    [compare, setCompare] = useState<string[]>([])
  const [editing, setEditing] = useState(false),
    [step, setStep] = useState(0),
    [draftId, setDraftId] = useState(''),
    [name, setName] = useState(''),
    [doc, setDoc] = useState<Document>(defaults(asset)),
    [confirm, setConfirm] = useState(''),
    [pending, setPending] = useState('')
  const [dates, setDates] = useState({
      start: new Date(Date.now() - 3 * 365 * 86400000).toISOString().slice(0, 10),
      end: new Date().toISOString().slice(0, 10),
    }),
    [cost, setCost] = useState(1)
  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/systems/workspace?asset=' + asset, { cache: 'no-store' })
      const d = await r.json()
      if (!r.ok) throw Error(d.error)
      setData(d)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Workspace unavailable')
    }
  }, [asset])
  useEffect(() => {
    void load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem('stockwatch-draft-' + asset)
      if (saved) {
        const d = JSON.parse(saved)
        setDoc(d.document)
        setName(d.name)
        setDraftId(d.id || '')
      }
    } catch {
      /* storage is optional */
    }
  }, [asset])
  useEffect(() => {
    if (!editing) return
    try {
      sessionStorage.setItem(
        'stockwatch-draft-' + asset,
        JSON.stringify({ name, document: doc, id: draftId })
      )
    } catch {
      /* draft stays in memory */
    }
  }, [doc, name, draftId, asset, editing])
  async function command(body: Record<string, unknown>) {
    setBusy(true)
    setNotice('')
    try {
      const r = await fetch('/api/systems/commands', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset, requestId: crypto.randomUUID(), ...body }),
      })
      const d = await r.json()
      if (!r.ok) throw Error(d.error)
      setNotice(
        d.status === 'saved'
          ? 'Draft saved. Publishing creates an immutable version.'
          : 'Command queued. Follow its result in Activity below.'
      )
      await load()
      return d
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Command failed')
      return null
    } finally {
      setBusy(false)
    }
  }
  async function save(publish = false) {
    const d = await command({ action: 'save_draft', id: draftId || undefined, name, document: doc })
    if (d) {
      setDraftId(d.id)
      if (publish) await command({ action: 'publish', draft: d.id })
    }
  }
  function edit(d?: Draft) {
    setEditing(true)
    setStep(0)
    if (d) {
      setName(d.name)
      setDoc(d.document)
      setDraftId(d.id)
    }
  }
  const label = (v: Version) =>
    v.hypothesis?.startsWith('Frozen baseline') ||
    v.hypothesis?.startsWith('Hourly automation copy')
      ? (v.template === 'trend' ? 'Moving-average trend' : 'Price breakout') +
        (v.config.protocol === 'visual-rules-v1' ? '' : ' · Baseline')
      : v.hypothesis || v.template
  const state = (v: Version) => {
    if (v.archived) return 'Archived'
    const dep = data.deployments.find((d) => d.version_id === v.id),
      a = data.allocations.find((a) => a.version_id === v.id),
      q = data.qualifications.find((q) => q.version_id === v.id),
      e = data.enrollments.find((e) => e.version_id === v.id)
    return dep?.mode === 'paused' || e?.paused
      ? 'Paused'
      : dep?.mode === 'paper' || a?.started_at
        ? 'Running'
        : q?.status === 'qualified'
          ? 'Ready for paper'
          : dep || e
            ? 'Research'
            : 'Ideas'
  }
  const chosen = data.versions.find((v) => v.id === selected),
    disabled = !session.authenticated || busy
  return (
    <main className="space-y-6">
      <PageHeader
        title={mode === 'systems' ? 'Systems library' : 'Backtesting'}
        description={
          mode === 'systems'
            ? 'Turn an idea into rules, test the evidence, and decide when to start paper trading.'
            : 'Test a frozen system version against historical data. Compare outcomes, costs, and limitations.'
        }
        action={
          mode === 'systems' ? (
            <button className="sw-button primary" onClick={() => edit()}>
              Create a system
            </button>
          ) : (
            <Link
              className="sw-button"
              href={'/systems' + (asset === 'bitcoin' ? '?asset=bitcoin' : '')}
            >
              Open systems library
            </Link>
          )
        }
      />
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
        <p className="sw-muted">
          Read-only workspace. Sign in through the header to save drafts or request research.
        </p>
      )}
      {mode === 'systems' && (
        <>
          <div className="sw-tabs" aria-label="System lifecycle">
            {['All', 'Ideas', 'Research', 'Ready for paper', 'Running', 'Paused', 'Archived'].map(
              (f) => (
                <button
                  aria-pressed={filter === f}
                  className="sw-button"
                  key={f}
                  onClick={() => setFilter(f)}
                >
                  {f}
                </button>
              )
            )}
          </div>
          {!editing && (
            <div className="sw-grid">
              {!data.versions.length && !data.drafts.length && (
                <p className="sw-empty">
                  Create your first system to turn an idea into testable rules. Saving a draft never
                  starts trading.
                </p>
              )}
              {data.drafts
                .filter((d) =>
                  filter === 'Archived'
                    ? d.archived
                    : !d.archived &&
                      !d.published_version &&
                      (filter === 'All' || filter === 'Ideas')
                )
                .map((d) => (
                  <article className="sw-panel" key={d.id}>
                    <span className="sw-badge">{d.archived ? 'Archived' : 'Draft'}</span>
                    <h2 className="mt-4">{d.name}</h2>
                    <p className="sw-muted my-4">Editable idea · No trading authorization</p>
                    <div className="flex gap-2">
                      <button className="sw-button" onClick={() => edit(d)}>
                        Edit draft
                      </button>
                      <button
                        className="sw-button"
                        disabled={disabled}
                        onClick={() =>
                          command({ action: 'archive', id: d.id, archived: !d.archived })
                        }
                      >
                        {d.archived ? 'Restore' : 'Archive'}
                      </button>
                    </div>
                  </article>
                ))}
              {data.versions
                .filter((v) => (filter === 'All' ? !v.archived : state(v) === filter))
                .map((v) => (
                  <article className="sw-panel" key={v.id}>
                    <div className="flex justify-between gap-2">
                      <span className="sw-badge">{state(v)}</span>
                      <span className="sw-muted">{v.config.timeframe || 'Daily'}</span>
                    </div>
                    <h2 className="mt-4">{label(v)}</h2>
                    <p className="sw-muted my-3">
                      {v.config.entry_rules
                        ? describe(v.config.entry_rules)
                        : v.template === 'trend'
                          ? 'Moving-average crossover'
                          : 'Price breakout'}{' '}
                      · Version {v.id.slice(0, 8)}
                    </p>
                    <div className="flex gap-2 flex-wrap">
                      <button className="sw-button" onClick={() => setSelected(v.id)}>
                        Details & next steps
                      </button>
                      <Link
                        className="sw-button"
                        href={'/backtesting?asset=' + asset + '&version=' + v.id}
                      >
                        Backtest
                      </Link>
                      {v.config.entry_rules && (
                        <button
                          className="sw-button"
                          onClick={() => {
                            setDoc(v.config)
                            setName(label(v) + ' copy')
                            setDraftId('')
                            setEditing(true)
                          }}
                        >
                          Duplicate
                        </button>
                      )}
                    </div>
                  </article>
                ))}
            </div>
          )}
          {editing && (
            <section className="sw-panel">
              <div className="sw-panel-heading">
                <div>
                  <h2>{draftId ? 'Edit draft' : 'Create a system'}</h2>
                  <p>Drafts do not trade. Published versions are immutable.</p>
                </div>
                <button className="sw-button" onClick={() => setEditing(false)}>
                  Close editor
                </button>
              </div>
              <div className="sw-stepper">
                {['Basics', 'Entry rules', 'Exit & risk', 'Review'].map((s, i) => (
                  <button
                    key={s}
                    aria-current={step === i ? 'step' : undefined}
                    onClick={() => setStep(i)}
                  >
                    {i + 1}. {s}
                  </button>
                ))}
              </div>
              {step === 0 && (
                <div className="grid sm:grid-cols-2 gap-5">
                  <label className="sw-field">
                    System name
                    <input
                      value={name}
                      maxLength={120}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="e.g. Patient momentum"
                    />
                  </label>
                  <label className="sw-field">
                    Decision timeframe
                    <select
                      value={doc.timeframe}
                      onChange={(e) => setDoc({ ...doc, timeframe: e.target.value })}
                    >
                      {(asset === 'stocks' ? ['1Day'] : frames).map((f) => (
                        <option key={f}>{f}</option>
                      ))}
                    </select>
                    <small>Rules evaluate completed bars. Stocks retain daily decisions.</small>
                  </label>
                </div>
              )}
              {step === 1 && (
                <>
                  <p className="sw-muted mb-4">
                    Enter when these conditions match. Indicators use completed bars; prior
                    highs/lows exclude the deciding bar. At most eight conditions.
                  </p>
                  <Rules
                    value={doc.entry_rules}
                    onChange={(entry_rules) => setDoc({ ...doc, entry_rules })}
                  />
                </>
              )}
              {step === 2 && (
                <>
                  <Rules
                    value={doc.exit_rules}
                    onChange={(exit_rules) => setDoc({ ...doc, exit_rules })}
                  />
                  <div className="grid sm:grid-cols-3 gap-4 mt-5">
                    {[
                      ['allocation', 'Position size (%)'],
                      ['stop_loss', 'Stop loss (%)'],
                      ['take_profit', 'Take profit (%)'],
                    ].map(([key, title]) => (
                      <label className="sw-field" key={key}>
                        {title}
                        <input
                          type="number"
                          min={1}
                          max={key === 'allocation' && asset === 'bitcoin' ? 50 : 100}
                          value={Math.round(Number(doc[key as keyof Document]) * 100)}
                          onChange={(e) => setDoc({ ...doc, [key]: Number(e.target.value) / 100 })}
                        />
                      </label>
                    ))}
                    <label className="sw-field">
                      Maximum holding period
                      <input
                        type="number"
                        min={1}
                        max={365}
                        value={doc.holding_count}
                        onChange={(e) => setDoc({ ...doc, holding_count: Number(e.target.value) })}
                      />
                    </label>
                    <label className="sw-field">
                      Holding unit
                      <select
                        value={doc.holding_unit}
                        onChange={(e) => setDoc({ ...doc, holding_unit: e.target.value })}
                      >
                        {['minutes', 'hours', 'days', 'weeks', 'months'].map((u) => (
                          <option key={u}>{u}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <p className="sw-muted mt-4">
                    Account-wide limits still apply. Stock exits evaluate completed daily bars and
                    execute near the next session close. Crypto monitors available quotes. Stops
                    request an exit; they do not guarantee a fill price.
                  </p>
                </>
              )}
              {step === 3 && (
                <div className="space-y-4">
                  <h3 className="text-lg">{name || 'Name your system'}</h3>
                  <p>Enter: {describe(doc.entry_rules)}.</p>
                  <p>Exit: {describe(doc.exit_rules)}.</p>
                  <p className="sw-muted">
                    Maximum position {doc.allocation * 100}% · Stop {doc.stop_loss * 100}% · Target{' '}
                    {doc.take_profit * 100}% · Hold at most {doc.holding_count} {doc.holding_unit}.
                    Publishing does not authorize trading.
                  </p>
                </div>
              )}
              <div className="flex gap-3 flex-wrap mt-6">
                <button
                  className="sw-button"
                  disabled={step === 0}
                  onClick={() => setStep(step - 1)}
                >
                  Back
                </button>
                {step < 3 ? (
                  <button className="sw-button primary" onClick={() => setStep(step + 1)}>
                    Continue
                  </button>
                ) : (
                  <button
                    className="sw-button primary"
                    disabled={disabled || !name.trim()}
                    onClick={() => save(true)}
                  >
                    Save & publish version
                  </button>
                )}
                <button
                  className="sw-button"
                  disabled={disabled || !name.trim()}
                  onClick={() => save()}
                >
                  Save draft
                </button>
              </div>
            </section>
          )}
          {chosen && (
            <section className="sw-panel">
              <div className="sw-panel-heading">
                <div>
                  <h2>{label(chosen)}</h2>
                  <p>
                    {state(chosen)} · Version <span className="break-all">{chosen.id}</span>
                  </p>
                </div>
                <button className="sw-button" onClick={() => setSelected('')}>
                  Close details
                </button>
              </div>
              <p className="sw-notice mb-4">
                {data.qualifications.find((q) => q.version_id === chosen.id)?.reason ||
                  'Backtest this version, start forward observation, and review account readiness before paper activation. Existing stock systems require 20 observed sessions; Crypto requires 30 forward days and its qualification checks.'}
              </p>
              {chosen.config.entry_rules && (
                <button
                  className="sw-button mb-4 mr-3"
                  onClick={() => {
                    setName(label(chosen))
                    setDoc(chosen.config)
                    setDraftId(chosen.draft_id || '')
                    setStep(0)
                    setEditing(true)
                  }}
                >
                  Edit next version
                </button>
              )}
              <details className="mb-5">
                <summary>Published version history</summary>
                <ul className="sw-muted mt-3">
                  {data.versions
                    .filter(
                      (v) =>
                        v.id === chosen.id || (chosen.draft_id && v.draft_id === chosen.draft_id)
                    )
                    .map((v) => (
                      <li key={v.id}>
                        <button className="underline" onClick={() => setSelected(v.id)}>
                          {label(v)} · {v.id.slice(0, 8)} ·{' '}
                          {new Date(v.created_at).toLocaleDateString()}
                        </button>
                      </li>
                    ))}
                </ul>
              </details>
              <button
                className="sw-button mb-4"
                disabled={disabled}
                onClick={() =>
                  command({ action: 'archive_version', id: chosen.id, archived: !chosen.archived })
                }
              >
                {chosen.archived ? 'Restore version' : 'Archive version'}
              </button>
              <div className="flex gap-3 flex-wrap">
                <button
                  disabled={disabled}
                  className="sw-button"
                  onClick={() => command({ action: 'observe', version: chosen.id })}
                >
                  Start observation
                </button>
                <button
                  disabled={disabled}
                  className="sw-button"
                  onClick={() => {
                    setPending('start_paper')
                    setConfirm('')
                  }}
                >
                  Review paper start
                </button>
                <button
                  disabled={disabled}
                  className="sw-button"
                  onClick={() => command({ action: 'pause', version: chosen.id })}
                >
                  Pause
                </button>
                <button
                  disabled={disabled}
                  className="sw-button"
                  onClick={() => {
                    setPending('resume')
                    setConfirm('')
                  }}
                >
                  Review resume
                </button>
                {asset === 'bitcoin' && (
                  <Link className="sw-button" href="/systems?asset=bitcoin&advanced=1">
                    Account setup & evidence
                  </Link>
                )}
              </div>
              {pending && (
                <form
                  className="sw-notice mt-5"
                  onSubmit={(e) => {
                    e.preventDefault()
                    void command({ action: pending, version: chosen.id, confirmation: confirm })
                    setPending('')
                  }}
                >
                  <strong>
                    {pending === 'start_paper'
                      ? 'Start this exact version in paper trading'
                      : 'Resume this exact version'}
                  </strong>
                  <p className="my-3">
                    The worker rechecks evidence, account identity, funding, reconciliation, and
                    risk before accepting. This request does not bypass any prerequisite. Existing
                    positions retain their owners.
                  </p>
                  <label className="sw-field">
                    Type the full version ID
                    <input
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                      autoComplete="off"
                    />
                  </label>
                  <button
                    className="sw-button primary mt-3"
                    disabled={disabled || confirm !== chosen.id}
                  >
                    Confirm request
                  </button>
                </form>
              )}
            </section>
          )}
        </>
      )}
      {mode === 'backtesting' && (
        <section className="sw-panel">
          <div className="sw-panel-heading">
            <div>
              <h2>Run a historical backtest</h2>
              <p className="sw-muted mt-3">
                {data.datasets.length
                  ? `Latest saved coverage: ${data.datasets[0].manifest.actual_start?.slice(0, 10) || 'unknown'} to ${data.datasets[0].manifest.actual_end?.slice(0, 10) || 'unknown'} · ${data.datasets[0].manifest.fidelity || 'See source evidence'}`
                  : asset === 'bitcoin'
                    ? 'No saved historical dataset yet. The worker will collect available provider bars for your interval.'
                    : 'No saved historical dataset yet. The worker will use captured daily stock bars, sectors, and market sessions.'}{' '}
                Indicators need warmup bars within the selected interval. Missing coverage is
                reported by the job.
              </p>
              <p>
                Historical exploration is separate from qualification. Dataset coverage and
                limitations are retained with the result.
              </p>
            </div>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void command({
                action: 'backtest',
                version: selected,
                start: dates.start + 'T00:00:00Z',
                end: dates.end + 'T00:00:00Z',
                costMultiplier: cost,
              })
            }}
            className="space-y-5"
          >
            <label className="sw-field">
              System version
              <select required value={selected} onChange={(e) => setSelected(e.target.value)}>
                <option value="">Choose a published version</option>
                {data.versions.map((v) => (
                  <option value={v.id} key={v.id}>
                    {label(v)} · {v.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid sm:grid-cols-2 gap-4">
              <label className="sw-field">
                From
                <input
                  required
                  type="date"
                  value={dates.start}
                  onChange={(e) => setDates({ ...dates, start: e.target.value })}
                />
              </label>
              <label className="sw-field">
                To
                <input
                  required
                  type="date"
                  value={dates.end}
                  max={new Date().toISOString().slice(0, 10)}
                  onChange={(e) => setDates({ ...dates, end: e.target.value })}
                />
              </label>
            </div>
            <details>
              <summary>Advanced assumptions</summary>
              <label className="sw-field mt-4">
                Execution cost stress
                <select value={cost} onChange={(e) => setCost(Number(e.target.value))}>
                  <option value={1}>Base</option>
                  <option value={2}>Double slippage</option>
                  <option value={3}>Triple slippage</option>
                </select>
              </label>
              <p className="sw-muted mt-3">
                Starts with a closed $300 research cash pool. Stock results include captured SPY
                price return when available. Crypto uses the selected decision timeframe. Large
                intraday requests are bounded; shorten the interval if collection reaches its limit.
              </p>
            </details>
            <button className="sw-button primary" disabled={disabled || !selected}>
              Prepare data & run backtest
            </button>
          </form>
        </section>
      )}
      <section className="sw-panel">
        <div className="sw-panel-heading">
          <div>
            <h2>Research results</h2>
            <p>
              Latest 20 runs. Select up to four to compare. Missing results are never shown as zero.
            </p>
          </div>
          <Link className="sw-button" href="/backtests">
            Historical stock experiments
          </Link>
        </div>
        {!data.runs.length ? (
          <p className="sw-empty">
            No backtests yet. Publish a system and choose a historical interval to get started.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th>Compare</th>
                  <th>System</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {data.runs.map((r) => (
                  <tr key={r.id} className="border-t">
                    <td className="p-3">
                      <input
                        aria-label={'Compare run ' + r.id.slice(0, 8)}
                        type="checkbox"
                        checked={compare.includes(r.id)}
                        disabled={!compare.includes(r.id) && compare.length >= 4}
                        onChange={() =>
                          setCompare(
                            compare.includes(r.id)
                              ? compare.filter((id) => id !== r.id)
                              : [...compare, r.id]
                          )
                        }
                      />
                    </td>
                    <td>
                      {data.versions.find((v) => v.id === r.version_id)?.hypothesis?.slice(0, 45) ||
                        r.version_id.slice(0, 8)}
                    </td>
                    <td>
                      {r.status}
                      {r.error && <p className="sw-muted">{r.error}</p>}
                    </td>
                    <td>{r.progress}%</td>
                    <td>
                      {['queued', 'running'].includes(r.status) && (
                        <button
                          className="sw-button"
                          disabled={disabled}
                          onClick={() => command({ action: 'cancel', id: r.id })}
                        >
                          Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="grid lg:grid-cols-2 gap-5 mt-5">
          {data.runs
            .filter((r) => compare.includes(r.id))
            .map((r) => (
              <Result key={r.id} run={r} />
            ))}
        </div>
      </section>
      <section className="sw-panel">
        <div className="sw-panel-heading">
          <h2>Activity</h2>
          <span className="sw-muted">Latest 60 requests</span>
        </div>
        {data.jobs.length ? (
          data.jobs.map((j) => (
            <div key={j.id} className="border-t py-3 flex justify-between items-start gap-3">
              <div>
                <strong className="text-sm">
                  {j.kind.replaceAll('_', ' ')} · {j.status}
                </strong>
                <p className="sw-muted">
                  {new Date(j.created_at).toLocaleString()}
                  {j.error ? ' · ' + j.error : ''}
                </p>
              </div>
              {j.kind === 'backtest' && ['queued', 'running'].includes(j.status) && (
                <button
                  className="sw-button"
                  disabled={disabled}
                  onClick={() => command({ action: 'cancel', id: j.id })}
                >
                  Cancel
                </button>
              )}
            </div>
          ))
        ) : (
          <p className="sw-muted">Your saved commands and worker outcomes will appear here.</p>
        )}
      </section>
      <p className="sw-muted">
        <Link className="underline" href={'/systems?asset=' + asset + '&legacy=1'}>
          Earlier research and deployments
        </Link>{' '}
        remain available with their original history.
      </p>
    </main>
  )
}
function Result({ run }: { run: Run }) {
  const result = run.result,
    summary = (result.base || result.summary || result.full || {}) as Record<string, unknown>
  return (
    <article className="rounded-lg border p-4">
      <h3 className="font-medium mb-4">
        Run {run.id.slice(0, 8)} · {run.status}
      </h3>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="sw-muted">Net return</p>
          <strong>{value(summary.net_return)}</strong>
        </div>
        <div>
          <p className="sw-muted">Maximum drawdown</p>
          <strong>
            {value(summary.maximum_drawdown ?? summary.max_drawdown ?? summary.drawdown)}
          </strong>
        </div>
      </div>
      <p className="sw-muted mt-3">
        Net return includes modeled costs. Drawdown measures the largest decline from a previous
        portfolio peak.
      </p>
      <div className="grid grid-cols-2 gap-4 my-4">
        <div>
          <p className="sw-muted">Closed trades</p>
          <strong>{String(summary.closed_trades ?? 'Not available')}</strong>
        </div>
        <div>
          <p className="sw-muted">Fees</p>
          <strong>
            {typeof summary.fees === 'number' ? '$' + summary.fees.toFixed(2) : 'Not available'}
          </strong>
        </div>
      </div>
      <SystemEquityChart points={summary.curve || summary.equity_curve} />
      <p className="sw-muted mt-3">
        {Array.isArray(result.limitations)
          ? result.limitations.join(' · ')
          : 'Historical simulation does not qualify a system for paper trading.'}
      </p>
      <div className="my-4">
        <h4 className="text-sm font-medium">Benchmarks</h4>
        {result.benchmarks && typeof result.benchmarks === 'object' ? (
          Object.entries(result.benchmarks).map(([name, metric]) => (
            <p key={name} className="sw-muted">
              {name}: {value(metric)}
            </p>
          ))
        ) : (
          <p className="sw-muted">No compatible benchmark recorded.</p>
        )}
      </div>
      <details className="my-4">
        <summary>Modeled fills</summary>
        <div className="overflow-auto max-h-64">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th>Time</th>
                <th>Side</th>
                <th>Symbol</th>
                <th>Price</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {Array.isArray(summary.fills) &&
                summary.fills.slice(0, 200).map((f: Record<string, unknown>, i: number) => (
                  <tr key={i}>
                    <td>{String(f.at)}</td>
                    <td>{String(f.side)}</td>
                    <td>{String(f.symbol)}</td>
                    <td>{Number(f.price).toFixed(2)}</td>
                    <td>{String(f.reason)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <p className="sw-muted">First 200 fills. Complete evidence remains in the saved run.</p>
      </details>
      <details className="mt-4 text-sm">
        <summary>Result preview and limitations</summary>
        <pre className="whitespace-pre-wrap break-words text-xs mt-3 max-h-80 overflow-auto">
          {JSON.stringify(result, null, 2)}
        </pre>
      </details>
    </article>
  )
}
