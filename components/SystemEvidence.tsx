'use client'
import Link from 'next/link'
import { BacktestCurve } from './BacktestCurve'
import { useState } from 'react'
import { ResearchActivity, pct, rate, money, color, outcome } from './ResearchActivity'
import { useOperator } from './OperatorSession'
function Evidence({ name, value }: { name: string; value: unknown }) {
  return (
    <details className="rounded border p-3">
      <summary className="cursor-pointer font-medium">{name}</summary>
      <pre className="text-xs whitespace-pre-wrap break-words mt-3 max-h-96 overflow-auto">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  )
}
export function SystemEvidence({ data: d }: { data: any }) {
  const session = useOperator(),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false)
  async function evaluate() {
    setBusy(true)
    try {
      const r = await fetch('/api/systems/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: 'evaluate',
            version: d.id,
            requestId: crypto.randomUUID(),
          }),
        }),
        v = await r.json()
      if (!r.ok) throw Error(v.error)
      setNotice(
        'Evaluation queued for the next discovery worker run. Track it under Research & automation.'
      )
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="sw-page space-y-6">
      <Link href={'/systems?asset=' + d.asset} className="underline">
        ← Systems
      </Link>
      <header>
        <h1>{d.hypothesis || 'System'}</h1>
        <p className="sw-muted">
          {d.asset === 'bitcoin' ? 'Crypto · Bitcoin' : 'Stocks'} · Immutable version {d.id}
        </p>
      </header>
      <div className="flex flex-wrap gap-3">
        <Link className="sw-button" href={'/systems?asset=' + d.asset + '&revise=' + d.id}>
          Copy & revise
        </Link>
        <Link className="sw-button" href={'/backtesting?asset=' + d.asset + '&version=' + d.id}>
          Backtest
        </Link>
        <button className="sw-button" disabled={!session.authenticated || busy} onClick={evaluate}>
          Evaluate 100 scenarios
        </button>
      </div>
      {notice && (
        <p className="sw-notice" role="status">
          {notice}
        </p>
      )}
      <section className="sw-panel space-y-3">
        <h2>Rules & lineage</h2>
        <p className="sw-muted">
          Signals use completed bars. A signal is a decision; an order and a fill are separate
          events.
        </p>
        {d.lineage?.parent_version && (
          <Link
            className="underline"
            href={'/systems/' + d.lineage.parent_version + '?asset=' + d.asset}
          >
            Parent version {d.lineage.parent_version.slice(0, 12)}
          </Link>
        )}
        <Evidence name="Entry, exit, sizing and risk rules" value={d.config} />
        <Evidence name="Parameter changes and research thesis" value={d.lineage} />
      </section>
      <section className="sw-panel space-y-3">
        <h2>Qualification & paper execution</h2>
        <p>
          {d.authorization
            ? 'Experimental historical authorization recorded; current policy, freshness, account and signal checks still apply.'
            : 'No automatic paper authorization recorded.'}
        </p>
        {d.trials.map((t: any) => (
          <div className="border-t py-3" key={t.id}>
            <p>
              {t.status} · {t.stage} · {t.result.passing_scenarios ?? '—'}/100 passing
            </p>
            <p className="sw-muted">
              {t.error ||
                t.result.reasons?.join(' · ') ||
                (t.result.passed
                  ? 'Historical gate passed; not a prediction of future returns.'
                  : 'Awaiting evidence')}
            </p>
            <Evidence name="Evaluation evidence" value={t.result} />
          </div>
        ))}
        <Evidence
          name="Allocation and execution ledger"
          value={{ allocation: d.allocation, authorization: d.authorization, orders: d.orders }}
        />
      </section>
      <ResearchActivity asset={d.asset} mode="systems" version={d.id} />
    </main>
  )
}
export function RunEvidence({ data: d }: { data: any }) {
  const b = d.result.base || {},
    m = d.metrics || {},
    metrics = [
      ['Net return', pct(b.net_return)],
      ['Net profit / loss', money(m.net_pnl)],
      ['Maximum drawdown', pct(b.maximum_drawdown)],
      ['Closed-trade win rate', rate(b.win_rate)],
      ['Closed trades', b.closed_trades ?? '—'],
      [
        'Profit factor',
        m.available ? m.profit_factor?.toFixed(2) || m.profit_factor_note || '—' : 'Unavailable',
      ],
      ['Average winning trade', money(m.average_win)],
      ['Average losing trade', money(m.average_loss)],
      ['Fees', money(b.fees)],
      ['Ending equity', money(b.ending_equity)],
    ]
  return (
    <main className="sw-page space-y-6">
      <Link className="underline" href={'/backtesting?asset=' + d.asset}>
        ← Backtesting
      </Link>
      <header>
        <h1>{d.name || 'Backtest'} · Run evidence</h1>
        <p className="sw-muted">
          {d.id} · Execution {d.status} ·{' '}
          <span className={color(b.net_return)}>{outcome(b.net_return)}</span>
        </p>
      </header>
      <div className="flex flex-wrap gap-3">
        <Link className="sw-button" href={'/systems/' + d.version + '?asset=' + d.asset}>
          System
        </Link>
        <Link
          className="sw-button"
          href={'/systems?asset=' + d.asset + '&revise=' + d.version + '&run=' + d.id}
        >
          Revise from this run
        </Link>
        <a className="sw-button" href={'/api/systems/runs/' + d.id + '?download=1'}>
          Download full evidence
        </a>
      </div>
      {d.error && <p className="sw-notice">{d.error}</p>}
      <section className="sw-panel grid grid-cols-2 lg:grid-cols-5 gap-5">
        {metrics.map(([name, value]) => (
          <div key={name}>
            <p className="sw-muted">{name}</p>
            <p className="font-medium">{value}</p>
          </div>
        ))}
      </section>
      <section className="sw-panel space-y-3">
        <h2>Equity over time</h2>
        <BacktestCurve rows={b.equity_curve || []} />
      </section>
      <section className="sw-panel space-y-3">
        <h2>Closed trades</h2>
        <p className="sw-muted">
          Net of modeled execution fees. Partial exits are combined when a position closes. Showing
          up to 100; full evidence is downloadable.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {['Symbol', 'Entry', 'Exit', 'Cost', 'Net P/L'].map((h) => (
                  <th className="text-left p-2" key={h}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(m.trades || []).slice(-100).map((t: any) => (
                <tr className="border-t" key={t.id}>
                  <td className="p-2">{t.symbol}</td>
                  <td>{t.entry_at?.slice(0, 16)}</td>
                  <td>{t.exit_at?.slice(0, 16)}</td>
                  <td>{money(t.cost)}</td>
                  <td className={color(t.pnl)}>
                    {money(t.pnl)} · {outcome(t.pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="sw-panel space-y-3">
        <h2>What this result establishes</h2>
        <p>
          Historical modeled execution. A completed job is not a qualification or a guarantee.
          Costs, coverage, holdout status and comparisons below are part of the result.
        </p>
        {b.warnings?.map((w: string) => (
          <p className="sw-notice" key={w}>
            {w}
          </p>
        ))}
        {m.available === false && <p className="sw-notice">{m.reason}</p>}
        <Evidence
          name="Benchmarks, holdout and repeated trials"
          value={{
            benchmarks: d.result.benchmarks,
            holdout: d.result.holdout_status,
            trials: d.result.trial_count,
            versions: d.result.distinct_versions_tested,
            coverage: d.result.coverage,
          }}
        />
        <Evidence
          name="Equity curve and fills (display sample; download complete evidence)"
          value={{ curve: b.equity_curve, fills: b.fills, closedTrades: m.trades }}
        />
        <Evidence name="Walk-forward validation and test folds" value={d.result.folds} />
        <Evidence name="Cost stress" value={d.result.double_cost} />
        <Evidence
          name="Frozen configuration, dataset provenance and hashes"
          value={{
            config: d.config,
            manifest: d.manifest,
            dataset: d.result.dataset_sha256,
            configHash: d.result.config_sha256,
            artifact: d.result.result_artifact_sha256,
          }}
        />
        <Evidence
          name="Revision lineage"
          value={{ parent: d.parentVersion, run: d.parentRun, changes: d.changes }}
        />
      </section>
    </main>
  )
}
