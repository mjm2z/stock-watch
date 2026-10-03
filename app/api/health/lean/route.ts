import { NextResponse } from 'next/server'
import { researchDatabase } from '@/lib/research-store'
export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
export function GET() {
  try {
    const row = researchDatabase(false, (db) =>
      db.prepare('SELECT * FROM lean_runner_health WHERE id=1').get()
    )
    const state = row ? JSON.parse(String(row.payload_json)) : { configured: false, healthy: false }
    const stale = !row || Date.now() - Date.parse(String(row.updated_at)) > 60000
    return NextResponse.json(
      { ...state, healthy: Boolean(state.healthy && !stale), stale, updatedAt: row?.updated_at },
      { status: state.healthy && !stale ? 200 : 503 }
    )
  } catch {
    return NextResponse.json(
      { configured: false, healthy: false, error: 'LEAN health is not installed' },
      { status: 503 }
    )
  }
}
