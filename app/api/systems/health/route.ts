import { NextResponse } from 'next/server'
import { researchDatabase } from '@/lib/research-store'
export const dynamic = 'force-dynamic'
export function GET() {
  try {
    const checks = researchDatabase(false, (db) => {
      const p = db.prepare('SELECT * FROM research_policies ORDER BY id DESC LIMIT 1').get()!
      const expected: { key: string; maxAge: number }[] = []
      if (p.discovery_enabled) expected.push({ key: 'discovery', maxAge: 27 * 3600 })
      if (db.prepare('SELECT 1 FROM btc_enrollments WHERE active=1').get())
        expected.push({ key: 'data', maxAge: 120 })
      if (db.prepare('SELECT 1 FROM btc_allocations WHERE started_at IS NOT NULL').get())
        expected.push(
          { key: 'account', maxAge: 120 },
          { key: 'orders', maxAge: 120 },
          { key: 'quote', maxAge: 120 }
        )
      return expected.map(({ key, maxAge }) => {
        const row = db.prepare('SELECT at,error FROM btc_health WHERE key=?').get(key)
        const age = row ? (Date.now() - Date.parse(String(row.at))) / 1000 : null
        return {
          worker: key,
          healthy: !!row && !row.error && age !== null && age >= 0 && age <= maxAge,
          ageSeconds: age,
          maxAgeSeconds: maxAge,
          error: row?.error || (!row ? 'Not observed' : null),
        }
      })
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
