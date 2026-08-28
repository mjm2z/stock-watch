import Link from 'next/link'
import { formatCurrency } from '@/lib/utils'
import type { DashboardSignal } from '@/types/dashboard'
import { StatusBadge } from './StatusBadge'

export function SignalTable({ signals }: { signals: DashboardSignal[] }) {
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
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3 text-left">Company</th>
              <th className="px-4 py-3 text-right">Score</th>
              <th className="px-4 py-3 text-right">Price</th>
              <th className="px-4 py-3 text-center">Horizon</th>
              <th className="px-4 py-3 text-center">Risk</th>
              <th className="px-4 py-3 text-center">Decision</th>
              <th className="px-4 py-3 text-right">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {signals.map(signal => (
              <tr key={signal.id} className="group border-b last:border-0">
                <td className="px-4 py-4 align-top">
                  <Link href={`/stock/${signal.symbol}`} className="font-semibold hover:text-primary">
                    {signal.symbol}
                  </Link>
                  <div className="max-w-52 truncate text-xs text-muted-foreground">
                    {signal.companyName ?? 'S&P 500 constituent'}
                  </div>
                  <details className="mt-3 max-w-2xl">
                    <summary className="cursor-pointer text-xs font-medium text-primary">
                      Why this score
                    </summary>
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      {signal.explanation}
                    </p>
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      {signal.pillars.map(pillar => (
                        <div key={pillar.name}>
                          <div className="mb-1 flex justify-between text-[11px]">
                            <span className="capitalize">{pillar.name.replaceAll('_', ' ')}</span>
                            <span>{pillar.score === null ? 'Missing' : pillar.score.toFixed(1)}</span>
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
                    {signal.completeness.toFixed(0)}% data
                  </div>
                </td>
                <td className="px-4 py-4 text-right align-top tabular-nums">
                  {signal.currentPrice === null ? '—' : formatCurrency(signal.currentPrice)}
                </td>
                <td className="px-4 py-4 text-center align-top">
                  {signal.horizonTradingDays}d
                </td>
                <td className="px-4 py-4 text-center align-top">
                  <StatusBadge status={signal.risk} />
                </td>
                <td className="px-4 py-4 text-center align-top">
                  <StatusBadge status={signal.decision} />
                  {signal.orderStatus ? (
                    <div className="mt-2 text-[11px] text-muted-foreground">
                      {signal.orderStatus}
                      {signal.notionalUsd ? ` · ${formatCurrency(signal.notionalUsd)}` : ''}
                    </div>
                  ) : null}
                </td>
                <td className="px-4 py-4 text-right align-top tabular-nums">
                  {signal.netReturn === null ? (
                    <span className="text-muted-foreground">Pending</span>
                  ) : (
                    <>
                      <div className={signal.netReturn >= 0 ? 'text-gain' : 'text-loss'}>
                        {(signal.netReturn * 100).toFixed(2)}%
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {signal.beatSpy ? 'Beat SPY' : 'Trailed SPY'}
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
