import { Activity, BadgeDollarSign, BriefcaseBusiness, Layers3, Scale, WalletCards } from 'lucide-react'
import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { EquityCurve } from '@/components/dashboard/EquityCurve'
import { MetricCard } from '@/components/dashboard/MetricCard'
import { StatusBadge } from '@/components/dashboard/StatusBadge'
import { PortfolioMetrics } from '@/components/PortfolioMetrics'
import { TradeTable } from '@/components/TradeTable'
import { formatCurrency } from '@/lib/utils'
import {
  readDashboardPortfolio,
  WorkerDatabaseUnavailable,
} from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'

export default function PortfolioPage() {
  try {
    const portfolio = readDashboardPortfolio()
    return (
      <main className="container mx-auto space-y-10 p-4 sm:p-8">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Paper portfolio</h1>
          <p className="mt-2 text-muted-foreground">
            Automatically placed strategy lots and performance against SPY.
          </p>
        </div>
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <MetricCard label="All lots" value={portfolio.totals.lots.toString()} icon={Layers3} />
          <MetricCard label="Open lots" value={portfolio.totals.openLots.toString()} detail={`${formatCurrency(portfolio.totals.deployedNotionalUsd)} deployed`} icon={BriefcaseBusiness} />
          <MetricCard label="Contributed" value={formatCurrency(portfolio.totals.contributedCapitalUsd)} icon={WalletCards} />
          <MetricCard label="Equity" value={formatCurrency(portfolio.totals.equityUsd)} detail={`${formatReturn(portfolio.totals.portfolioReturn)} return`} icon={Activity} />
          <MetricCard label="Realized P&L" value={formatCurrency(portfolio.totals.realizedPnlUsd)} icon={BadgeDollarSign} />
          <MetricCard label="Versus SPY" value={portfolio.totals.excessVsSpyUsd === null ? '—' : formatCurrency(portfolio.totals.excessVsSpyUsd)} detail={`${formatReturn(portfolio.totals.excessReturn)} excess return`} icon={Scale} />
        </section>
        <section className="rounded-xl border bg-card p-5 shadow-sm">
          <div className="mb-5">
            <h2 className="text-xl font-semibold">Equity versus SPY</h2>
            <p className="text-sm text-muted-foreground">Actual fill cohorts versus equal contributions to SPY</p>
          </div>
          <EquityCurve history={portfolio.history} />
        </section>
        <section>
          <h2 className="mb-4 text-xl font-semibold">Automated lots</h2>
          <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
            {portfolio.lots.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b bg-muted/50 text-xs uppercase text-muted-foreground">
                    <tr><th className="p-3 text-left">Ticker</th><th className="p-3 text-right">Score</th><th className="p-3 text-center">Horizon</th><th className="p-3 text-right">Notional</th><th className="p-3 text-right">Entry / exit</th><th className="p-3 text-center">Lot</th><th className="p-3 text-center">Entry / exit order</th><th className="p-3 text-right">Return</th></tr>
                  </thead>
                  <tbody>
                    {portfolio.lots.map(lot => (
                      <tr key={lot.id} className="border-b last:border-0">
                        <td className="p-3 font-semibold">{lot.symbol}</td>
                        <td className="p-3 text-right tabular-nums">{lot.score.toFixed(1)}</td>
                        <td className="p-3 text-center">
                          <div>{lot.horizonTradingDays}d</div>
                          {lot.targetExitAt ? <time className="text-xs text-muted-foreground">{formatDate(lot.targetExitAt)}</time> : null}
                        </td>
                        <td className="p-3 text-right">{formatCurrency(lot.entryNotionalUsd)}</td>
                        <td className="p-3 text-right">
                          <div>{lot.entryPrice === null ? '—' : formatCurrency(lot.entryPrice)}</div>
                          {lot.exitPrice === null ? null : <div className="text-xs text-muted-foreground">{formatCurrency(lot.exitPrice)}</div>}
                        </td>
                        <td className="p-3 text-center"><StatusBadge status={lot.status} /></td>
                        <td className="space-y-1 p-3 text-center">
                          <div><StatusBadge status={lot.orderStatus} /></div>
                          {lot.exitOrderStatus ? <div><StatusBadge status={lot.exitOrderStatus} /></div> : null}
                        </td>
                        <td className={`p-3 text-right font-medium ${returnColor(lot.realizedReturn)}`}>
                          {formatReturn(lot.realizedReturn)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="p-8 text-center text-sm text-muted-foreground">No automated paper lots yet.</p>}
          </div>
        </section>
        <section className="space-y-5 border-t pt-8">
          <div>
            <h2 className="text-xl font-semibold">Manual sandbox</h2>
            <p className="text-sm text-muted-foreground">Legacy browser-local trades, kept separate from automated results.</p>
          </div>
          <PortfolioMetrics />
          <TradeTable />
        </section>
      </main>
    )
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) {
      return (
        <main className="container mx-auto space-y-10 p-4 sm:p-8">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Paper portfolio</h1>
            <p className="mt-2 text-muted-foreground">
              Automated strategy results appear after the worker database is connected.
            </p>
          </div>
          <DatabaseUnavailable reason={error.message} />
          <section className="space-y-5 border-t pt-8">
            <div>
              <h2 className="text-xl font-semibold">Manual sandbox</h2>
              <p className="text-sm text-muted-foreground">
                Browser-local trades remain available while the automated worker is offline.
              </p>
            </div>
            <PortfolioMetrics />
            <TradeTable />
          </section>
        </main>
      )
    }
    throw error
  }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(new Date(value))
}

function formatReturn(value: number | null) {
  if (value === null) return '—'
  return new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 2 }).format(value)
}

function returnColor(value: number | null) {
  if (value === null || value === 0) return 'text-muted-foreground'
  return value > 0 ? 'text-gain' : 'text-loss'
}
