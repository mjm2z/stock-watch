import { NextResponse } from 'next/server'
import { readDashboardOverview } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET() {
  return NextResponse.json(readDashboardOverview())
}
