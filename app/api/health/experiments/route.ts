import { NextResponse } from 'next/server'
import { researchDatabase } from '@/lib/research-store'
export const dynamic = 'force-dynamic'
export async function GET() {
  try {
    const components = researchDatabase(false, (db) =>
      db.prepare('SELECT * FROM experiment_health ORDER BY component').all()
    )
    return NextResponse.json({
      status:
        components.length &&
        components.every((r) => !r.error && Date.now() - Date.parse(String(r.at)) < 180000)
          ? 'healthy'
          : 'attention',
      components,
    })
  } catch {
    return NextResponse.json({ status: 'unavailable' }, { status: 503 })
  }
}
