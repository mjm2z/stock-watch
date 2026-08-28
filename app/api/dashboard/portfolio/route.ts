import { NextResponse } from 'next/server'
import { readDashboardPortfolio, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET() {
  try {
    return NextResponse.json(readDashboardPortfolio())
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) {
      return NextResponse.json({ lots: [], error: error.message }, { status: 503 })
    }
    throw error
  }
}
