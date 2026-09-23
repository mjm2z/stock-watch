import Link from 'next/link'
import type { DashboardPortfolioLot } from '@/types/dashboard'
import { formatCurrency, formatTimestamp } from '@/lib/utils'
import { StatusBadge } from './StatusBadge'
export function PaperLots({ lots }: { lots: DashboardPortfolioLot[] }) {
  if (!lots.length)
    return (
      <p className="rounded-xl border p-6 text-sm text-muted-foreground">
        No automated paper lots yet. Qualified signals must pass entry checks before an order is
        submitted.
      </p>
    )
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {lots.map((lot) => (
        <article key={lot.id} className="space-y-3 rounded-xl border bg-card p-4">
          <div className="flex justify-between gap-2">
            <Link
              href={`/stock/${lot.symbol}?from=%2Fportfolio`}
              className="font-semibold underline"
            >
              {lot.symbol} · {lot.horizonTradingDays} trading days
            </Link>
            <StatusBadge status={lot.status} />
          </div>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted-foreground">Entry order</dt>
              <dd>
                <StatusBadge status={lot.orderStatus} />
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Exit order</dt>
              <dd>
                {lot.exitOrderStatus ? (
                  <StatusBadge status={lot.exitOrderStatus} />
                ) : (
                  'Not submitted'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Filled entry cost</dt>
              <dd>
                {lot.entryPrice !== null && lot.entryQuantity !== null
                  ? formatCurrency(lot.entryPrice * lot.entryQuantity)
                  : 'Awaiting fill'}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Realized return</dt>
              <dd>
                {lot.realizedReturn === null
                  ? lot.status === 'closed'
                    ? 'Unavailable'
                    : 'Awaiting exit'
                  : `${(lot.realizedReturn * 100).toFixed(2)}%`}
              </dd>
            </div>
          </dl>
          <p className="text-sm">
            <span className="text-muted-foreground">Exit submission target: </span>
            {lot.targetExitAt ? `${formatTimestamp(lot.targetExitAt)} ET` : 'Not scheduled'}
          </p>
          {lot.exitOrderError && (
            <details className="text-sm text-loss">
              <summary>Exit needs review</summary>
              <p>{lot.exitOrderError}</p>
            </details>
          )}
          <details className="text-sm">
            <summary>Fill details</summary>
            <dl className="mt-2 space-y-1 text-muted-foreground">
              <div>Requested: {formatCurrency(lot.entryNotionalUsd)}</div>
              <div>
                Entry price:{' '}
                {lot.entryPrice === null ? 'Awaiting fill' : formatCurrency(lot.entryPrice)}
              </div>
              <div>
                Exit price:{' '}
                {lot.exitPrice === null ? 'Awaiting fill' : formatCurrency(lot.exitPrice)}
              </div>
              <div>
                Opened: {lot.openedAt ? `${formatTimestamp(lot.openedAt)} ET` : 'Awaiting fill'}
              </div>
              <div>
                Closed: {lot.closedAt ? `${formatTimestamp(lot.closedAt)} ET` : 'Not closed'}
              </div>
              <div>Rank score: {lot.score.toFixed(1)}</div>
            </dl>
          </details>
        </article>
      ))}
    </div>
  )
}
