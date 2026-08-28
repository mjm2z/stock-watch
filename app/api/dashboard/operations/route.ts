import { NextResponse } from 'next/server'
import { readDashboardOperations, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET() {
  try {
    return NextResponse.json(readDashboardOperations())
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) {
      return NextResponse.json(
        {
          brokerReconciliation: null,
          runs: [],
          jobs: [],
          ingestions: [],
          error: error.message,
        },
        { status: 503 }
      )
    }
    throw error
  }
}
