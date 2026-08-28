import { NextResponse } from 'next/server'
import { readDashboardBacktests, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET() {
  try {
    return NextResponse.json({ backtests: readDashboardBacktests() })
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) {
      return NextResponse.json({ backtests: [], error: error.message }, { status: 503 })
    }
    throw error
  }
}
