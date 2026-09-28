import { manualHealth } from '@/lib/manual-health'
export const dynamic = 'force-dynamic'
export function GET() {
  try {
    const report = manualHealth('notifications')
    return Response.json(report, { status: report.healthy ? 200 : 503 })
  } catch {
    return Response.json({ healthy: false, state: 'unconfigured or unavailable' }, { status: 503 })
  }
}
