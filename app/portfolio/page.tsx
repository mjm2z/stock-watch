import { PerformanceSummary } from '@/components/dashboard/PerformanceSummary'
import { PaperLots } from '@/components/dashboard/PaperLots'
import { AssessmentControls } from '@/components/dashboard/AssessmentControls'
import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { EquityCurve } from '@/components/dashboard/EquityCurve'
import { PortfolioMetrics } from '@/components/PortfolioMetrics'
import { TradeTable } from '@/components/TradeTable'
import { formatTimestamp } from '@/lib/utils'
import { readDashboardPortfolio, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'

export default function PortfolioPage() {
  try {
    const portfolio = readDashboardPortfolio()
    const nextExit = portfolio.lots
      .filter((lot) => ['open', 'closing'].includes(lot.status) && lot.targetExitAt)
      .sort((a, b) => a.targetExitAt!.localeCompare(b.targetExitAt!))[0]?.targetExitAt
    return (
      <main className="container mx-auto space-y-10 p-4 sm:p-8">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Paper portfolio</h1>
          <p className="mt-2 text-muted-foreground">
            Automatically placed strategy lots and performance against SPY.
          </p>
        </div>
        <PerformanceSummary />
        <section className="rounded-xl border bg-card p-4">
          <h2 className="font-semibold">Next scheduled exit</h2>
          <p className="mt-1 text-sm">
            {nextExit
              ? formatTimestamp(nextExit) + ' ET · Submission target; fill time may differ'
              : 'No open lots with a recorded exit target.'}
          </p>
        </section>
        <section className="rounded-xl border bg-card p-5 shadow-sm">
          <div className="mb-5">
            <h2 className="text-xl font-semibold">Equity versus SPY</h2>
            <p className="text-sm text-muted-foreground">
              Actual fill cohorts versus equal contributions to SPY
            </p>
          </div>
          <EquityCurve history={portfolio.history} />
        </section>
        <section>
          <h2 className="mb-4 text-xl font-semibold">Automated lots</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            Scheduled exits target five minutes before the horizon’s market close when the
            near-close policy is active. Actual fills determine paper returns; research outcomes use
            the session close as a separate benchmark. Missed windows can execute later.
          </p>
          <PaperLots lots={portfolio.lots} />
        </section>
        <details className="rounded-xl border p-4">
          <summary className="font-semibold">Allocation and entry-check history</summary>
          <div className="mt-4">
            <AssessmentControls />
          </div>
        </details>
        <details className="space-y-5 border-t pt-8">
          <summary className="font-semibold">Legacy manual sandbox · This browser only</summary>
          <div>
            <h2 className="text-xl font-semibold">Manual sandbox</h2>
            <p className="text-sm text-muted-foreground">
              Legacy browser-local trades, kept separate from automated results.
            </p>
          </div>
          <PortfolioMetrics />
          <TradeTable />
        </details>
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
          <details className="space-y-5 border-t pt-8">
            <summary className="font-semibold">Legacy manual sandbox · This browser only</summary>
            <div>
              <h2 className="text-xl font-semibold">Manual sandbox</h2>
              <p className="text-sm text-muted-foreground">
                Browser-local trades remain available while the automated worker is offline.
              </p>
            </div>
            <PortfolioMetrics />
            <TradeTable />
          </details>
        </main>
      )
    }
    throw error
  }
}
