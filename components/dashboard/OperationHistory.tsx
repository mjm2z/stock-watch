'use client'
import { useState } from 'react'
import type { DashboardOperations } from '@/types/dashboard'
import { formatTimestamp } from '@/lib/utils'
import { commandLabels, incidentText } from '@/lib/dashboard-presentation'
import { StatusBadge } from './StatusBadge'
type Run = DashboardOperations['runs'][number]
export function OperationHistory({ runs }: { runs: Run[] }) {
  const [filter, setFilter] = useState('all'),
    [limit, setLimit] = useState(10)
  const groups = new Map<string, Run[]>()
  for (const run of runs) {
    const job = run.result.job_id ?? run.context.job_id
    const key = job ? `${run.command}:${job}` : run.id
    groups.set(key, [...(groups.get(key) ?? []), run])
  }
  const selected = Array.from(groups.values()).filter(
    (group) => filter === 'all' || group.some((run) => run.status === filter)
  )
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Operation history</h2>
        <label className="text-sm">
          Show{' '}
          <select
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value)
              setLimit(10)
            }}
            className="min-h-11 rounded border bg-background p-2"
          >
            <option value="all">All recent operations</option>
            <option value="failed">Includes failed attempts</option>
            <option value="running">Running</option>
            <option value="succeeded">Includes successes</option>
          </select>
        </label>
      </div>
      <p className="text-xs text-muted-foreground">
        Latest {runs.length} recorded runs. Attempts with the same recorded job are grouped;
        historical failures remain visible.
      </p>
      {!selected.length && (
        <p className="rounded-lg border p-4 text-sm">No operations match this view.</p>
      )}
      {selected.slice(0, limit).map((group) => {
        const latest = group[0]
        return (
          <article key={latest.id} className="space-y-3 rounded-xl border bg-card p-4">
            <div className="flex flex-wrap justify-between gap-2">
              <h3 className="font-medium">
                {commandLabels[latest.command] ?? latest.command.replaceAll('-', ' ')}
              </h3>
              <StatusBadge status={latest.status} />
            </div>
            <p className="text-sm text-muted-foreground">
              {formatTimestamp(latest.startedAt)} ET · {Math.round(latest.durationSeconds)}s ·{' '}
              {group.length} recorded attempt{group.length === 1 ? '' : 's'}
            </p>
            {latest.errorMessage && (
              <p className="text-sm text-loss">{incidentText(latest.errorMessage)}</p>
            )}
            <details>
              <summary className="text-sm">Attempts and technical evidence</summary>
              <ol className="mt-3 space-y-3">
                {group.map((run) => (
                  <li key={run.id} className="rounded border p-3 text-sm">
                    <p>
                      {formatTimestamp(run.startedAt)} ET · {run.status}
                    </p>
                    <p className="mt-1">{run.message ?? 'No status message recorded'}</p>
                    {run.errorMessage && (
                      <p className="mt-2 break-words text-loss">
                        {run.errorType}: {run.errorMessage}
                      </p>
                    )}
                    <details className="mt-2">
                      <summary>Raw audit record</summary>
                      <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">
                        {JSON.stringify(run, null, 2)}
                      </pre>
                    </details>
                  </li>
                ))}
              </ol>
            </details>
          </article>
        )
      })}
      {selected.length > limit && (
        <button
          className="min-h-11 rounded border px-4 text-sm"
          onClick={() => setLimit((n) => n + 10)}
        >
          Show more operations
        </button>
      )}
    </section>
  )
}
