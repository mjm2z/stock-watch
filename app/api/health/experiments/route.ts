import { NextResponse } from 'next/server'
import { researchDatabase } from '@/lib/research-store'
export const dynamic = 'force-dynamic'
export async function GET() {
  try {
    const { components, missing } = researchDatabase(false, (db) => {
      const active = new Set(
        db
          .prepare(
            "SELECT asset FROM experiment_batches WHERE status IN ('active','paused','expired','exiting')"
          )
          .all()
          .map((r) => String(r.asset))
      )
      const components = db
        .prepare('SELECT * FROM experiment_health ORDER BY component')
        .all()
        .map((r) => {
          const name = String(r.component)
          const asset = name.split(':').at(-1) || ''
          const conditional = /^(execution|fees|reconciliation):/.test(name)
          const informational =
            name.startsWith('fee-reserve-release:') || (conditional && !active.has(asset))
          const maxAge = name.startsWith('context:') ? 75 * 60_000 : 180_000
          const age = Date.now() - Date.parse(String(r.at))
          return {
            ...r,
            component: name,
            error: r.error || null,
            stale: !informational && (!Number.isFinite(age) || age < 0 || age >= maxAge),
            required: !informational,
          }
        })
      const required = [
        'collection:stocks',
        'collection:bitcoin',
        'stream:stocks',
        'stream:bitcoin',
        'stock-baseline-owner',
        'stock-experiment-owner',
        'preflight:stocks',
        'news',
        'storage',
        'settlement-calendar',
      ]
      for (const asset of active) required.push('execution:' + asset)
      if (active.has('bitcoin')) required.push('bitcoin-experiment-owner', 'preflight:bitcoin')
      const present = new Set(components.map((r) => String(r.component)))
      return { components, missing: required.filter((name) => !present.has(name)) }
    })
    return NextResponse.json({
      status:
        !missing.length && components.every((r) => !r.required || (!r.error && !r.stale))
          ? 'healthy'
          : 'attention',
      components,
      missing,
    })
  } catch {
    return NextResponse.json({ status: 'unavailable' }, { status: 503 })
  }
}
