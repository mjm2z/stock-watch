import { NextRequest, NextResponse } from 'next/server'
import { readDashboardSignals, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams
  try {
    const signals = readDashboardSignals({
      decision: params.get('decision') || undefined,
      horizon: optionalNumber(params.get('horizon')),
      minimumScore: optionalNumber(params.get('minimumScore')),
      limit: optionalNumber(params.get('limit')),
    })
    return NextResponse.json({ signals })
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) {
      return NextResponse.json({ signals: [], error: error.message }, { status: 503 })
    }
    throw error
  }
}

function optionalNumber(value: string | null): number | undefined {
  if (value === null || value.trim() === '') return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}
