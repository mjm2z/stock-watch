import { PageHeader } from '@/components/PageHeader'
import { OperationHistory } from '@/components/dashboard/OperationHistory'
import { incidentText } from '@/lib/dashboard-presentation'
import { LiquidityDiagnostics } from '@/components/dashboard/LiquidityDiagnostics'
import { ExecutionStatus } from '@/components/dashboard/ExecutionStatus'
import { formatTimestamp } from '@/lib/utils'
import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { StatusBadge } from '@/components/dashboard/StatusBadge'
import { readDashboardOperations, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'

export default function OperationsPage() {
  try {
    const operations = readDashboardOperations()
    return (
      <main className="container mx-auto space-y-8 p-4 sm:p-8">
        <PageHeader title="Operations" description="Job attempts, provider ingestion, and actionable failures." />
        <ExecutionStatus />
        <section>
          <h2 className="mb-4 text-xl font-semibold">Broker reconciliation</h2>
          {operations.brokerReconciliation ? (
            <div className="space-y-4 rounded-xl border bg-card p-5">
              <div className="flex flex-wrap items-center gap-4">
                <StatusBadge status={operations.brokerReconciliation.status} />
                <span className="text-sm text-muted-foreground">
                  Captured {formatTimestamp(operations.brokerReconciliation.capturedAt)}
                </span>
                <span className="text-sm">
                  Full broker account: {operations.brokerReconciliation.accountStatus}
                </span>
                <span className="text-sm">
                  Equity {formatUsd(operations.brokerReconciliation.equityUsd)}
                </span>
                <span className="text-sm">
                  Cash {formatUsd(operations.brokerReconciliation.cashUsd)}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                These are full paper-broker balances. The automated strategy has a separate
                allocation cap shown on Paper.
              </p>
              <div className="grid gap-4 lg:grid-cols-2">
                <PositionList
                  title="Expected strategy positions"
                  positions={operations.brokerReconciliation.expectedPositions}
                />
                <PositionList
                  title="Actual Alpaca positions"
                  positions={operations.brokerReconciliation.actualPositions}
                />
              </div>
              {operations.brokerReconciliation.discrepancies.length ? (
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-loss">
                    Discrepancies blocking entries
                  </h3>
                  <p className="text-sm">
                    {operations.brokerReconciliation.discrepancies.length} recorded discrepancies
                    require review before new entries.
                  </p>
                  <details className="mt-2 text-sm">
                    <summary>Discrepancy evidence</summary>
                    <pre className="overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-3 text-xs">
                      {JSON.stringify(operations.brokerReconciliation.discrepancies, null, 2)}
                    </pre>
                  </details>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Broker quantities match all open strategy lots.
                </p>
              )}
              {operations.brokerReconciliation.corporateActions.length ? (
                <div>
                  <h3 className="mb-2 text-sm font-semibold">Related corporate-action evidence</h3>
                  <details className="text-sm">
                    <summary>
                      {operations.brokerReconciliation.corporateActions.length} corporate-action
                      records
                    </summary>
                    <pre className="overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-3 text-xs">
                      {JSON.stringify(operations.brokerReconciliation.corporateActions, null, 2)}
                    </pre>
                  </details>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="rounded-xl border bg-card p-6 text-sm text-muted-foreground">
              No broker reconciliation has been captured. Paper entries are fail-closed.
            </div>
          )}
        </section>
        <OperationHistory runs={operations.runs} />
        <section>
          <h2 className="mb-4 text-xl font-semibold">Worker jobs</h2>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="p-3 text-left">Scheduled</th>
                  <th className="p-3 text-left">Type</th>
                  <th className="p-3 text-center">Status</th>
                  <th className="p-3 text-right">Attempt</th>
                  <th className="p-3 text-left">Error</th>
                </tr>
              </thead>
              <tbody>
                {operations.jobs.map((job) => (
                  <tr key={job.id} className="border-b last:border-0">
                    <td className="p-3 whitespace-nowrap">{formatTimestamp(job.scheduledFor)}</td>
                    <td className="p-3">{job.type}</td>
                    <td className="p-3 text-center">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="p-3 text-right">{job.attempt}</td>
                    <td className="max-w-md p-3 text-xs">
                      {job.error ? (
                        <details>
                          <summary>{incidentText(job.error)}</summary>
                          <p className="break-all">{job.error}</p>
                        </details>
                      ) : (
                        'No error'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!operations.jobs.length ? (
              <p className="p-6 text-sm text-muted-foreground">No jobs recorded.</p>
            ) : null}
          </div>
        </section>
        <section>
          <h2 className="mb-4 text-xl font-semibold">Data ingestions</h2>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="p-3 text-left">Dataset</th>
                  <th className="p-3 text-left">Provider</th>
                  <th className="p-3 text-center">Status</th>
                  <th className="p-3 text-right">Rows</th>
                  <th className="p-3 text-left">Completed</th>
                </tr>
              </thead>
              <tbody>
                {operations.ingestions.map((item) => (
                  <tr key={item.id} className="border-b last:border-0">
                    <td className="p-3 font-medium">{item.dataset}</td>
                    <td className="p-3">{item.provider}</td>
                    <td className="p-3 text-center">
                      <StatusBadge status={item.status} />
                    </td>
                    <td className="p-3 text-right">{item.rowCount}</td>
                    <td className="p-3">
                      {item.completedAt ? formatTimestamp(item.completedAt) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!operations.ingestions.length ? (
              <p className="p-6 text-sm text-muted-foreground">No ingestions recorded.</p>
            ) : null}
          </div>
        </section>
        <details className="rounded-xl border p-4">
          <summary className="font-semibold">Liquidity and risk diagnostics</summary>
          <div className="mt-4">
            <LiquidityDiagnostics />
          </div>
        </details>
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
      {entries.length ? (
        <ul className="space-y-1 text-sm">
          {entries.map(([symbol, quantity]) => (
            <li key={symbol} className="flex justify-between">
              <span>{symbol}</span>
              <span className="font-mono">
                {Number(quantity).toLocaleString('en-US', { maximumFractionDigits: 9 })}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No positions</p>
      )}
    </div>
  )
}

export const metadata = { title: 'Operations' }
