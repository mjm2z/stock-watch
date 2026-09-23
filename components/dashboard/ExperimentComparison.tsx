'use client'
import { useState } from 'react'
import { formatTimestamp } from '@/lib/utils'
type Row = Record<string, unknown>
const variants: Record<string, string> = {
  'baseline-v1': 'Baseline weights and data checks',
  'horizon-weights-v1': 'Horizon-specific weights',
  'without-news-v1': 'Without news',
}
const percent = (n: unknown) =>
  n == null ? 'Awaiting outcomes' : `${(Number(n) * 100).toFixed(2)}%`
export function ExperimentComparison({ rows }: { rows: Row[] }) {
  const strategies = Array.from(new Set(rows.map((r) => String(r.strategy))))
  const [strategy, setStrategy] = useState(strategies[0] ?? ''),
    [horizon, setHorizon] = useState('5')
  const filtered = rows.filter(
    (r) => String(r.strategy) === strategy && String(r.horizon) === horizon
  )
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          Strategy
          <select
            className="mt-1 block min-h-11 w-full rounded border bg-background p-2"
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
          >
            {strategies.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Holding period
          <select
            className="mt-1 block min-h-11 w-full rounded border bg-background p-2"
            value={horizon}
            onChange={(e) => setHorizon(e.target.value)}
          >
            {[5, 21, 63, 105].map((n) => (
              <option key={n} value={n}>
                {n} trading days
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-sm text-muted-foreground">
        {filtered.some((r) => Number(r.matured) < 30)
          ? 'Early sample: at least one variant has fewer than 30 completed outcomes.'
          : 'Descriptive results: further validation is required.'}{' '}
        Repeated companies and overlapping periods are correlated.
      </p>
      {!filtered.length && <p className="text-sm">No observations for this selection yet.</p>}
      <div className="grid gap-3 lg:grid-cols-3">
        {filtered.map((r, i) => (
          <article key={i} className="space-y-3 rounded-lg border p-4">
            <h3 className="font-semibold">{variants[String(r.variant)] ?? String(r.variant)}</h3>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              {[
                ['Scored observations', r.observations],
                ['Companies', r.companies],
                ['Qualified', r.qualified],
                ['Completed outcomes', r.matured],
                ['Average modeled net return', percent(r.net_return)],
                ['Excess versus SPY', percent(r.excess_return)],
                ['Beat SPY', percent(r.beat_spy)],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <dt className="text-xs text-muted-foreground">{String(label)}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
            </dl>
            <details className="text-sm">
              <summary>Window and configuration</summary>
              <p className="mt-2 text-xs">
                {formatTimestamp(String(r.first_at))} – {formatTimestamp(String(r.last_at))} ET
              </p>
              <pre className="mt-2 whitespace-pre-wrap break-all text-xs">
                {String(r.config_json)}
              </pre>
            </details>
          </article>
        ))}
      </div>
    </div>
  )
}
