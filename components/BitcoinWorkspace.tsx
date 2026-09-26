'use client'
import Link from 'next/link'
import { PaperTradingGuide } from './PaperTradingGuide'
import { PageHeader } from './PageHeader'
import { CryptoMarketChart } from './MarketChart'
import { BitcoinSystemResearch } from './BitcoinSystemResearch'
import { useCallback, useEffect, useState } from 'react'
import { OperatorAccess } from './SystemsWorkspace'
type Row = Record<string, unknown>
const object = (v: unknown): Row => {
  try {
    return typeof v === 'string' ? JSON.parse(v) : ((v || {}) as Row)
  } catch {
    return {}
  }
}
const button = 'min-h-11 rounded border px-3 py-2 text-sm disabled:opacity-50'
export function BitcoinWorkspace({ view }: { view: string }) {
  const [data, setData] = useState<Row>({})
  const [systems, setSystems] = useState<Row>({})
  const [automation, setAutomation] = useState<Row>({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [authorized, setAuthorized] = useState(false)
  const refresh = useCallback(async () => {
    try {
      const [networkResponse, systemResponse, automationResponse] = await Promise.all([
        fetch('/api/bitcoin'),
        fetch('/api/systems?asset=bitcoin'),
        fetch('/api/systems/bitcoin').catch(() => null),
      ])
      const [network, system] = await Promise.all([networkResponse.json(), systemResponse.json()])
      if (!networkResponse.ok || !systemResponse.ok) throw new Error(network.error || system.error)
      setData(network)
      setSystems(system)
      if (automationResponse?.ok) setAutomation(await automationResponse.json())
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Monitoring unavailable.')
    }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = setInterval(refresh, 30000)
    return () => clearInterval(timer)
  }, [refresh])
  const network = object(data.network)
  const payload = object(network.payload_json)
  const market = object(data.market)
  const quote = object(object(market.payload_json).quote)
  const marketStale =
    !market.observed_at || Date.now() - Date.parse(String(market.observed_at)) > 120000
  const block = object(payload.block)
  const fees = object(payload.fees)
  const observations = (systems.observations || []) as Row[]
  const portfolio = observations.find((o) => o.kind === 'portfolio')
  const position = object(portfolio?.payload_json)
  const account = object(automation.account)
  const automatedVersions = (automation.versions || []) as Row[]
  const orders = [
    ...((automation.orders || []) as Row[]),
    ...((systems.orders || []) as Row[]),
  ].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
  const stale =
    !network.observed_at || Date.now() - Date.parse(String(network.observed_at)) > 180000
  async function mutate(body: Row) {
    try {
      const response = await fetch('/api/systems', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error)
      setNotice('Saved. Address requests are validated by the monitoring worker.')
      await refresh()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Change failed.')
    }
  }
  return (
    <main className="container mx-auto space-y-6 p-4 sm:p-8">
      <PageHeader
        title={
          view === 'overview'
            ? 'Crypto overview'
            : view === 'paper'
              ? 'Crypto paper portfolio'
              : view === 'blockchain'
                ? 'Blockchain research'
                : view === 'signals'
                  ? 'Crypto signals'
                  : 'Crypto operations'
        }
        description="Bitcoin · BTC/USD · Continuous market · Paper trading only"
      />
      {view === 'paper' && <PaperTradingGuide asset="bitcoin" />}
      {view === 'overview' && <CryptoMarketChart />}
      {view === 'overview' && <BitcoinSystemResearch compact />}
      {error && (
        <p role="alert" className="rounded border border-amber-500 p-3">
          {error}
        </p>
      )}
      {view === 'overview' && !!quote.bp && (
        <section className="rounded-xl border p-5">
          <h2 className="text-xl font-semibold">BTC/USD market</h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-3">
            <Metric
              title="Bid"
              value={quote.bp ? `$${Number(quote.bp).toLocaleString()}` : 'Unavailable'}
            />
            <Metric
              title="Ask"
              value={quote.ap ? `$${Number(quote.ap).toLocaleString()}` : 'Unavailable'}
            />
            <Metric
              title="Spread"
              value={
                quote.bp
                  ? `${((Number(quote.ap) / Number(quote.bp) - 1) * 100).toFixed(3)}%`
                  : 'Unavailable'
              }
            />
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            {marketStale
              ? 'Awaiting fresh market data · check Bitcoin worker configuration'
              : `Alpaca US · ${String(market.observed_at)}`}
          </p>
        </section>
      )}
      {view === 'overview' && !account.id && !portfolio && (
        <section className="sw-panel flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2>From research to paper trading</h2>
            <p className="sw-muted mt-2">
              No paper system is active. Start with a researched idea, review a backtest, then
              collect forward observations.
            </p>
          </div>
          <Link className="sw-button" href="/crypto?view=paper">
            Review paper setup
          </Link>
        </section>
      )}
      {(view === 'overview' && (account.id || portfolio)) || view === 'paper' ? (
        <section className="space-y-3 rounded-xl border p-5">
          <h2 className="text-xl font-semibold">Paper performance</h2>
          {account.id ? (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <Metric
                  title="Conservative net equity"
                  value={
                    account.equity == null
                      ? 'Awaiting a price check'
                      : `$${Number(account.equity).toFixed(2)}`
                  }
                />
                <Metric
                  title="Funded systems"
                  value={String(automatedVersions.filter((v) => v.budget != null).length)}
                />
                <Metric
                  title="Drawdown from peak"
                  value={
                    account.equity == null
                      ? 'Unavailable'
                      : `${((1 - Number(account.equity) / Number(account.high_water)) * 100).toFixed(2)}%`
                  }
                />
              </div>
              <p className="text-sm">
                {account.risk_paused
                  ? 'Risk paused · owned exits remain active'
                  : 'Shared Bitcoin paper account'}{' '}
                ·{' '}
                {account.checked_at
                  ? `Price check ${String(account.checked_at)}`
                  : 'Waiting for the coordinator'}
              </p>
              <p className="text-sm text-muted-foreground">
                Balances reserve estimated fees until settlement.{' '}
                <Link className="underline" href="/systems?asset=bitcoin">
                  Review qualification, allocations, and reconciliation
                </Link>
                .
              </p>
            </>
          ) : portfolio ? (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <Metric
                  title="Modeled net equity"
                  value={`$${Number(position.equity).toFixed(2)}`}
                />
                <Metric title="Cash" value={`$${Number(position.cash).toFixed(2)}`} />
                <Metric
                  title="Drawdown from peak"
                  value={`${(Number(position.drawdown) * 100).toFixed(2)}%`}
                />
              </div>
              <p className="text-sm">
                {position.paused ? 'Paused · exit management active' : 'Paper monitoring active'} ·{' '}
                {position.reconciled ? 'Position reconciled' : 'Reconciliation requires attention'}
              </p>
              <p className="text-xs text-muted-foreground">
                Observed {String(portfolio.observed_at)} · Modeled equity deducts estimated unposted
                fees and additional slippage without double-counting posted fees.
              </p>
            </>
          ) : (
            <p className="text-muted-foreground">
              No Bitcoin paper account has produced a portfolio observation. Configure the separate
              account, backtest a system, and complete shadow review before activation.
            </p>
          )}
          <p className="text-sm">
            Objective: positive net return with no more than 10% portfolio drawdown. A breach
            requests exit and pauses entries; execution may exceed that threshold.
          </p>
        </section>
      ) : null}
      {(view === 'overview' &&
        (observations.length > 0 || automatedVersions.some((v) => v.last_decision_at))) ||
      view === 'signals' ? (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Latest rule decisions</h2>
          {automatedVersions
            .filter((v) => v.last_decision_at)
            .map((v) => (
              <article key={String(v.id)} className="rounded-lg border p-4 text-sm">
                <p className="font-medium">
                  {String(v.template)} · {String(v.id).slice(0, 8)} ·{' '}
                  {String(object(v.paper_state_json).last_action || 'hold')}
                </p>
                <p>{String(object(v.paper_state_json).last_reason || v.reason || '')}</p>
                <p className="text-muted-foreground">{String(v.last_decision_at)}</p>
              </article>
            ))}
          {observations
            .filter((o) => ['shadow', 'decision', 'error', 'warning'].includes(String(o.kind)))
            .slice(0, 10)
            .map((o) => {
              const p = object(o.payload_json)
              return (
                <article className="rounded-lg border p-4" key={String(o.id)}>
                  <h3 className="font-medium">{String(p.action || o.kind)}</h3>
                  <p className="mt-1 text-sm">{String(p.reason || p.message || '')}</p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {String(o.observed_at)} ·{' '}
                    {o.kind === 'shadow' ? 'Shadow observation · no order' : String(o.kind)}
                  </p>
                </article>
              )
            })}
          {!observations.length && (
            <p className="text-muted-foreground">
              No decisions recorded yet. Start a shadow system to observe its hourly rules.
            </p>
          )}
        </section>
      ) : null}
      {view === 'overview' || view === 'blockchain' ? (
        <section className="space-y-4 rounded-xl border p-5">
          <h2 className="text-xl font-semibold">Network conditions</h2>
          <p
            className={`text-sm ${stale ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground'}`}
          >
            {stale ? 'Awaiting fresh network observations' : 'Network observation current'}
            {network.observed_at ? ` · ${String(network.observed_at)}` : ''}
          </p>
          <div className="grid gap-4 sm:grid-cols-3">
            <Metric title="Block height" value={String(block.height ?? 'Unavailable')} />
            <Metric
              title="Pending transactions"
              value={String(object(payload.mempool).count ?? 'Unavailable')}
            />
            <Metric
              title="Fast fee estimate"
              value={fees.fastestFee == null ? 'Unavailable' : `${fees.fastestFee} sat/vB`}
            />
          </div>
          <p className="text-sm text-muted-foreground">
            Congestion and transfers are research observations. They do not establish trading intent
            or generate orders.
          </p>
        </section>
      ) : null}
      {view === 'paper' && (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Orders and actual fills</h2>
          {orders.length === 0 && <p className="text-muted-foreground">No Bitcoin paper orders.</p>}
          {orders.map((o) => (
            <article key={String(o.id)} className="rounded-lg border p-4 text-sm">
              <p className="font-medium">
                {String(o.side)} BTC/USD · {String(o.status)}
              </p>
              <p>
                Filled {String(o.filled_qty)} BTC
                {o.filled_price ? ` at $${Number(o.filled_price).toLocaleString()}` : ''}
              </p>
              <p className="text-xs text-muted-foreground">{String(o.updated_at)}</p>
              {!!o.evaluation_id && (
                <Link
                  className="underline"
                  href={`/systems?asset=bitcoin#evaluation-${String(o.evaluation_id)}`}
                >
                  Review entry evidence
                </Link>
              )}
            </article>
          ))}
        </section>
      )}
      {view === 'operations' && (
        <section className="space-y-4 rounded-xl border p-5">
          <h2 className="text-xl font-semibold">Independent Bitcoin processes</h2>
          <p className="text-sm">
            Network monitoring:{' '}
            {stale
              ? 'awaiting a fresh observation'
              : `last observed ${String(network.observed_at)}`}
          </p>
          <p className="text-sm">
            Market data:{' '}
            {marketStale
              ? 'awaiting a fresh observation'
              : `last observed ${String(market.observed_at)}`}
          </p>
          <p className="text-sm">
            Paper/shadow deployments: {((systems.deployments || []) as Row[]).length}
          </p>
          <p className="text-sm">
            Enrolled automation versions: {automatedVersions.filter((v) => v.active).length}.{' '}
            <Link className="underline" href="/systems?asset=bitcoin">
              Open worker health and evaluations
            </Link>
            .
          </p>
          <p className="text-sm text-muted-foreground">
            A recent observation confirms a completed collection, not that a timer is currently
            enabled. Service failures and configuration require host-level checks.
          </p>
          <h3 className="font-semibold">Recorded errors</h3>
          {[
            ...((data.errors || []) as Row[]),
            ...observations.filter((o) => o.kind === 'error'),
          ].map((e, i) => (
            <p key={i} className="break-words text-sm">
              {String(e.observed_at)} · {String(object(e.payload_json).message || 'Unknown error')}
            </p>
          ))}
          <Link href="/operations" className="inline-block text-sm underline">
            Stock operations and broker reconciliation
          </Link>
        </section>
      )}
      {view === 'blockchain' && (
        <section className="space-y-4">
          <h2 className="text-xl font-semibold">Watch-only addresses</h2>
          <OperatorAccess onChange={setAuthorized} />
          <p className="text-sm">
            Address queries are sent to mempool.space. Labels stay local. Watched balances are
            separate from the paper account; an address list may not represent an entire wallet.
          </p>
          <form
            className="flex flex-wrap gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              const f = new FormData(e.currentTarget)
              void mutate({ action: 'watch', address: f.get('address'), label: f.get('label') })
            }}
          >
            <input
              name="address"
              aria-label="Bitcoin mainnet address"
              required
              maxLength={90}
              placeholder="Public Bitcoin mainnet address"
              className="min-w-0 flex-1 rounded border bg-background p-2"
            />
            <input
              name="label"
              aria-label="Local address label"
              maxLength={120}
              placeholder="Local label"
              className="rounded border bg-background p-2"
            />
            <button disabled={!authorized} className={button}>
              Watch via public API
            </button>
          </form>
          {notice && <p role="status">{notice}</p>}
          {((data.addresses || []) as Row[]).map((a) => {
            const observation = object(a.payload_json)
            const stats = object(observation.stats)
            const chain = object(stats.chain_stats)
            const mempool = object(stats.mempool_stats)
            return (
              <article className="space-y-2 rounded-lg border p-4" key={String(a.address)}>
                <h3 className="font-medium">{String(a.label || 'Unlabeled address')}</h3>
                <p className="break-all font-mono text-xs">{String(a.address)}</p>
                <p className="text-sm">
                  Confirmed:{' '}
                  {a.payload_json
                    ? ((Number(chain.funded_txo_sum) - Number(chain.spent_txo_sum)) / 1e8).toFixed(
                        8
                      ) + ' BTC'
                    : 'Awaiting indexing'}{' '}
                  · Pending change:{' '}
                  {a.payload_json
                    ? (
                        (Number(mempool.funded_txo_sum) - Number(mempool.spent_txo_sum)) /
                        1e8
                      ).toFixed(8) + ' BTC'
                    : 'Unavailable'}
                </p>
                <p className="text-xs text-muted-foreground">
                  History {observation.history_complete ? 'indexed' : 'indexing'} · Checked{' '}
                  {String(a.last_checked_at || 'not yet')}
                </p>
                <button
                  className={button}
                  disabled={!authorized}
                  onClick={() => void mutate({ action: 'unwatch', address: a.address })}
                >
                  Stop watching
                </button>
              </article>
            )
          })}
          {((data.requests || []) as Row[])
            .filter((r) => r.status !== 'succeeded')
            .map((r) => (
              <p key={String(r.id)} role="status" className="break-all text-sm">
                {String(r.address)}: {String(r.status)} {String(r.error || '')}
              </p>
            ))}
          <h3 className="font-semibold">Recent transactions</h3>
          {((data.transactions || []) as Row[]).map((t) => {
            const tx = object(t.payload_json)
            const status = object(tx.status)
            const confirmations =
              status.confirmed && block.height
                ? Math.max(0, Number(block.height) - Number(status.block_height) + 1)
                : 0
            return (
              <div key={`${t.address}:${t.txid}`} className="space-y-1 border-b py-3 text-sm">
                <p className="break-all font-mono text-xs">{String(t.txid)}</p>
                <p>
                  {status.recheck_required
                    ? 'Rechecking after chain reorganization'
                    : status.confirmed
                      ? `${confirmations} confirmations at last observation`
                      : 'Unconfirmed at last observation'}
                </p>
                <p className="text-xs text-muted-foreground">
                  Checked {String(t.observed_at)} · Confirmations may reverse after a
                  reorganization.
                </p>
              </div>
            )
          })}
        </section>
      )}
    </main>
  )
}
function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div>
      <p className="text-sm text-muted-foreground">{title}</p>
      <p className="text-2xl font-semibold">{value}</p>
    </div>
  )
}
