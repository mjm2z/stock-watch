'use client'
import Link from 'next/link'
import { useState } from 'react'
import study from '@/lib/research/bitcoin-study-summary.json'

const percent = (n: number | null) => (n === null ? 'No closed trades' : `${(n * 100).toFixed(1)}%`)
export function BitcoinSystemResearch({ compact = false }: { compact?: boolean }) {
  const [period, setPeriod] = useState('2026 YTD')
  return (
    <section className="sw-panel space-y-5" aria-labelledby="bitcoin-systems-heading">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="sw-muted">BITCOIN / SYSTEM RESEARCH</p>
          <h2 id="bitcoin-systems-heading" className="mt-2">
            Compare ideas before committing capital
          </h2>
          <p className="sw-muted mt-2">
            Three researched rule sets · Daily decisions · Long-only · Historical simulations
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {compact && (
            <Link className="sw-button" href="/systems?asset=bitcoin">
              Your systems
            </Link>
          )}
          {compact && (
            <Link className="sw-button primary" href="/systems?asset=bitcoin&create=1">
              Create a system
            </Link>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm">
          Evaluation period
          <select
            className="rounded border bg-background p-2"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          >
            {study.systems[0].windows.map((w) => (
              <option key={w.label}>{w.label}</option>
            ))}
          </select>
        </label>
        <p className="sw-muted">10 runs per system = 5 periods × 2 cost assumptions</p>
      </div>
      <p className="text-sm text-muted-foreground">
        Win rate measures profitable closed trades, not the probability of future success. All three
        systems have fewer than 30 closed trades across the study.
      </p>
      <div className="space-y-3">
        {study.systems.map((system) => {
          const result = system.windows.find((w) => w.label === period)!
          return (
            <article className="rounded-lg border p-4 sm:p-5 space-y-4" key={system.id}>
              <div className="flex flex-wrap justify-between gap-3">
                <div>
                  <h3 className="font-semibold">{system.name}</h3>
                  <p className="sw-muted mt-1">
                    {system.family} · {system.backtest_count} backtests · {system.closed_trades}{' '}
                    total closed trades
                  </p>
                </div>
                <span className="sw-badge self-start">Limited evidence</span>
              </div>
              <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
                <Stat title={`${period} net return`} value={percent(result.net_return)} />
                <Stat title="Maximum drawdown" value={percent(result.maximum_drawdown)} />
                <Stat
                  title="Closed-trade win rate"
                  value={percent(result.win_rate)}
                  note={`${result.closed_trades} closed trades in this period`}
                />
                <Stat
                  title="Matched buy & hold"
                  value={percent(result.benchmark_return)}
                  note="25% BTC / 75% cash"
                />
              </div>
              <p className="text-sm">{system.rules}</p>
              <details className="text-sm">
                <summary className="cursor-pointer">Evidence, assumptions and source</summary>
                <div className="space-y-3 mt-4">
                  <p className="text-muted-foreground">{system.adaptation}</p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                    <Stat title="Double-cost return" value={percent(result.stress_return)} />
                    <Stat
                      title="Full BTC benchmark"
                      value={percent(result.btc_return)}
                      note="100% invested; different exposure"
                    />
                    <Stat
                      title="Profitable periods"
                      value={`${system.profitable_periods} / ${system.period_count}`}
                      note="Four full years and one YTD period"
                    />
                    <Stat
                      title="Pooled closed-trade wins"
                      value={percent(system.win_rate)}
                      note={`${system.closed_trades} trades; base runs only`}
                    />
                    <Stat
                      title="Win-rate 95% interval"
                      value={
                        result.win_rate_interval
                          ? `${percent(result.win_rate_interval.lower)}–${percent(result.win_rate_interval.upper)}`
                          : 'Insufficient trades'
                      }
                      note="Does not adjust for trade dependence"
                    />
                    <Stat
                      title="Risk pause reached"
                      value={result.risk_paused ? 'Yes · Entries stopped' : 'No'}
                    />
                  </div>
                  <p className="sw-muted">
                    Period: {result.start.slice(0, 10)} to {result.end.slice(0, 10)} ·{' '}
                    {result.open_positions} open position(s) at end · Open positions marked to
                    market, excluded from win rate.
                  </p>
                  <p className="sw-muted">{result.warnings.join(' · ')}</p>
                  <a
                    className="underline"
                    href={system.source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {system.source.title}
                  </a>
                  <p className="sw-muted break-all">Frozen version: {system.version}</p>
                </div>
              </details>
              <Link
                className="sw-button inline-flex"
                href={`/systems?asset=bitcoin&template=${system.id}`}
              >
                Use as an editable draft
              </Link>
            </article>
          )
        })}
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer">Study methodology and reproducible results</summary>
        <ul className="list-disc pl-5 mt-3 space-y-2 text-muted-foreground">
          {study.methodology.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
        <p className="sw-muted mt-3">
          Alpaca US · {study.coverage.bars.toLocaleString()} completed daily bars · Collected{' '}
          {study.collected_at.slice(0, 10)} · Fixed research snapshot, not live performance.
        </p>
        <a className="inline-block underline mt-3" href="/api/systems/research/bitcoin">
          Download all runs, fills, equity curves and input data (JSON)
        </a>
      </details>
    </section>
  )
}
function Stat({ title, value, note }: { title: string; value: string; note?: string }) {
  return (
    <div className="min-w-0">
      <p className="sw-muted">{title}</p>
      <p className="text-lg font-medium tabular-nums mt-1">{value}</p>
      {note && <p className="text-xs text-muted-foreground mt-1">{note}</p>}
    </div>
  )
}
