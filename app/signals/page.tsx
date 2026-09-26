import { PageHeader } from '@/components/PageHeader'
import Link from 'next/link'
import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { SignalTable } from '@/components/dashboard/SignalTable'
import {
  readDashboardSignals,
  readSignalSummary,
  WorkerDatabaseUnavailable,
  type SignalFilters,
} from '@/lib/worker-dashboard'
import { decisionReason } from '@/lib/decision-language'
import { easternDayBoundary } from '@/lib/dashboard-presentation'
export const dynamic = 'force-dynamic'
type Params = Record<string, string | undefined>
export default async function SignalsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const p = await searchParams
  const number = (key: string) =>
    p[key] && Number.isFinite(Number(p[key])) ? Number(p[key]) : undefined
  const page = Math.max(1, Math.floor(number('page') ?? 1))
  const timezone = p.timezone ?? 'America/New_York'
  const filters: SignalFilters = {
    symbol: p.symbol,
    strategyId: p.strategyId,
    scanRunId: p.scanRunId,
    reason: p.reason,
    decision: p.decision,
    horizon: number('horizon'),
    minimumScore: number('minimumScore'),
    since: p.since,
    until: p.until,
    timezone,
    limit: 50,
    offset: (page - 1) * 50,
  }
  try {
    let validation = ''
    try {
      if (p.since) easternDayBoundary(p.since)
      if (p.until) easternDayBoundary(p.until)
      if (p.since && p.until && p.since > p.until) validation = 'From must be on or before Through.'
    } catch {
      validation = 'Enter valid calendar dates.'
    }
    const summary = validation ? null : readSignalSummary(filters)
    const signals = validation ? [] : readDashboardSignals(filters)
    const query = new URLSearchParams(
      Object.entries(p).filter(([, v]) => Boolean(v)) as [string, string][]
    )
    query.set('timezone', timezone)
    const pageLink = (n: number) => {
      const q = new URLSearchParams(query)
      q.set('page', String(n))
      return `/signals?${q}`
    }
    const field =
      'mt-1 block min-h-11 w-full min-w-0 rounded-md border bg-background px-3 py-2 text-sm'
    return (
      <main className="container mx-auto space-y-6 p-4 sm:p-8">
        <PageHeader title="Signal ledger" description="Ranked opportunities and their execution history. Modeled outcomes are separate from actual paper fills." />
        <p className="sw-muted">Scores are ranks, not confidence percentages. Four horizons for one company are four observations, not independent forecasts.</p>
        <form className="rounded-xl border bg-card p-4">
          <input type="hidden" name="timezone" value={timezone} />
          {p.scanRunId && <input type="hidden" name="scanRunId" value={p.scanRunId} />}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <label className="text-sm">
              Ticker
              <input
                name="symbol"
                defaultValue={p.symbol}
                placeholder="e.g. AAPL"
                className={field}
              />
            </label>
            <label className="text-sm">
              Decision
              <select name="decision" defaultValue={p.decision ?? ''} className={field}>
                <option value="">All decisions</option>
                <option value="qualified">Score qualified</option>
                <option value="rejected">Not selected</option>
              </select>
            </label>
            <label className="text-sm">
              Holding period
              <select name="horizon" defaultValue={p.horizon ?? ''} className={field}>
                <option value="">All horizons</option>
                {[5, 21, 63, 105].map((n) => (
                  <option key={n} value={n}>
                    {n} trading days
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Minimum rank score
              <input
                name="minimumScore"
                type="number"
                min="0"
                max="100"
                defaultValue={p.minimumScore}
                className={field}
              />
            </label>
          </div>
          <details className="mt-4" open={Boolean(p.strategyId || p.reason || p.since || p.until)}>
            <summary className="text-sm">Strategy, dates and rejection reason</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="text-sm">
                Strategy
                <select name="strategyId" defaultValue={p.strategyId ?? ''} className={field}>
                  <option value="">All strategies</option>
                  {Array.from(
                    new Set([
                      ...(summary?.strategies ?? []),
                      ...(p.strategyId ? [p.strategyId] : []),
                    ])
                  ).map((id) => (
                    <option key={id} value={id}>
                      {id.replaceAll('-', ' ')}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm">
                Rejection reason
                <select name="reason" defaultValue={p.reason ?? ''} className={field}>
                  <option value="">All reasons</option>
                  {Array.from(
                    new Set([...(summary?.reasons ?? []), ...(p.reason ? [p.reason] : [])])
                  ).map((reason) => (
                    <option key={reason} value={reason}>
                      {decisionReason(reason)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm">
                From ({timezone === 'America/New_York' ? 'Eastern' : 'UTC'} date)
                <input name="since" type="date" defaultValue={p.since} className={field} />
              </label>
              <label className="text-sm">
                Through ({timezone === 'America/New_York' ? 'Eastern' : 'UTC'} date)
                <input name="until" type="date" defaultValue={p.until} className={field} />
              </label>
            </div>
          </details>
          <div className="mt-4 flex items-center gap-4">
            <button className="min-h-11 rounded-md bg-primary px-4 text-primary-foreground">
              Apply filters
            </button>
            <Link href="/signals" className="py-3 text-sm underline">
              Clear filters
            </Link>
          </div>
        </form>
        {validation && (
          <p role="alert" className="text-loss">
            {validation}
          </p>
        )}
        {p.scanRunId && (
          <p className="text-sm">
            Showing one exact scan.{' '}
            <Link href="/signals" className="underline">
              Show all scans
            </Link>
            <span className="mt-1 block break-all text-xs text-muted-foreground">
              {p.scanRunId}
            </span>
          </p>
        )}
        {summary && (
          <p className="text-sm text-muted-foreground">
            {summary.total} matching horizon observations · {summary.companies} companies ·{' '}
            {signals.length ? `${(page - 1) * 50 + 1}–${(page - 1) * 50 + signals.length}` : '0'}{' '}
            shown · Page {page}
          </p>
        )}
        <SignalTable signals={signals} returnTo={`/signals?${query}`} />
        <nav aria-label="Signal pages" className="flex flex-wrap items-center gap-4 text-sm">
          {page > 1 && (
            <Link className="py-3 underline" href={pageLink(page - 1)}>
              Previous page
            </Link>
          )}
          {summary && page * 50 < summary.total && (
            <Link className="py-3 underline" href={pageLink(page + 1)}>
              Next page
            </Link>
          )}
          {!!summary?.total && (
            <a
              className="py-3 underline"
              href={`/api/dashboard/signals?${query}&format=csv&limit=500`}
            >
              Export {Math.min(summary.total, 500)} matching rows
              {summary.total > 500 ? ' (first 500 only)' : ''}
            </a>
          )}
        </nav>
      </main>
    )
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable)
      return (
        <main className="container mx-auto p-4 sm:p-8">
          <DatabaseUnavailable reason={error.message} />
        </main>
      )
    throw error
  }
}

export const metadata = { title: 'Signals' }
