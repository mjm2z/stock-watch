import { researchDatabase } from '@/lib/research-store'
import { manualHealth } from '@/lib/manual-health'
export const dynamic = 'force-dynamic'
export function GET() {
  try {
    const automated = researchDatabase(false, (db) =>
      db.prepare("SELECT * FROM btc_health WHERE key='execution_owner'").get()
    )
    const manual = manualHealth('owner')
    const healthy = Boolean(
      automated &&
      !automated.error &&
      Date.now() - Date.parse(String(automated.at)) < 90000 &&
      manual.healthy
    )
    return Response.json({ healthy, automated, manual }, { status: healthy ? 200 : 503 })
  } catch {
    return Response.json({ healthy: false, error: 'Execution owner unavailable' }, { status: 503 })
  }
}
