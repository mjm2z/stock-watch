import { PageHeader } from '@/components/PageHeader'
import { PerformanceSummary } from '@/components/dashboard/PerformanceSummary'
import { incidentText } from '@/lib/dashboard-presentation'
import { ExecutionStatus } from '@/components/dashboard/ExecutionStatus'
import Link from 'next/link'
import { StockSearch } from '@/components/StockSearch'
import { MarketOverview } from '@/components/dashboard/MarketOverview'
import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { SignalTable } from '@/components/dashboard/SignalTable'
import { StatusBadge } from '@/components/dashboard/StatusBadge'
import { ResearchQuality } from '@/components/dashboard/ResearchQuality'
import { formatTimestamp } from '@/lib/utils'
import { readDashboardOverview } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'

export default function Home() {
  const overview = readDashboardOverview()

  return (
    <main className="container mx-auto space-y-8 p-4 sm:p-8">
      <PageHeader title="Stocks overview" description="S&P 500 signals, paper execution, and performance against SPY." action={<StockSearch />} />

      <ExecutionStatus />
      {!overview.available ? (
        <DatabaseUnavailable reason={overview.unavailableReason} />
      ) : (
        <>
          <PerformanceSummary />
          <section className="grid gap-6 xl:grid-cols-[1.6fr_0.8fr]">
            <div className="min-w-0">
              <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold">Highest-ranked signals</h2>
                  <p className="text-sm text-muted-foreground">
                    {overview.topSignals[0]
                      ? `Scored ${formatTimestamp(overview.topSignals[0].asOf)} ET · Latest available scored scan`
                      : 'Awaiting scored signals'}
                  </p>
                </div>
                <Link href="/signals" className="text-sm font-medium text-primary hover:underline">
                  View all
                </Link>
              </div>
              <SignalTable signals={overview.topSignals} />
            </div>

            <div>
              <div className="mb-4">
                <h2 className="text-xl font-semibold">Recent scans</h2>
                <p className="text-sm text-muted-foreground">Exchange-calendar execution history</p>
              </div>
              <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
                {overview.recentScans.length ? (
                  overview.recentScans.map((scan) => (
                    <div key={scan.id} className="border-b p-4 last:border-0">
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-medium capitalize">{scan.type} scan</div>
                        <StatusBadge status={scan.status} />
                      </div>
                      <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
                        <time>{formatTimestamp(scan.scheduledFor)}</time>
                        <span>
                          {scan.qualifiedSignals}/{scan.totalSignals} qualified
                        </span>
                      </div>
                      {scan.error ? (
                        <p className="mt-2 text-xs text-loss">
                          {incidentText(scan.error)}{' '}
                          <Link href="/operations" className="underline">
                            Review incident
                          </Link>
                        </p>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <p className="p-6 text-sm text-muted-foreground">No scans have run yet.</p>
                )}
              </div>
            </div>
          </section>
          <MarketOverview />
          <details className="rounded-xl border p-4">
            <summary className="font-semibold">Research coverage and methodology</summary>
            <div className="mt-4">
              <ResearchQuality />
            </div>
          </details>
        </>
      )}
    </main>
  )
}

export const metadata = { title: 'Stocks overview' }
