import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { StatusBadge } from '@/components/dashboard/StatusBadge'
import { readDashboardOperations, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'

export default function OperationsPage() {
  try {
    const operations = readDashboardOperations()
    return (
      <main className="container mx-auto space-y-8 p-4 sm:p-8">
        <div><h1 className="text-3xl font-semibold tracking-tight">Operations</h1><p className="mt-2 text-muted-foreground">Job attempts, provider ingestion, and actionable failures.</p></div>
        <section>
          <h2 className="mb-4 text-xl font-semibold">Broker reconciliation</h2>
          {operations.brokerReconciliation ? (
            <div className="space-y-4 rounded-xl border bg-card p-5">
              <div className="flex flex-wrap items-center gap-4">
                <StatusBadge status={operations.brokerReconciliation.status} />
                <span className="text-sm text-muted-foreground">
                  Captured {formatTimestamp(operations.brokerReconciliation.capturedAt)}
                </span>
                <span className="text-sm">Account {operations.brokerReconciliation.accountStatus}</span>
                <span className="text-sm">Equity {formatUsd(operations.brokerReconciliation.equityUsd)}</span>
                <span className="text-sm">Cash {formatUsd(operations.brokerReconciliation.cashUsd)}</span>
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <PositionList title="Expected strategy positions" positions={operations.brokerReconciliation.expectedPositions} />
                <PositionList title="Actual Alpaca positions" positions={operations.brokerReconciliation.actualPositions} />
              </div>
              {operations.brokerReconciliation.discrepancies.length ? (
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-loss">Discrepancies blocking entries</h3>
                  <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">{JSON.stringify(operations.brokerReconciliation.discrepancies, null, 2)}</pre>
                </div>
              ) : <p className="text-sm text-muted-foreground">Broker quantities match all open strategy lots.</p>}
              {operations.brokerReconciliation.corporateActions.length ? (
                <div>
                  <h3 className="mb-2 text-sm font-semibold">Related corporate-action evidence</h3>
                  <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">{JSON.stringify(operations.brokerReconciliation.corporateActions, null, 2)}</pre>
                </div>
              ) : null}
            </div>
          ) : <div className="rounded-xl border bg-card p-6 text-sm text-muted-foreground">No broker reconciliation has been captured. Paper entries are fail-closed.</div>}
        </section>
        <section>
          <h2 className="mb-4 text-xl font-semibold">Operational runs</h2>
          <div className="space-y-3">
            {operations.runs.map(run => {
              const progress =
                run.progressCurrent !== null && run.progressTotal
                  ? Math.round((run.progressCurrent / run.progressTotal) * 100)
                  : null
              return (
                <article key={run.id} className="rounded-xl border bg-card p-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <StatusBadge status={run.status} />
                    <span className="font-medium">{run.command}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {run.id}
                    </span>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {formatTimestamp(run.startedAt)} · {formatDuration(run.durationSeconds)}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {run.message ?? 'No status message'}
                  </p>
                  {progress !== null ? (
                    <div className="mt-3 flex items-center gap-3">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {run.progressCurrent}/{run.progressTotal} ({progress}%)
                      </span>
                    </div>
                  ) : null}
                  {run.errorMessage ? (
                    <details className="mt-3 rounded-lg border border-red-500/20 bg-red-500/5 p-3">
                      <summary className="cursor-pointer text-sm font-medium text-loss">
                        {run.errorType}: {run.errorMessage}
                      </summary>
                      {run.exceptionChain.length ? (
                        <ol className="mt-3 list-decimal space-y-1 pl-5 text-xs">
                          {run.exceptionChain.map((item, index) => (
                            <li key={index}>
                              <span className="font-mono">{String(item.type)}</span>: {' '}
                              {String(item.message)}
                            </li>
                          ))}
                        </ol>
                      ) : null}
                      {run.traceback ? (
                        <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded bg-background p-3 text-xs">
                          {run.traceback}
                        </pre>
                      ) : null}
                    </details>
                  ) : null}
                  <details className="mt-3 text-xs text-muted-foreground">
                    <summary className="cursor-pointer">Context and result</summary>
                    <pre className="mt-2 overflow-auto rounded bg-muted p-3">
                      {JSON.stringify(
                        {
                          host: run.host,
                          processId: run.processId,
                          heartbeatAt: run.heartbeatAt,
                          context: run.context,
                          result: run.result,
                        },
                        null,
                        2
                      )}
                    </pre>
                  </details>
                </article>
              )
            })}
            {!operations.runs.length ? (
              <p className="rounded-xl border bg-card p-6 text-sm text-muted-foreground">
                No instrumented operations recorded yet.
              </p>
            ) : null}
          </div>
        </section>
        <section>
          <h2 className="mb-4 text-xl font-semibold">Worker jobs</h2>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-sm"><thead className="border-b bg-muted/50 text-xs uppercase text-muted-foreground"><tr><th className="p-3 text-left">Scheduled</th><th className="p-3 text-left">Type</th><th className="p-3 text-center">Status</th><th className="p-3 text-right">Attempt</th><th className="p-3 text-left">Error</th></tr></thead><tbody>
              {operations.jobs.map(job => <tr key={job.id} className="border-b last:border-0"><td className="p-3 whitespace-nowrap">{formatTimestamp(job.scheduledFor)}</td><td className="p-3">{job.type}</td><td className="p-3 text-center"><StatusBadge status={job.status} /></td><td className="p-3 text-right">{job.attempt}</td><td className="max-w-md truncate p-3 text-xs text-loss">{job.error ?? '—'}</td></tr>)}
            </tbody></table>
            {!operations.jobs.length ? <p className="p-6 text-sm text-muted-foreground">No jobs recorded.</p> : null}
          </div>
        </section>
        <section>
          <h2 className="mb-4 text-xl font-semibold">Data ingestions</h2>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-sm"><thead className="border-b bg-muted/50 text-xs uppercase text-muted-foreground"><tr><th className="p-3 text-left">Dataset</th><th className="p-3 text-left">Provider</th><th className="p-3 text-center">Status</th><th className="p-3 text-right">Rows</th><th className="p-3 text-left">Completed</th></tr></thead><tbody>
              {operations.ingestions.map(item => <tr key={item.id} className="border-b last:border-0"><td className="p-3 font-medium">{item.dataset}</td><td className="p-3">{item.provider}</td><td className="p-3 text-center"><StatusBadge status={item.status} /></td><td className="p-3 text-right">{item.rowCount}</td><td className="p-3">{item.completedAt ? formatTimestamp(item.completedAt) : '—'}</td></tr>)}
            </tbody></table>
            {!operations.ingestions.length ? <p className="p-6 text-sm text-muted-foreground">No ingestions recorded.</p> : null}
          </div>
        </section>
      </main>
    )
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) return <main className="container mx-auto p-4 sm:p-8"><DatabaseUnavailable reason={error.message} /></main>
    throw error
  }
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/New_York' }).format(new Date(value))
}

function formatUsd(value: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const remaining = Math.round(seconds % 60)
  return `${minutes}m ${remaining}s`
}

function PositionList({ title, positions }: { title: string; positions: Record<string, unknown> }) {
  const entries = Object.entries(positions)
  return (
    <div className="rounded-lg bg-muted/50 p-4">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {entries.length ? <ul className="space-y-1 text-sm">{entries.map(([symbol, quantity]) => <li key={symbol} className="flex justify-between"><span>{symbol}</span><span className="font-mono">{Number(quantity).toLocaleString('en-US', { maximumFractionDigits: 9 })}</span></li>)}</ul> : <p className="text-sm text-muted-foreground">No positions</p>}
    </div>
  )
}
