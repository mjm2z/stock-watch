import { AccountPerformance } from './AccountPerformance'
import { Activity, Scale, BadgeDollarSign, ShieldAlert, BriefcaseBusiness } from 'lucide-react'
import { readDashboardPortfolio, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'
import { formatCurrency, formatTimestamp } from '@/lib/utils'
import { MetricCard } from './MetricCard'
export function PerformanceSummary() {
  try {
    const { totals: t, snapshotAt, performanceAvailable } = readDashboardPortfolio()
    const rate = (n: number | null) =>
      performanceAvailable && n !== null ? `${(n * 100).toFixed(2)}%` : 'Unavailable'
    const money = (n: number) => (performanceAvailable ? formatCurrency(n) : 'Unavailable')
    return (
      <section aria-label="Paper performance" className="space-y-3">
        <AccountPerformance />
        <div>
          <h2 className="text-xl font-semibold">Legacy fill-cohort performance</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Scanner-owned lots · Return on accumulated entry cost ·{' '}
            {snapshotAt
              ? `Snapshot ${formatTimestamp(snapshotAt)} ET`
              : 'Awaiting a valued portfolio snapshot'}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
          <MetricCard
            label="Fill-cohort return"
            value={rate(t.portfolioReturn)}
            detail={`Equity ${money(t.equityUsd)}`}
            icon={Activity}
          />
          <MetricCard
            label="Matched SPY return"
            value={rate(t.spyReturn)}
            detail="Matched entry-cost cohorts; bar-price proxy"
            icon={Scale}
          />
          <MetricCard
            label="Excess return"
            value={rate(t.excessReturn)}
            detail={
              performanceAvailable && t.excessVsSpyUsd !== null
                ? `${formatCurrency(t.excessVsSpyUsd)} versus SPY`
                : 'Benchmark unavailable'
            }
            icon={Scale}
          />
          <MetricCard
            label="Realized P&L"
            value={money(t.realizedPnlUsd)}
            detail="Closed scanner lots"
            icon={BadgeDollarSign}
          />
          <MetricCard
            label="Filled capital"
            value={formatCurrency(t.deployedNotionalUsd)}
            detail={`${t.openLots} open lots · ${formatCurrency(t.reservedNotionalUsd ?? 0)} reserved`}
            icon={BriefcaseBusiness}
          />
          <MetricCard
            label="Unrealized P&L"
            value={money(t.unrealizedPnlUsd)}
            detail="Open scanner lots at the recorded marks"
            icon={ShieldAlert}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Returns reflect the recorded snapshot, not a live quote. Each purchase adds capital to
          this constructed cohort; it is not an external account deposit. Idle broker cash is
          excluded. Open-lot counts reflect current order records.
        </p>
      </section>
    )
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable)
      return (
        <p className="text-sm text-muted-foreground">
          Paper performance is unavailable until portfolio data can be read.
        </p>
      )
    throw error
  }
}
