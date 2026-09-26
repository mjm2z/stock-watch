import Link from 'next/link'
import { researchDatabase } from '@/lib/research-store'

export function SystemPortfolio() {
  try {
    const data = researchDatabase(false, (db) => {
      const control = db
        .prepare(
          'SELECT d.mode,v.template FROM system_stock_control c JOIN system_deployments d ON d.id=c.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE c.id=1'
        )
        .get()
      const positions = db
        .prepare(
          "SELECT o.symbol,SUM(CASE WHEN o.side='buy' THEN CAST(o.filled_qty AS REAL) ELSE -CAST(o.filled_qty AS REAL) END) AS quantity FROM system_orders o JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE v.asset='stocks' GROUP BY o.symbol HAVING quantity>0.000000001"
        )
        .all()
      return { control, positions }
    })
    if (!data.control) return null
    return (
      <section className="space-y-3 rounded-xl border border-primary/40 p-5">
        <h2 className="text-xl font-semibold">Stock systems allocation</h2>
        <p className="text-sm">
          New entries are managed by {String(data.control.template)} ({String(data.control.mode)}).
          Existing strategy lots retain their original exits. The legacy cohort chart below excludes
          systems trades; full-account reconciliation includes both.
        </p>
        {data.positions.length ? (
          <div className="flex flex-wrap gap-4">
            {data.positions.map((p) => (
              <p key={String(p.symbol)} className="text-sm">
                <strong>{String(p.symbol)}</strong> · {Number(p.quantity).toFixed(8)} shares
              </p>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No filled systems positions.</p>
        )}
        <Link href="/systems" className="inline-block text-sm underline">
          Review systems decisions and controls
        </Link>
      </section>
    )
  } catch {
    return null
  }
}
