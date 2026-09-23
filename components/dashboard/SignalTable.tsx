import { executionLabel } from '@/lib/dashboard-presentation'
import {
  decisionReason,
  decisionExplanation,
  decisionEvent,
  eventDetails,
} from '@/lib/decision-language'
import Link from 'next/link'
import { formatCurrency, formatTimestamp } from '@/lib/utils'
import type { DashboardSignal } from '@/types/dashboard'
import { StatusBadge } from './StatusBadge'

export function SignalTable({
  signals,
  returnTo = '/signals',
}: {
  signals: DashboardSignal[]
  returnTo?: string
}) {
  if (!signals.length) {
    return (
      <div className="rounded-xl border bg-card p-8 text-center text-sm text-muted-foreground">
        No signals match the current view.
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
      <div className="overflow-x-auto">
        <table className="signal-records w-full text-sm">
          <thead className="border-b bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3 text-left">Company</th>
              <th className="px-4 py-3 text-right">Rank score</th>
              <th className="px-4 py-3 text-right">Cached daily price</th>
              <th className="px-4 py-3 text-center">Horizon</th>
              <th className="px-4 py-3 text-center">Risk</th>
              <th className="px-4 py-3 text-center">Decision</th>
              <th className="px-4 py-3 text-right">Modeled outcome</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((signal) => (
              <tr key={signal.id} className="group border-b last:border-0">
                <td className="px-4 py-4 align-top">
                  <Link
                    href={`/stock/${signal.symbol}?from=${encodeURIComponent(returnTo)}`}
                    className="font-semibold hover:text-primary"
                  >
                    {signal.symbol}
                  </Link>
                  <div className="max-w-52 truncate text-xs text-muted-foreground">
                    {signal.companyName ?? 'S&P 500 constituent'}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {formatTimestamp(signal.asOf)} ET
                  </div>
                  <details className="mt-3 max-w-2xl">
                    <summary className="cursor-pointer text-xs font-medium text-primary">
                      Decision & evaluation history
                    </summary>
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      {decisionExplanation(signal.explanation, signal.reasons)}
                    </p>
                    <dl className="mt-3 space-y-1 text-xs text-muted-foreground">
                      {signal.qualityReview && (
                        <div className="space-y-1 rounded-md border p-2">
                          <div>
                            Underlying metric coverage: {signal.qualityReview.coverage.toFixed(0)}%
                            · Price anomalies: {signal.qualityReview.anomalies}
                          </div>
                          <div>
                            Input blockers:{' '}
                            {signal.qualityReview.blockers.map(decisionReason).join('; ') ||
                              'None detected'}
                          </div>
                          <div>
                            Data notes:{' '}
                            {signal.qualityReview.warnings.map(decisionReason).join('; ') || 'None'}
                          </div>
                          <div>Financial leverage uses total liabilities / equity.</div>
                        </div>
                      )}
                      <div>
                        Reasons:{' '}
                        {signal.reasons.map(decisionReason).join('; ') ||
                          'No rejection reasons recorded'}
                      </div>
                      {signal.orderError && (
                        <div className="text-loss">
                          Order error: {decisionReason(signal.orderError)}
                        </div>
                      )}
                      <div>
                        {signal.evaluationReason ??
                          (signal.decision === 'qualified'
                            ? 'Awaiting the next scheduled outcome evaluation.'
                            : 'Rejected signals with an assessment review are also tracked for research outcomes.')}
                      </div>
                      {signal.evaluationCheckedAt && (
                        <div>Last evaluated: {formatTimestamp(signal.evaluationCheckedAt)} ET</div>
                      )}
                    </dl>
                    <ol className="mt-3 space-y-2 border-l pl-3 text-xs">
                      <li>
                        {formatTimestamp(signal.asOf)} ET · Scored: {signal.decision}
                      </li>
                      {signal.events.map((event, index) => (
                        <li key={index}>
                          <span className="text-muted-foreground">
                            {formatTimestamp(event.at)} ET
                          </span>
                          <br />
                          {decisionEvent(event.type)} · {eventDetails(event.detail)}
                        </li>
                      ))}
                    </ol>
                    <details className="mt-3 text-xs text-muted-foreground">
                      <summary className="cursor-pointer">Technical details</summary>
                      <p className="mt-2 break-all">
                        Strategy: {signal.strategyId}
                        <br />
                        Scan: {signal.scanRunId}
                        <br />
                        Reason codes: {signal.reasons.join(', ') || 'None'}
                      </p>
                      {signal.events.map((event, index) => (
                        <pre key={index} className="mt-2 max-w-md whitespace-pre-wrap break-all">
                          {event.type}: {event.detail}
                        </pre>
                      ))}
                    </details>
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      {signal.pillars.map((pillar) => (
                        <div key={pillar.name}>
                          <div className="mb-1 flex justify-between text-[11px]">
                            <span className="capitalize">{pillar.name.replaceAll('_', ' ')}</span>
                            <span>
                              {pillar.score === null ? 'Missing' : pillar.score.toFixed(1)}
                            </span>
                          </div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full rounded-full bg-primary"
                              style={{ width: `${pillar.score ?? 0}%` }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                </td>
                <td className="px-4 py-4 text-right align-top">
                  <div className="font-semibold tabular-nums">{signal.score.toFixed(1)}</div>
                  <div className="text-xs text-muted-foreground">
                    {signal.completeness.toFixed(0)}% pillar coverage
                  </div>
                </td>
                <td className="px-4 py-4 text-right align-top tabular-nums">
                  {signal.currentPrice === null ? '—' : formatCurrency(signal.currentPrice)}
                  <div className="text-xs text-muted-foreground">
                    {signal.priceAsOf
                      ? signal.priceAsOf.length === 10
                        ? signal.priceAsOf + ' session'
                        : formatTimestamp(signal.priceAsOf) + ' ET'
                      : 'No cached bar'}
                  </div>
                </td>
                <td className="px-4 py-4 text-center align-top">{signal.horizonTradingDays}d</td>
                <td className="px-4 py-4 text-center align-top">
                  <StatusBadge status={signal.risk} />
                </td>
                <td className="px-4 py-4 text-center align-top">
                  <StatusBadge
                    status={signal.decision === 'qualified' ? 'score_qualified' : signal.decision}
                  />
                  <div className="mt-2 text-xs text-muted-foreground">
                    {executionLabel(signal)}
                    {signal.notionalUsd ? ` · ${formatCurrency(signal.notionalUsd)}` : ''}
                  </div>
                </td>
                <td className="px-4 py-4 text-right align-top tabular-nums">
                  {signal.netReturn === null ? (
                    <span className="text-muted-foreground">
                      {decisionReason(signal.evaluationState ?? 'Awaiting evaluation')}
                    </span>
                  ) : (
                    <>
                      {signal.outcomeVersion !== 'alpaca-iex-completed-sessions-v2' && (
                        <div className="text-xs text-amber-600">
                          Legacy result · freshness unverified
                        </div>
                      )}
                      <div className={signal.netReturn >= 0 ? 'text-gain' : 'text-loss'}>
                        {(signal.netReturn * 100).toFixed(2)}%
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {signal.beatSpy === null
                          ? 'Benchmark unavailable'
                          : signal.beatSpy
                            ? 'Beat SPY'
                            : 'Did not beat SPY'}
                      </div>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
