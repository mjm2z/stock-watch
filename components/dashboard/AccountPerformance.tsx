import { AccountReturnCurve } from '@/components/AccountReturnCurve'
import { accountPerformance } from '@/lib/performance-store'
import { formatCurrency, formatTimestamp } from '@/lib/utils'
export function AccountPerformance({ asset = 'stocks' }: { asset?: 'stocks' | 'bitcoin' }) {
  let data: ReturnType<typeof accountPerformance>
  try {
    data = accountPerformance(asset)
  } catch {
    data = { available: false, reason: 'Account measurement unavailable', result: null }
  }
  const r = data.result
  return (
    <section className="space-y-3 rounded-xl border bg-card p-5" aria-label="Account performance">
      <h2 className="text-xl font-semibold">Paper account performance</h2>
      <p className="text-sm text-muted-foreground">
        Whole {asset === 'bitcoin' ? 'Bitcoin' : 'stock'} account · Includes idle cash ·
        Cash-flow-adjusted observed returns
      </p>
      {data.available && r ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <div>
            <p className="text-sm text-muted-foreground">Account return</p>
            <strong>{(r.return * 100).toFixed(2)}%</strong>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Observed drawdown</p>
            <strong>{(r.maximum_drawdown * 100).toFixed(2)}%</strong>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Dollar equity</p>
            <strong>{formatCurrency(Number(r.equity))}</strong>
          </div>
        </div>
      ) : (
        <p className="text-sm">{data.reason}</p>
      )}
      {'points' in (data || {}) && data?.points && <AccountReturnCurve points={data.points} />}
      {r && (
        <p className="text-xs text-muted-foreground">
          {formatTimestamp(r.since)} – {formatTimestamp(r.as_of)} · {r.observations} observations ·{' '}
          {r.method}. {r.valuation}. Benchmark: {r.benchmark.reason}.
        </p>
      )}
    </section>
  )
}
