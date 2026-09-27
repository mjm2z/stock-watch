import { NextResponse } from 'next/server'
import { researchDatabase } from '@/lib/research-store'
import { assessDiscovery, discoverySchedule } from '@/lib/worker-readiness'
export const dynamic = 'force-dynamic'
export async function GET() {
  try {
    const schedule = await discoverySchedule()
    const checks = researchDatabase(false, (db) => {
      const p = db.prepare('SELECT * FROM research_policies ORDER BY id DESC LIMIT 1').get()!
      const expected: { key: string; maxAge: number }[] = []
      const counts = db
        .prepare('SELECT status,COUNT(*) AS n FROM discovery_trials GROUP BY status')
        .all()
      const count = (state: string) => Number(counts.find((r) => r.status === state)?.n || 0)
      const row = db.prepare("SELECT at,error FROM btc_health WHERE key='discovery'").get()
      const discovery = assessDiscovery({
        enabled: Boolean(p.discovery_enabled),
        schedule,
        heartbeat: row ? { at: String(row.at), error: row.error } : undefined,
        pending: count('queued'),
        blocked: Number(
          db
            .prepare(
              "SELECT COUNT(*) AS n FROM discovery_trials WHERE status='blocked' AND batch_id=(SELECT id FROM discovery_batches ORDER BY created_at DESC LIMIT 1)"
            )
            .get()?.n || 0
        ),
        running: count('running'),
      })
      if (db.prepare('SELECT 1 FROM btc_enrollments WHERE active=1').get())
        expected.push({ key: 'data', maxAge: 120 })
      if (db.prepare('SELECT 1 FROM btc_allocations WHERE started_at IS NOT NULL').get())
        expected.push(
          { key: 'account', maxAge: 120 },
          { key: 'orders', maxAge: 120 },
          { key: 'quote', maxAge: 120 }
        )
      return [
        discovery,
        ...expected.map(({ key, maxAge }) => {
          const row = db.prepare('SELECT at,error FROM btc_health WHERE key=?').get(key)
          const age = row ? (Date.now() - Date.parse(String(row.at))) / 1000 : null
          return {
            worker: key,
            state: row?.error
              ? 'failed'
              : !row || age === null || age < 0 || age > maxAge
                ? 'stale'
                : 'healthy',
            healthy: !!row && !row.error && age !== null && age >= 0 && age <= maxAge,
            ageSeconds: age,
            maxAgeSeconds: maxAge,
            error: row?.error || (!row ? 'Not observed' : null),
          }
        }),
      ]
    })
    const healthy = checks.every((c) => c.healthy)
    return NextResponse.json({ healthy, checks }, { status: healthy ? 200 : 503 })
  } catch {
    return NextResponse.json(
      { healthy: false, error: 'Research database unavailable' },
      { status: 503 }
    )
  }
}
