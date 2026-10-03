'use client'
import { useEffect, useState } from 'react'
import { useOperator } from './OperatorSession'
import { SystemEquityChart } from './dashboard/SystemEquityChart'
type Row = Record<string, any>
const labels: Record<string, string> = {
  queued: 'Queued',
  baseline: 'Running StockWatch baseline',
  transferring: 'Transferring inputs',
  lean: 'Running LEAN',
  comparing: 'Comparing evidence',
  complete: 'Complete',
  failed: 'Failed',
  canceled: 'Canceled',
}
function jobId() {
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 15) | 64
  b[8] = (b[8] & 63) | 128
  const s = Array.from(b, (n) => n.toString(16).padStart(2, '0')).join('')
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`
}
function obj(value: unknown): Row {
  try {
    return typeof value === 'string' ? JSON.parse(value) : value || {}
  } catch {
    return {}
  }
}
export function LeanValidation({ versions, datasets }: { versions: Row[]; datasets: Row[] }) {
  const operator = useOperator()
  const [state, setState] = useState<Row>({ health: { configured: false }, runs: [] })
  const [version, setVersion] = useState(''),
    [dataset, setDataset] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [preview, setPreview] = useState(false)
  const [draftId, setDraftId] = useState('')
  const [selected, setSelected] = useState(''),
    [detail, setDetail] = useState<Row>({}),
    [page, setPage] = useState(0),
    [differences, setDifferences] = useState<Row[]>([])
  const choices = versions.filter(
    (v) => v.asset === 'bitcoin' && v.template === 'trend' && !obj(v.config_json).protocol
  )
  const sources = datasets.filter(
    (d) => d.asset === 'bitcoin' && obj(d.manifest_json).timeframe === '1Hour'
  )
  async function refresh() {
    try {
      const r = await fetch('/api/lean', { cache: 'no-store' })
      const b = await r.json()
      if (!r.ok) throw Error(b.error)
      setState(b)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'LEAN unavailable')
    }
  }
  useEffect(() => {
    void refresh()
    const timer = setInterval(refresh, 10000)
    return () => clearInterval(timer)
  }, [])
  const selectedStatus = state.runs.find((r: Row) => r.id === selected)?.status
  useEffect(() => {
    if (!selected) return
    setDetail({})
    setDifferences([])
    const controller = new AbortController()
    fetch(`/api/lean/${selected}`, { signal: controller.signal })
      .then(async (r) => {
        const b = await r.json()
        if (!r.ok) throw Error(b.error)
        setDetail(b)
        setDifferences(b.summary?.differences || [])
        setPage(0)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message)
      })
    return () => controller.abort()
  }, [selected, selectedStatus])
  async function mutate(action: string, id: string) {
    setBusy(true)
    setError('')
    try {
      const r = await fetch('/api/lean', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, id, version, dataset }),
      })
      const b = await r.json()
      if (!r.ok) throw Error(b.error)
      setPreview(false)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }
  async function changePage(next: number) {
    try {
      const r = await fetch(`/api/lean/${selected}?page=${next}`)
      const b = await r.json()
      if (!r.ok) throw Error(b.error)
      setDifferences(b.differences)
      setPage(next)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Evidence unavailable')
    }
  }
  const healthy = state.health?.healthy && !state.health?.stale
  const summary = detail.summary
  return (
    <section className="sw-panel" aria-label="LEAN validation">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Validate with LEAN</h2>
          <p className="sw-muted">Independent Bitcoin trend replay · Research only</p>
        </div>
        <span className="sw-muted" role="status">
          {!state.health?.configured
            ? 'Runner not configured'
            : healthy
              ? 'Runner available'
              : 'Runner unavailable or stale'}
        </span>
      </div>
      <p className="sw-muted mt-3">
        Compare the original hourly Bitcoin trend template using the same retained data and
        assumptions. Agreement does not qualify or activate a system.
      </p>
      <div className="grid sm:grid-cols-2 gap-3 mt-4">
        <label>
          System version
          <select
            className="block w-full mt-1"
            aria-label="LEAN system version"
            value={version}
            onChange={(e) => {
              setVersion(e.target.value)
              setPreview(false)
            }}
          >
            <option value="">Choose Bitcoin trend</option>
            {choices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.template} · {String(v.id).slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Dataset
          <select
            className="block w-full mt-1"
            aria-label="LEAN dataset"
            value={dataset}
            onChange={(e) => {
              setDataset(e.target.value)
              setPreview(false)
            }}
          >
            <option value="">Choose hourly Bitcoin data</option>
            {sources.map((d) => (
              <option key={d.id} value={d.id}>
                {String(d.id).slice(0, 8)} · {obj(d.manifest_json).actual_start} –{' '}
                {obj(d.manifest_json).actual_end}
              </option>
            ))}
          </select>
        </label>
      </div>
      {(!choices.length || !sources.length) && (
        <p className="sw-muted mt-2">
          Create an original Bitcoin trend version and collect an hourly dataset using the existing
          research controls first. Visual and automated-protocol versions are not supported in this
          first adapter.
        </p>
      )}
      <button
        className="sw-button mt-3"
        disabled={!operator.authenticated || !healthy || !version || !dataset || busy}
        onClick={() => {
          setDraftId(jobId())
          setPreview(true)
        }}
      >
        Preview comparison
      </button>
      {preview && (
        <div className="rounded-lg border p-4 mt-3">
          <h3 className="font-medium">Comparison assumptions</h3>
          <p className="sw-muted">
            $300 starting cash · Full retained dataset interval · No parameter optimization ·
            Completed-hour decisions and subsequent quotes · Dataset fees, slippage and drawdown
            rules retained. Historical prices may be synthetic execution proxies.
          </p>
          <p className="sw-muted mt-2">
            Selected versions and dataset hashes are frozen. Unsupported execution features will
            fail explicitly. This does not submit paper or live orders.
          </p>
          <button
            className="sw-button mt-3"
            disabled={busy}
            onClick={() => void mutate('create', draftId)}
          >
            Run comparison
          </button>
          <button className="sw-button ml-2" onClick={() => setPreview(false)}>
            Cancel
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="sw-notice mt-3">
          {error}
        </p>
      )}
      <div className="mt-4 divide-y">
        {state.runs.map((run: Row) => (
          <div key={run.id} className="py-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <button className="text-primary text-left" onClick={() => setSelected(run.id)}>
                Comparison {run.id.slice(0, 8)}
              </button>
              <p className="sw-muted">
                {labels[run.status] || run.status} · {new Date(run.created_at).toLocaleString()}
                {run.started_at && !run.finished_at
                  ? ` · ${Math.max(0, Math.floor((Date.now() - Date.parse(run.started_at)) / 1000))}s elapsed`
                  : ''}
              </p>
              {run.error && <p className="sw-muted">{run.error}</p>}
            </div>
            {!['complete', 'failed', 'canceled'].includes(run.status) && (
              <button
                className="sw-button"
                disabled={!operator.authenticated || busy || run.cancel_requested}
                onClick={() => void mutate('cancel', run.id)}
              >
                {run.cancel_requested ? 'Cancel requested' : 'Cancel'}
              </button>
            )}
          </div>
        ))}
      </div>
      {summary && (
        <div className="mt-4 border-t pt-4">
          <h3 className="font-semibold">
            {summary.outcome === 'matched'
              ? 'Matched within tolerance'
              : summary.outcome === 'differences'
                ? 'Differences found'
                : 'Incomplete'}
          </h3>
          <p className="sw-muted">
            {summary.difference_count} differences · Money ±$0.01 · Quantity ±
            {summary.tolerances?.quantity} BTC · Drawdown ±1 basis point
          </p>
          <div className="grid lg:grid-cols-2 gap-5 mt-4">
            {['baseline', 'lean'].map((key) => (
              <div key={key}>
                <h4 className="font-medium">{key === 'baseline' ? 'StockWatch' : 'LEAN'}</h4>
                <p className="sw-muted">
                  Ending equity ${summary[key]?.ending_equity?.toFixed(2)} · Fees $
                  {summary[key]?.fees?.toFixed(2)} · Drawdown{' '}
                  {(100 * (summary[key]?.maximum_drawdown || 0)).toFixed(2)}% ·{' '}
                  {summary[key]?.fills_count} fills
                </p>
                <SystemEquityChart points={summary[key]?.equity_curve} />
              </div>
            ))}
          </div>
          {summary.first_divergence && (
            <p className="sw-notice">
              First divergence: {summary.first_divergence.kind}, row{' '}
              {summary.first_divergence.index ?? 'summary'}, {summary.first_divergence.field}
            </p>
          )}
          {!!differences.length && (
            <>
              <div className="overflow-x-auto mt-3">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th>Evidence</th>
                      <th>Row</th>
                      <th>Field</th>
                      <th>StockWatch</th>
                      <th>LEAN</th>
                    </tr>
                  </thead>
                  <tbody>
                    {differences.map((d, i) => (
                      <tr key={i}>
                        <td>{d.kind}</td>
                        <td>{d.index ?? '—'}</td>
                        <td>{d.field}</td>
                        <td>{String(d.stockwatch)}</td>
                        <td>{String(d.lean)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex gap-2 mt-2">
                <button
                  className="sw-button"
                  disabled={!detail.artifactsAvailable || page === 0}
                  onClick={() => void changePage(page - 1)}
                >
                  Previous
                </button>
                <span className="sw-muted">Page {page + 1}</span>
                <button
                  className="sw-button"
                  disabled={
                    !detail.artifactsAvailable ||
                    (page + 1) * 100 >= summary.stored_difference_count
                  }
                  onClick={() => void changePage(page + 1)}
                >
                  Next
                </button>
              </div>
            </>
          )}
          {detail.artifactsAvailable ? (
            <a className="sw-button inline-block mt-3" href={`/api/lean/${selected}?download=1`}>
              Download full comparison
            </a>
          ) : (
            <p className="sw-muted">Detailed artifacts expired; summary retained.</p>
          )}
          <p className="sw-muted mt-3 break-all">Engine image: {summary.image}</p>
          {summary.limitations?.map((text: string) => (
            <p key={text} className="sw-muted">
              {text}
            </p>
          ))}
        </div>
      )}
    </section>
  )
}
