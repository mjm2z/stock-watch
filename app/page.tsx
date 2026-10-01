import { StockMarketChart } from '@/components/StockMarketChart'
import { PageHeader } from '@/components/PageHeader'
import { CompactPerformance } from '@/components/dashboard/CompactPerformance'
import { incidentText } from '@/lib/dashboard-presentation'
import { ExecutionStatus } from '@/components/dashboard/ExecutionStatus'
import Link from 'next/link'
import { MarketOverview } from '@/components/dashboard/MarketOverview'
import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { StatusBadge } from '@/components/dashboard/StatusBadge'
import { ResearchQuality } from '@/components/dashboard/ResearchQuality'
import { formatTimestamp } from '@/lib/utils'
import { readDashboardOverview } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'

export default function Home() {
  const overview = readDashboardOverview()

  return (
    <main className="container mx-auto space-y-8 p-4 sm:p-8">
      <PageHeader
        title="Stocks overview"
        description="Track stocks, compare market performance, and monitor your paper accounts."
      />

      <StockMarketChart />
      <MarketOverview />
      <div className="grid gap-6 xl:grid-cols-2">
        <ExecutionStatus />
        <CompactPerformance />
      </div>
      {!overview.available ? (
        <DatabaseUnavailable reason={overview.unavailableReason} />
      ) : (
        <>
          <section className="grid gap-6 xl:grid-cols-[1.6fr_0.8fr]">
            <details className="sw-panel self-start">
              <summary className="font-semibold">Research coverage and methodology</summary>
              <div className="mt-4">
                <ResearchQuality />
              </div>
            </details>

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
                          {scan.qualifiedSignals}/{scan.totalSignals} horizon assessments qualified
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
        </>
      )}
    </main>
  )
}

export const metadata = { title: 'Stocks overview' }
