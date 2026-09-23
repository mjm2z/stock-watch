'use client'
import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { formatTimestamp } from '@/lib/utils'
import { incidentText } from '@/lib/dashboard-presentation'
import { utcMillis, type ExecutionStatus as Status } from '@/lib/execution-status-model'
const titles = {
  ready: 'Scheduled and monitored',
  running: 'Scan in progress',
  blocked: 'Paper execution is blocked',
  attention: 'Scan needs attention',
  unknown: 'Readiness is not verified',
}
export function ExecutionStatus() {
  const pathname = usePathname()
  const [status, setStatus] = useState<Status | null>(null),
    [error, setError] = useState<string | null>(null),
    [now, setNow] = useState(Date.now()),
    [retry, setRetry] = useState(0)
  const refreshAgain = useCallback(() => setRetry((n) => n + 1), [])
  useEffect(() => {
    let disposed = false,
      inFlight = false
    let controller: AbortController | null = null
    const refresh = async () => {
      if (inFlight) return
      inFlight = true
      controller = new AbortController()
      const timeout = setTimeout(() => controller?.abort(), 10000)
      try {
        const response = await fetch('/api/dashboard/execution', {
          cache: 'no-store',
          signal: controller.signal,
        })
        const data = await response.json()
        if (!response.ok) throw new Error('Status could not refresh.')
        if (!disposed) {
          setStatus(data)
          setError(null)
        }
      } catch {
        if (!disposed) setError('Status could not refresh. Showing the last received information.')
      } finally {
        clearTimeout(timeout)
        inFlight = false
      }
    }
    void refresh()
    const poll = setInterval(() => void refresh(), 15000)
    const tick = setInterval(() => setNow(Date.now()), 15000)
    window.addEventListener('focus', refresh)
    return () => {
      disposed = true
      controller?.abort()
      clearInterval(poll)
      clearInterval(tick)
      window.removeEventListener('focus', refresh)
    }
  }, [retry])
  const stale = Boolean(status && now - utcMillis(status.generatedAt) > 60000)
  const state = error || stale ? 'unknown' : status?.state
  const latestFailed = status?.latestScan?.status === 'failed'
  const issues = (status?.issues ?? []).filter(
    (issue) =>
      !latestFailed ||
      (!issue.includes('latest scan failed') && !issue.includes('most recent scheduled scan'))
  )
  return (
    <section aria-label="Execution status" className="space-y-4 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{state ? titles[state] : 'Checking execution status…'}</h2>
        {pathname !== '/operations' && (
          <Link href="/operations" className="text-sm underline">
            Review operations
          </Link>
        )}
      </div>
      {(error || stale) && (
        <p role="alert" className="text-sm text-amber-700">
          {error ?? 'Status is over a minute old; readiness is unverified.'}{' '}
          <button className="min-h-11 underline" onClick={refreshAgain}>
            Retry
          </button>
        </p>
      )}
      {status && (
        <>
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">
                Next {status.nextScan?.type ?? ''} scan{error || stale ? ' (unverified)' : ''}
              </dt>
              <dd>
                {status.nextScan
                  ? `${formatTimestamp(status.nextScan.at)} ET`
                  : 'Schedule unavailable'}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Last successful scan</dt>
              <dd>
                {status.lastSuccess
                  ? `${formatTimestamp(status.lastSuccess.completedAt ?? status.lastSuccess.at)} ET`
                  : 'None recorded'}
              </dd>
              {status.lastSuccess && status.lastSuccess.strategyId !== status.strategyId && (
                <p className="text-amber-700">
                  A different strategy; current readiness is not established.
                </p>
              )}
            </div>
            <div>
              <dt className="text-muted-foreground">Broker positions</dt>
              <dd>
                {status.reconciliation?.status === 'matched'
                  ? 'Matched at last check'
                  : (status.reconciliation?.status ?? 'Not checked')}
              </dd>
              <dd className="text-xs text-muted-foreground">
                {status.reconciliation?.at ? `${formatTimestamp(status.reconciliation.at)} ET` : ''}
              </dd>
            </div>
          </dl>
          {latestFailed && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
              <p className="font-medium">
                Last scan failed · {formatTimestamp(status.latestScan!.at)} ET
              </p>
              <p>
                {incidentText(status.latestScan!.error ?? '')} No later successful scan has been
                recorded for this strategy.
              </p>
            </div>
          )}
          {!!issues.length && (
            <ul className="list-disc space-y-1 pl-5 text-sm text-amber-700">
              {(pathname === '/operations' ? issues : issues.slice(0, 2)).map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          )}
          {pathname !== '/operations' && issues.length > 2 && (
            <p className="text-sm">
              <Link href="/operations" className="underline">
                Review {issues.length - 2} additional checks
              </Link>
            </p>
          )}
          <details open={pathname === '/operations'}>
            <summary className="text-sm font-medium">Schedules and data freshness</summary>
            <div className="mt-3 grid gap-4 text-sm sm:grid-cols-2">
              <div>
                <h3 className="font-medium">Scheduled services</h3>
                <ul className="mt-2 space-y-1">
                  {status.timers.map((timer) => (
                    <li key={timer.name}>
                      {timer.name}:{' '}
                      {timer.checked ? (timer.active ? 'enabled' : 'inactive') : 'unverified'} ·{' '}
                      {timer.result ?? 'no result'}
                      {timer.lastRun ? ` · ${formatTimestamp(timer.lastRun)} ET` : ''}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="font-medium">Last successful collections</h3>
                <ul className="mt-2 space-y-1">
                  {status.ingestions.map((item) => (
                    <li key={item.dataset}>
                      {(
                        {
                          historical_calendar: 'Exchange calendar',
                          scan_bundle: 'Prices and news',
                          company_facts: 'Company financials',
                        } as Record<string, string>
                      )[item.dataset] ?? item.dataset.replaceAll('_', ' ')}
                      : {formatTimestamp(item.at)} ET
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-muted-foreground">
                  Collection time does not establish the freshness of every underlying record.
                </p>
              </div>
              <p>
                Next reconciliation and evaluation:{' '}
                {status.nextMaintenance
                  ? `${formatTimestamp(status.nextMaintenance)} ET`
                  : 'Unverified'}
              </p>
              <p className="break-all text-xs text-muted-foreground">
                Strategy: {status.strategyId ?? 'Unavailable'}
              </p>
            </div>
          </details>
          <p className="text-xs text-muted-foreground">
            Status checked {formatTimestamp(status.generatedAt)} ET · Refreshes every 15 seconds
          </p>
        </>
      )}
    </section>
  )
}
