import Link from 'next/link'
import {
  Activity,
  BadgeDollarSign,
  BriefcaseBusiness,
  Crosshair,
  Gauge,
  ShieldAlert,
} from 'lucide-react'
import { StockSearch } from '@/components/StockSearch'
import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { MetricCard } from '@/components/dashboard/MetricCard'
import { SignalTable } from '@/components/dashboard/SignalTable'
import { StatusBadge } from '@/components/dashboard/StatusBadge'
import { formatCurrency } from '@/lib/utils'
import { readDashboardOverview } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'

export default function Home() {
  const overview = readDashboardOverview()

  return (
    <main className="container mx-auto space-y-8 p-4 sm:p-8">
      <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
        <div>
          <div className="mb-2 flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            <span className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500" /> Research system
            </span>
            {overview.strategyStatus ? <StatusBadge status={overview.strategyStatus} /> : null}
          </div>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Market intelligence</h1>
          <p className="mt-2 max-w-2xl text-muted-foreground">
            Twice-daily S&amp;P 500 signals, paper execution, and performance against SPY.
          </p>
        </div>
        <div className="w-full lg:max-w-md">
          <StockSearch />
        </div>
      </div>

      {!overview.available ? (
        <DatabaseUnavailable reason={overview.unavailableReason} />
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
            <MetricCard
              label="Qualified now"
              value={overview.metrics.qualifiedSignals.toString()}
              detail={overview.latestScan ? `${overview.latestScan.type} scan` : 'No scan yet'}
              icon={Crosshair}
            />
            <MetricCard
              label="Open paper lots"
              value={overview.metrics.openLots.toString()}
              detail={`${formatCurrency(overview.metrics.deployedNotionalUsd)} deployed`}
              icon={BriefcaseBusiness}
            />
            <MetricCard
              label="Positive outcomes"
              value={rate(overview.metrics.positiveRate)}
              detail={`${overview.metrics.completedOutcomes} completed horizons`}
              icon={Activity}
            />
            <MetricCard
              label="Beat SPY"
              value={rate(overview.metrics.beatSpyRate)}
              detail="Identical observation windows"
              icon={Gauge}
            />
            <MetricCard
              label="Realized P&L"
              value={formatCurrency(overview.metrics.realizedPnlUsd)}
              detail="Confidence-adjusted notionals"
              icon={BadgeDollarSign}
            />
            <MetricCard
              label="Failed jobs"
              value={overview.metrics.failedJobs.toString()}
              detail="Requires operational review"
              icon={ShieldAlert}
            />
          </section>

          <section className="grid gap-6 xl:grid-cols-[1.6fr_0.8fr]">
            <div>
              <div className="mb-4 flex items-end justify-between">
                <div>
                  <h2 className="text-xl font-semibold">Highest-confidence signals</h2>
                  <p className="text-sm text-muted-foreground">Latest scan, ranked by heuristic score</p>
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
                  overview.recentScans.map(scan => (
                    <div key={scan.id} className="border-b p-4 last:border-0">
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-medium capitalize">{scan.type} scan</div>
                        <StatusBadge status={scan.status} />
                      </div>
                      <div className="mt-2 flex justify-between text-xs text-muted-foreground">
                        <time>{formatTimestamp(scan.scheduledFor)}</time>
                        <span>{scan.qualifiedSignals}/{scan.totalSignals} qualified</span>
                      </div>
                      {scan.error ? <p className="mt-2 text-xs text-loss">{scan.error}</p> : null}
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

function rate(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/New_York',
    timeZoneName: 'short',
  }).format(new Date(value))
}
