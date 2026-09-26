import { NextRequest, NextResponse } from 'next/server'
import { activity } from '@/lib/research-control'
export const dynamic = 'force-dynamic'
export function GET(r: NextRequest) {
  try {
    return NextResponse.json(activity(r.nextUrl.searchParams))
  } catch {
    return NextResponse.json(
      { error: 'Activity unavailable. Check research migration and worker health.' },
      { status: 503 }
    )
  }
}
